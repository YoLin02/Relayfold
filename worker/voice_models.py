"""Verified, resumable downloads for the on-demand Windows TTS models."""

import asyncio
from dataclasses import dataclass
import hashlib
import re
import shutil

import httpx


@dataclass(frozen=True)
class Artifact:
    name: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Model:
    size_label: str
    revision: str
    weights: tuple

    @property
    def name(self):
        return f"Qwen3-TTS-12Hz-{self.size_label}-Base"

    @property
    def files(self):
        return self.weights + COMMON

    @property
    def size(self):
        return sum(item.size for item in self.files)

    def urls(self, name):
        return (f"https://modelscope.cn/models/Qwen/{self.name}/resolve/master/{name}",
                f"https://huggingface.co/Qwen/{self.name}/resolve/{self.revision}/{name}")


COMMON = (
    Artifact("generation_config.json", 245, "f1b90b4513f3b34c62851049e2492d7b4c5940daf1276f89c82b8ef04127f3aa"),
    Artifact("merges.txt", 1671839, "599bab54075088774b1733fde865d5bd747cbcc7a547c5bc12610e874e26f5e3"),
    Artifact("preprocessor_config.json", 127, "efdde1022ea9d76928bf7a9cd53139138f5ba2e466e837f08f6105ab1af1c119"),
    Artifact("speech_tokenizer/config.json", 2336, "ee65bb901c876664ab8707c487157aa1a6ee57c65969b28fb5ec9dc211e68167"),
    Artifact("speech_tokenizer/configuration.json", 76, "6bc26d64eb5024b4d1dab5a52371958b429256d6c9d59787f1f5294a54e0cebd"),
    Artifact("speech_tokenizer/model.safetensors", 682293092,
             "836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258"),
    Artifact("speech_tokenizer/preprocessor_config.json", 234,
             "fcb3805e597e786d4067706e602f6688524640f8d3396790e2e09b5942fcbdfb"),
    Artifact("tokenizer_config.json", 7344, "dc3c31c3bdaedd5016382bb3cbe07323026775ad51f5a4fb564505992ae4a670"),
    Artifact("vocab.json", 2776833, "ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910"),
)
MODELS = {model.size_label: model for model in (
    Model("0.6B", "5d83992436eae1d760afd27aff78a71d676296fc", (
        Artifact("config.json", 4494, "2e714c787c8edb98b05432685cddb634add2de4d4e645f653d68251ef72ba011"),
        Artifact("model.safetensors", 1829344272, "180b3b10eb1c9f1b4db7806d5475bae3071c0243c299d49926bab1da3b6946f6"),
    )),
    Model("1.7B", "fd4b254389122332181a7c3db7f27e918eec64e3", (
        Artifact("config.json", 4494, "b4f01752d15a488abde3e1ab44723ae4f4b9e68a4037257b098b3737893cc1f9"),
        Artifact("model.safetensors", 3857413744, "38fc7fc51c5e776e840414b6fd443962e9411b9654888fd7913e4da643cb857c"),
    )),
)}
RANGE_BYTES = 16 * 1024 * 1024


def file_size(path):
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def part_path(target):
    return target.with_name(target.name + ".part")


def placed_file(root, name):
    target = root / name
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("模型目录包含指向其他位置的链接，请重新选择目录。")
    return target


async def transfer_range(client, url, part, total, progress):
    offset = file_size(part)
    end = min(total, offset + RANGE_BYTES) - 1
    headers = {"Range": f"bytes={offset}-{end}", "Accept-Encoding": "identity"}
    async with client.stream("GET", url, headers=headers) as response:
        response.raise_for_status()
        if response.status_code == 206:
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("content-range", ""))
            if not match or tuple(map(int, match.groups())) != (offset, end, total):
                raise ValueError("下载源返回的分段范围不正确。")
        elif response.status_code == 200 and not offset:
            end = total - 1
        else:
            raise ValueError("下载源暂时无法继续分段下载。")
        with part.open("ab" if offset else "wb") as output:
            async for chunk in response.aiter_bytes(256 * 1024):
                if offset + len(chunk) > end + 1:
                    raise ValueError("下载源返回了超出预期的数据。")
                output.write(chunk)
                offset += len(chunk)
                progress(offset)
        if offset != end + 1:
            raise ValueError("连接中断，模型文件尚未下载完整。")


async def fetch_artifact(client, urls, target, artifact, progress):
    target.parent.mkdir(parents=True, exist_ok=True)
    if file_size(target) == artifact.size and await asyncio.to_thread(file_digest, target) == artifact.sha256:
        progress(artifact.size)
        return
    part = part_path(target)
    if part.is_symlink():
        raise ValueError("临时下载文件指向了其他位置，请选择新的下载目录。")
    if file_size(part) > artifact.size:
        part.unlink()
    for start_source in range(len(urls)):
        if start_source and file_size(part) == artifact.size:
            part.unlink()
        while file_size(part) < artifact.size:
            before = file_size(part)
            for attempt in range(len(urls) * 2):
                try:
                    await transfer_range(client, urls[(start_source + attempt) % len(urls)], part, artifact.size, progress)
                    break
                except (httpx.HTTPError, ValueError) as exc:
                    if file_size(part) > before:
                        break
                    if attempt + 1 == len(urls) * 2:
                        raise ValueError("下载中断。请检查网络后重试，已下载的部分会保留。") from exc
                    await asyncio.sleep(0.5 * (attempt + 1))
        if await asyncio.to_thread(file_digest, part) == artifact.sha256:
            part.replace(target)
            progress(artifact.size)
            return
    part.unlink(missing_ok=True)
    raise ValueError("下载文件未通过 SHA-256 校验，请重新下载。")


def model_ready(root, model):
    return bool(root) and all(file_size(root / item.name) == item.size for item in model.files)


async def verify_model(root, model, report):
    if not model_ready(root, model):
        raise ValueError(f"此目录缺少完整的 {model.name} 文件。请选择模型目录，或用下载按钮安装。")
    checked = 0
    for item in model.files:
        if await asyncio.to_thread(file_digest, placed_file(root, item.name)) != item.sha256:
            raise ValueError(f"{item.name} 与官方模型校验值不符，请检查模型版本。")
        checked += item.size
        report(checked)


async def download_model(root, model, report):
    root.mkdir(parents=True, exist_ok=True)
    remaining = sum(max(0, item.size - max(file_size(root / item.name), file_size(part_path(root / item.name))))
                    for item in model.files)
    if shutil.disk_usage(root).free < remaining + 128 * 1024 * 1024:
        raise ValueError("模型下载剩余空间不足，请选择有足够空间的磁盘。")
    completed = 0
    async with httpx.AsyncClient(follow_redirects=True, timeout=35) as client:
        for item in model.files:
            await fetch_artifact(client, model.urls(item.name), placed_file(root, item.name), item,
                                 lambda size: report(completed + size))
            completed += item.size

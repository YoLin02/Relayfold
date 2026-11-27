"""Verified local Whisper runtime and SubRip conversion."""

import asyncio
import hashlib
import os
import platform
import re
import shutil
import tempfile
from pathlib import Path
from zipfile import ZipFile

import httpx

from materials import run, start, stop, tool

WHISPER_VERSION = "1.8.3"
MODEL = "ggml-small-q5_1.bin"
VAD = "ggml-silero-v6.2.0.bin"
RUNTIME = "whisper-bin-x64.zip"
RUNTIME_FILES = ("whisper-cli.exe", "whisper.dll", "ggml.dll", "ggml-base.dll", "ggml-cpu.dll")
ARTIFACTS = {
    RUNTIME: (
        f"https://github.com/ggml-org/whisper.cpp/releases/download/v{WHISPER_VERSION}/{RUNTIME}",
        3968674, "d824b1e37599f882b396e73f1ee0bfd5d0529f700314c48311dcbd00b803321d",
    ),
    MODEL: (
        f"https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/{MODEL}?download=true",
        190085487, "ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb",
    ),
    VAD: (
        f"https://huggingface.co/ggml-org/whisper-vad/resolve/9ffd54a1e1ee413ddf265af9913beaf518d1639b/{VAD}?download=true",
        885098, "2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987",
    ),
}
LANGUAGES = {"auto", "zh", "en", "ja", "ko", "es", "fr", "de"}
STAMP = r"\d{2,3}:[0-5]\d:[0-5]\d[,.]\d{3}"
TIMELINE = re.compile(rf"(?m)^(?:[ \t]*\d+[ \t]*\n)?[ \t]*({STAMP})[ \t]*-->[ \t]*({STAMP})[^\n]*\n")
MAX_SRT_BYTES = 8 * 1024 * 1024
MAX_CUES = 12000
MAX_MS = 360_000_000


def stamp_ms(stamp):
    hours, minutes, seconds, millis = map(int, re.split(r"[:,.]", stamp))
    return (hours * 3600 + minutes * 60 + seconds) * 1000 + millis


def time_stamp(value):
    seconds, millis = divmod(value, 1000)
    minutes, second = divmod(seconds, 60)
    hour, minute = divmod(minutes, 60)
    return f"{hour:02}:{minute:02}:{second:02},{millis:03}"


def validate_cues(cues):
    if not isinstance(cues, list) or not 1 <= len(cues) <= MAX_CUES:
        raise ValueError("字幕需要包含 1 至 12000 条有效内容。")
    clean = []
    for index, cue in enumerate(cues, 1):
        if not isinstance(cue, dict):
            raise ValueError(f"第 {index} 条字幕格式不正确。")
        start_ms, end_ms, text = cue.get("startMs"), cue.get("endMs"), cue.get("text")
        if (type(start_ms) is not int or type(end_ms) is not int or not 0 <= start_ms < end_ms <= MAX_MS
                or not isinstance(text, str) or not text.strip() or len(text) > 2000):
            raise ValueError(f"第 {index} 条字幕需填写正文，且结束时间应晚于开始时间。")
        text = re.sub(r"\n[ \t]*\n+", "\n", text.replace("\r\n", "\n").replace("\r", "\n").strip())
        if "\x00" in text or re.search(rf"(?m)^{STAMP}\s*-->\s*{STAMP}", text):
            raise ValueError(f"第 {index} 条正文包含无效控制字符或时间轴。")
        clean.append({"startMs": start_ms, "endMs": end_ms, "text": text})
    clean.sort(key=lambda item: item["startMs"])
    if sum(len(cue["text"]) for cue in clean) > 2_000_000:
        raise ValueError("字幕正文过长，请分段处理。")
    return clean


def read_srt(path):
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("没有识别到可用字幕。")
    if path.stat().st_size > MAX_SRT_BYTES:
        raise ValueError("字幕文件过大，请分段处理。")
    raw = path.read_bytes()
    try:
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = raw.decode("utf-16")
        else:
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("gb18030")
    except UnicodeDecodeError as exc:
        raise ValueError("无法读取字幕编码，请保存为 UTF-8 SRT 后重试。") from exc
    text = text.replace("\r\n", "\n").replace("\r", "\n") + "\n"
    markers = list(TIMELINE.finditer(text))
    cues = []
    for index, marker in enumerate(markers):
        stop_at = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        start_ms, end_ms = map(stamp_ms, marker.groups())
        line = text[marker.end():stop_at].strip()
        if line and end_ms > start_ms:
            cues.append({"startMs": start_ms, "endMs": end_ms, "text": line})
    if not cues:
        raise ValueError("没有识别到可用字幕。")
    return validate_cues(cues)


def render_srt(cues):
    return "\n".join(f"{index}\n{time_stamp(cue['startMs'])} --> {time_stamp(cue['endMs'])}\n{cue['text']}\n"
                     for index, cue in enumerate(cues, 1))


async def fetch_artifact(home, name, progress):
    url, expected_size, expected_digest = ARTIFACTS[name]
    target = home / name
    temporary = home / (name + ".part")
    try:
        async with asyncio.timeout(900), httpx.AsyncClient(follow_redirects=True, timeout=40) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                digest = hashlib.sha256()
                size = 0
                last_percent = -5
                with temporary.open("wb") as output:
                    async for chunk in response.aiter_bytes(512 * 1024):
                        size += len(chunk)
                        if size > expected_size:
                            raise ValueError("字幕组件校验失败，请重试。")
                        digest.update(chunk)
                        output.write(chunk)
                        percent = int(size * 100 / expected_size)
                        if percent >= last_percent + 5:
                            progress(percent)
                            last_percent = percent
        if size != expected_size or digest.hexdigest() != expected_digest:
            raise ValueError("字幕组件校验失败，请重试。")
        temporary.replace(target)
    except (httpx.HTTPError, TimeoutError) as exc:
        raise ValueError("下载本地字幕组件失败，请检查网络后重试。") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return target


def unpack_runtime(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive) as package:
        for name in RUNTIME_FILES:
            with package.open(f"Release/{name}") as source, (destination / name).open("wb") as output:
                shutil.copyfileobj(source, output)


class Whisper:
    def __init__(self, root):
        self.home = Path(os.environ.get("RELAYFOLD_CAPTION_HOME") or root / "caption-models").resolve()

    async def prepare(self, progress):
        if platform.system() != "Windows" or platform.machine().lower() not in {"amd64", "x86_64"}:
            raise ValueError("本地语音识别目前支持 Windows x64。")
        self.home.mkdir(parents=True, exist_ok=True)
        runtime = self.home / f"whisper-{WHISPER_VERSION}"
        if not all((runtime / name).is_file() for name in RUNTIME_FILES):
            progress("setup", None, "正在下载本地语音识别引擎")
            archive = await fetch_artifact(self.home, RUNTIME, lambda _: None)
            # Only extract the specific executable and libraries from the verified release.
            with tempfile.TemporaryDirectory(prefix="unpack-", dir=self.home) as staging:
                await asyncio.to_thread(unpack_runtime, archive, Path(staging) / "bin")
                if runtime.exists():
                    shutil.rmtree(runtime)
                (Path(staging) / "bin").replace(runtime)
            archive.unlink(missing_ok=True)
        for name in (MODEL, VAD):
            local = self.home / name
            if not local.is_file() or local.stat().st_size != ARTIFACTS[name][1]:
                progress("setup", 0, "正在下载本地字幕模型")
                await fetch_artifact(self.home, name, lambda value: progress("setup", value, "正在下载本地字幕模型"))
        return runtime / "whisper-cli.exe"

    async def transcribe(self, source, language, progress):
        executable = await self.prepare(progress)
        with tempfile.TemporaryDirectory(prefix="speech-", dir=self.home) as folder:
            root = Path(folder)
            progress("audio", None, "正在提取视频音频")
            await run(tool("ffmpeg"), "-v", "error", "-protocol_whitelist", "file,pipe", "-i", str(source),
                      "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(root / "voice.wav"),
                      timeout=1800)
            progress("recognizing", 0, "正在本地识别语音")
            await self.recognize(executable, root, language, progress)
            try:
                return await asyncio.to_thread(read_srt, root / "captions.srt")
            except ValueError as exc:
                if str(exc) == "没有识别到可用字幕。":
                    raise ValueError("没有识别到清晰的人声字幕，请检查音轨或调整语言。") from exc
                raise

    async def recognize(self, executable, root, language, progress):
        process = await start(str(executable), "-m", f"../{MODEL}", "-f", "voice.wav", "-l", language, "-ng",
                              "-t", str(min(8, os.cpu_count() or 4)), "--vad", "-vm", f"../{VAD}",
                              "-ml", "72", "-pp", "-osrt", "-of", "captions", cwd=root)
        drain = asyncio.create_task(process.stdout.read())
        try:
            last = -1
            async with asyncio.timeout(14400):
                while line := await process.stderr.readline():
                    match = re.search(rb"progress\s*=\s*(\d+)%", line)
                    if match:
                        percent = min(99, int(match[1]))
                        if percent > last:
                            progress("recognizing", percent, "正在本地识别语音")
                            last = percent
                if await process.wait():
                    raise ValueError("本地语音识别没有完成，请检查素材音频后重试。")
        except TimeoutError as exc:
            raise ValueError("语音识别超时，请缩短视频后重试。") from exc
        finally:
            if process.returncode is None:
                await stop(process)
            await asyncio.gather(drain, return_exceptions=True)

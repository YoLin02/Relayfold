"""Provision an optional, isolated Windows CUDA runtime for Qwen3-TTS."""

import json
import logging
import platform
import shutil
import tempfile
from pathlib import Path
from zipfile import ZipFile

import httpx

from materials import run
from voice_models import Artifact, fetch_artifact

UV = Artifact("uv-x86_64-pc-windows-msvc.zip", 17891221,
              "cae6a3bc25239f83dffb467a4b180508d9da23986c04639ebfa44e43e6a84bff")
UV_RELEASE = f"https://github.com/astral-sh/uv/releases/download/0.12.18/{UV.name}"
PYTHON_VERSION = "3.11.14"
RUNTIME_DIR = "Qwen3-TTS-CUDA128"
ENGINE = Path(__file__).resolve().with_name("voice_engine.py")
PYPI = "https://pypi.org/simple"


async def engine_job(python, scratch, action, **args):
    job = scratch / "job.json"
    job.write_text(json.dumps({"action": action, **args}, ensure_ascii=False), encoding="utf-8")
    try:
        output = await run(str(python), "-I", "-B", "-X", "utf8", str(ENGINE), str(job), cwd=scratch,
                           timeout=1800, extra_env={"TEMP": str(scratch), "TMP": str(scratch)})
        return json.loads(output.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise ValueError("配音引擎未返回有效结果，请检查所选环境。") from exc
    except ValueError as exc:
        if "ModuleNotFoundError" in str(exc) or "ImportError" in str(exc):
            raise ValueError(f"配音环境缺少依赖。请安装配音环境，或选择完整的 Qwen3-TTS Python。{exc}") from exc
        raise


async def install_runtime(folder, report):
    if platform.system() != "Windows" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise ValueError("自动安装配音环境支持 Windows x64 和 NVIDIA CUDA 显卡。")
    root = folder / RUNTIME_DIR
    if not root.resolve().is_relative_to(folder.resolve()):
        raise ValueError("配音环境目录指向了其他位置，请选择新的存放目录。")
    root.mkdir(parents=True, exist_ok=True)
    python = root / "environment" / "Scripts" / "python.exe"
    if not python.is_file() and shutil.disk_usage(root).free < 12 * 1024**3:
        raise ValueError("首次安装配音环境需要至少 12 GiB 可用空间，包括安装缓存。请更改存放目录。")

    archive = root / UV.name
    executable = root / "uv.exe"
    report("正在下载并校验环境安装工具", 0)
    async with httpx.AsyncClient(follow_redirects=True, timeout=40) as client:
        await fetch_artifact(client, (UV_RELEASE,), archive, UV,
                             lambda size: report("正在下载并校验环境安装工具", int(size * 100 / UV.size)))
    with tempfile.TemporaryDirectory(prefix="installer-", dir=root) as directory:
        with ZipFile(archive) as package:
            staged = Path(package.extract("uv.exe", directory))
        staged.replace(executable)

    cache = root / "cache"
    temp = root / "temporary"
    temp.mkdir(exist_ok=True)
    env = {"UV_PYTHON_INSTALL_DIR": str(root / "python"), "TEMP": str(temp), "TMP": str(temp)}

    async def uv(*args):
        await run(str(executable), "--no-config", "--no-progress", "--system-certs", "--cache-dir", str(cache),
                  *args, cwd=root, extra_env=env, timeout=2700)

    report("正在准备专用 Python 环境", None)
    await uv("python", "install", "--no-bin", "--no-registry", PYTHON_VERSION)
    if not python.is_file():
        await uv("venv", "--python", PYTHON_VERSION, "--managed-python", str(python.parent.parent))
    install = ("pip", "install", "--python", str(python))
    report("正在下载并安装 PyTorch CUDA 组件，首次安装需要较长时间", None)
    await uv(*install, "--index", "https://download.pytorch.org/whl/cu128", "--default-index", PYPI,
             "torch==2.8.0+cu128", "torchaudio==2.8.0+cu128")
    report("正在安装语音推理依赖", None)
    await uv(*install, "--default-index", PYPI, "transformers==4.57.3", "accelerate==1.12.0", "librosa==0.11.0",
             "soundfile==0.14.0", "safetensors==0.8.0", "onnxruntime==1.30.0", "sox==1.5.0", "einops==0.8.2",
             "numpy==2.4.6", "numba==0.67.0")
    # The desktop inference process uses the Qwen library API, without its Gradio demo.
    await uv(*install, "--default-index", PYPI, "--no-deps", "qwen-tts==0.1.1")
    try:
        await uv("cache", "clean")
    except (OSError, ValueError):
        logging.warning("Could not clean the isolated TTS installer cache")
    return python

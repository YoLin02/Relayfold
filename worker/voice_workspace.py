"""Persist local voice profiles and coordinate the optional voice workflow."""

import asyncio
import json
import logging
import math
import os
import re
import shutil
import tempfile
from pathlib import Path

from materials import run, tool
from store import new_id, now
from voice_models import MODELS, download_model, file_size, model_ready, verify_model
from voice_runtime import engine_job, install_runtime

AUDIO = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
LANGUAGES = {"Auto", "Chinese", "English", "Japanese", "Korean", "German", "French", "Russian", "Portuguese", "Spanish", "Italian"}
MAX_TEXT = 1200


def local_path(value):
    path = Path(value) if isinstance(value, str) and "\0" not in value else Path()
    if not path.is_absolute():
        raise ValueError("请选择有效的本地路径。")
    return path


def clean_text(value, limit, error):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\0" in value:
        raise ValueError(error)
    return value.strip()


def safe_export_name(name):
    return "配音-" + re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", name).strip(" .")[:60] + ".wav"


async def audio_seconds(path):
    result = await run(tool("ffprobe"), "-v", "error", "-protocol_whitelist", "file,pipe", "-select_streams", "a:0",
                       "-show_entries", "stream=index,duration:format=duration", "-of", "json", str(path))
    data = json.loads(result)
    if data.get("streams"):
        for raw in (data["streams"][0].get("duration"), data.get("format", {}).get("duration")):
            try:
                duration = float(raw)
                if math.isfinite(duration) and duration > 0:
                    return duration
            except (TypeError, ValueError):
                continue
    raise ValueError("无法读取有效的音频时长，请换一个录音文件。")


def copy_new(source, destination):
    with tempfile.TemporaryDirectory(prefix=".relayfold-audio-", dir=destination.parent) as directory:
        staged = Path(directory) / "配音.wav"
        shutil.copyfile(source, staged)
        if os.name == "nt":
            staged.rename(destination)
        else:
            os.link(staged, destination)


class VoiceWorkspace:
    def __init__(self, store, root, recognizer, send):
        self.db = store.db
        self.data = root / "voice-data"
        self.default_directory = root / "voice-models"
        self.recognizer = recognizer
        self.send = send
        self.job = None
        self.status = None
        self.reference = None
        with self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS voice_profiles (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, model TEXT NOT NULL, revision TEXT NOT NULL,
                reference_text TEXT NOT NULL, created_at TEXT NOT NULL
            )""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS voice_outputs (
                id TEXT PRIMARY KEY, voice_name TEXT NOT NULL, duration REAL NOT NULL, text TEXT NOT NULL,
                created_at TEXT NOT NULL
            )""")

    def setting(self, key):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", ("voice:" + key,)).fetchone()
        return row["value"] if row else ""

    def save_setting(self, key, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", ("voice:" + key, str(value)))
        self.changed()

    @property
    def directory(self):
        return Path(self.setting("directory") or self.default_directory)

    @property
    def python(self):
        file = self.setting("python")
        return Path(file) if file and Path(file).is_file() else None

    def model_path(self, key):
        directory = self.setting("model:" + key)
        return Path(directory) if directory and model_ready(Path(directory), MODELS[key]) else None

    def profile_dir(self, identifier):
        return self.data / "profiles" / identifier

    def output_file(self, identifier):
        return self.data / "outputs" / (identifier + ".wav")

    def snapshot(self):
        models = [{"id": key, "bytes": model.size, "ready": bool(self.model_path(key))}
                  for key, model in MODELS.items()]
        profiles = []
        for row in self.db.execute("SELECT id,name,model,revision,created_at FROM voice_profiles ORDER BY rowid DESC"):
            folder = self.profile_dir(row["id"])
            profiles.append({"id": row["id"], "name": row["name"], "model": row["model"], "createdAt": row["created_at"],
                             "available": bool(file_size(folder / "tone.safetensors")),
                             "hasReference": bool(file_size(folder / "reference.wav")),
                             "compatible": MODELS[row["model"]].revision == row["revision"]})
        outputs = [{"id": row["id"], "voiceName": row["voice_name"], "duration": row["duration"], "text": row["text"],
                    "available": bool(file_size(self.output_file(row["id"])))}
                   for row in self.db.execute("SELECT * FROM voice_outputs ORDER BY rowid DESC LIMIT 50")]
        reference = {k: self.reference[k] for k in ("id", "name", "duration")} if self.reference else None
        return {"directory": str(self.directory), "runtime": {"ready": bool(self.python), "device": self.setting("device")},
                "models": models, "profiles": profiles, "outputs": outputs, "reference": reference, "job": self.status}

    def changed(self):
        self.send({"event": "voice"})

    def idle(self):
        if self.job is not None:
            raise ValueError("已有配音任务正在运行，请等待完成或取消。")

    def report(self, detail, progress=None):
        if (detail, progress) != (self.status["detail"], self.status["progress"]):
            self.status.update(detail=detail, progress=progress)
            self.changed()

    def begin(self, kind, detail, action, *args):
        self.idle()
        self.status = {"id": new_id(), "kind": kind, "status": "running", "progress": None, "detail": detail, "result": None}
        task = asyncio.create_task(self.perform(action, *args))
        self.job = task
        self.changed()
        return self.status["id"]

    async def perform(self, action, *args):
        try:
            self.status.update(status="ready", result=await action(*args), progress=None, detail="")
        except asyncio.CancelledError:
            self.status.update(status="canceled", progress=None, detail="任务已取消。")
            raise
        except (OSError, ValueError) as exc:
            self.status.update(status="failed", progress=None, detail=str(exc)[:650] or "配音任务失败。")
        except Exception:
            logging.exception("Voice workspace operation failed")
            self.status.update(status="failed", progress=None, detail="配音任务失败，请检查录音和模型后重试。")
        finally:
            self.job = None
            self.changed()

    async def cancel(self):
        if self.job:
            task = self.job
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if self.job is task:
                self.job = None
                self.status.update(status="canceled", progress=None, detail="任务已取消。")
                self.changed()

    def scratch(self):
        work = self.data / "work"
        work.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(prefix="job-", dir=work)

    def set_directory(self, value):
        self.idle()
        directory = local_path(value).resolve() / "Relayfold-TTS"
        directory.mkdir(parents=True, exist_ok=True)
        self.save_setting("directory", directory)

    @staticmethod
    def model_spec(key):
        if not isinstance(key, str) or key not in MODELS:
            raise ValueError("请选择支持的 Qwen3-TTS 克隆模型。")
        return MODELS[key]

    async def prepare_model(self, key, local):
        model = self.model_spec(key)
        progress = lambda size: self.report("正在校验本机模型" if local else "正在下载并校验模型",
                                            min(99, int(size * 100 / model.size)))
        folder = local or self.directory / model.name
        if local:
            await verify_model(folder, model, progress)
        else:
            if not folder.resolve().is_relative_to(self.directory.resolve()):
                raise ValueError("模型目录指向了其他位置，请选择新的下载目录。")
            await download_model(folder, model, progress)
        self.save_setting("model:" + key, folder)
        return {"model": key}

    async def prepare_runtime(self, python):
        if python is None:
            python = await install_runtime(self.directory, self.report)
        self.report("正在检测 CUDA 和配音依赖")
        with self.scratch() as directory:
            device = (await engine_job(python, Path(directory), "probe"))["device"]
        with self.db:
            self.db.executemany("INSERT OR REPLACE INTO settings VALUES (?,?)",
                                (("voice:python", str(python)), ("voice:device", device)))

    def engine_inputs(self, key):
        self.model_spec(key)
        if not self.python:
            raise ValueError("请先安装配音环境，或选择现有的 Python 环境。")
        model = self.model_path(key)
        if model is None:
            raise ValueError("请先下载或选择这个模型的本机目录。")
        return self.python, str(model)

    async def select_reference(self, value):
        self.idle()
        path = local_path(value)
        if path.suffix.lower() not in AUDIO or not path.is_file():
            raise ValueError("请选择 WAV、MP3、M4A、AAC、FLAC、OGG 或 OPUS 录音。")
        duration = await audio_seconds(path)
        self.idle()
        if duration < 3:
            raise ValueError("请使用至少 3 秒的清晰单人录音。")
        self.reference = {"id": new_id(), "name": path.name, "duration": duration, "path": path}
        self.changed()

    def selection(self, args):
        selected = self.reference
        if not selected or args.get("reference") != selected["id"] or not selected["path"].is_file():
            raise ValueError("请选择本地参考录音。")
        start, end = args.get("start"), args.get("end")
        if (type(start) not in (int, float) or type(end) not in (int, float) or not 0 <= start < end <= selected["duration"] + 0.01
                or not 2.995 <= end - start <= 30):
            raise ValueError("参考片段请选 3 到 30 秒，并确保时间范围在录音内。")
        return selected["path"], start, end - start

    async def normalize(self, reference, output):
        path, start, duration = reference
        await run(tool("ffmpeg"), "-v", "error", "-protocol_whitelist", "file,pipe", "-ss", str(start), "-i", str(path),
                  "-t", str(duration), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(output))
        if await audio_seconds(output) < 2.98:
            raise ValueError("选取的录音太短，请重新选择参考片段。")

    async def transcribe(self, selection, reference_id):
        with self.scratch() as directory:
            clip = Path(directory) / "reference.wav"
            await self.normalize(selection, clip)
            cues = await self.recognizer.transcribe(clip, "auto", lambda _, percent, detail: self.report(detail, percent))
        text = "\n".join(cue["text"] for cue in cues).strip()
        return {"transcript": text[:2000], "reference": reference_id}

    def commit_profile(self, staged, name, key, reference_text):
        identifier = new_id()
        target = self.profile_dir(identifier)
        target.parent.mkdir(parents=True, exist_ok=True)
        staged.rename(target)
        try:
            with self.db:
                self.db.execute("INSERT INTO voice_profiles VALUES (?,?,?,?,?,?)",
                                (identifier, name, key, MODELS[key].revision, reference_text, now()))
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise
        return {"profile": identifier}

    async def clone(self, name, key, selection, reference_text):
        python, model = self.engine_inputs(key)
        with self.scratch() as directory:
            scratch = Path(directory)
            staged = scratch / "profile"
            staged.mkdir()
            reference = staged / "reference.wav"
            await self.normalize(selection, reference)
            self.report("正在提取参考音色", None)
            await engine_job(python, scratch, "clone", model=model, reference=str(reference), reference_text=reference_text,
                             profile=str(staged / "tone.safetensors"))
            return self.commit_profile(staged, name, key, reference_text)

    async def import_preset(self, directory):
        key = "1.7B"
        python, _ = self.engine_inputs(key)
        name = directory.name[:80] or "导入音色"
        reference, transcript, legacy = (directory / filename for filename in ("reference.wav", "reference.txt", "voice_profile.pt"))
        if any(path.is_symlink() for path in (reference, transcript, legacy)):
            raise ValueError("音色目录包含指向其他位置的链接。")
        if file_size(reference) and 0 < file_size(transcript) <= 8192:
            text = transcript.read_text(encoding="utf-8-sig").strip()
            if text and len(text) <= 2000:
                duration = min(30, await audio_seconds(reference))
                return await self.clone(name, key, (reference, 0, duration), text)
        if not 0 < file_size(legacy) <= 2 * 1024 * 1024:
            raise ValueError("请选择包含 reference.wav 和 reference.txt，或 voice_profile.pt 的旧音色目录。")
        with self.scratch() as directory:
            scratch = Path(directory)
            staged = scratch / "profile"
            staged.mkdir()
            self.report("正在转换旧音色文件")
            result = await engine_job(python, scratch, "import", legacy=str(legacy), profile=str(staged / "tone.safetensors"))
            if file_size(reference):
                duration = min(30, await audio_seconds(reference))
                await self.normalize((reference, 0, duration), staged / "reference.wav")
            return self.commit_profile(staged, name, key, result["reference_text"])

    def row(self, table, identifier, error):
        if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{32}", identifier):
            raise ValueError(error)
        result = self.db.execute(f"SELECT * FROM {table} WHERE id=?", (identifier,)).fetchone()
        if result is None:
            raise ValueError(error)
        return result

    async def generate(self, profile, text, language, mode):
        key = profile["model"]
        python, model = self.engine_inputs(key)
        cached = self.profile_dir(profile["id"]) / "tone.safetensors"
        if profile["revision"] != MODELS[key].revision or not file_size(cached):
            raise ValueError("音色文件缺失或模型版本已变更，请重新创建音色。")
        with self.scratch() as directory:
            scratch = Path(directory)
            audio = scratch / "voice.wav"
            self.report("正在合成配音")
            result = await engine_job(python, scratch, "generate", model=model, profile=str(cached), text=text,
                                      reference_text=profile["reference_text"], language=language, mode=mode, output=str(audio))
            if not file_size(audio) or not 0 < result["duration"] <= 900:
                raise ValueError("生成的音频无效，请缩短文案后重试。")
            identifier = new_id()
            target = self.output_file(identifier)
            target.parent.mkdir(parents=True, exist_ok=True)
            audio.rename(target)
            try:
                with self.db:
                    self.db.execute("INSERT INTO voice_outputs VALUES (?,?,?,?,?)",
                                    (identifier, profile["name"], result["duration"], text, now()))
            except Exception:
                target.unlink(missing_ok=True)
                raise
        return {"output": identifier}

    def file(self, identifier, kind):
        if kind == "reference":
            row = self.row("voice_profiles", identifier, "音色已不存在。")
            path, name = self.profile_dir(identifier) / "reference.wav", row["name"] + ".wav"
        elif kind == "output":
            row = self.row("voice_outputs", identifier, "配音记录已不存在。")
            path, name = self.output_file(identifier), safe_export_name(row["voice_name"])
        else:
            raise ValueError("请选择要试听的录音或配音。")
        if not file_size(path) or not path.resolve().is_relative_to(self.data.resolve()):
            raise ValueError("音频文件已移动或删除。")
        return {"path": str(path), "name": name}

    async def export(self, identifier, value):
        source = Path(self.file(identifier, "output")["path"])
        destination = local_path(value)
        if destination.suffix.lower() != ".wav" or not destination.parent.is_dir():
            raise ValueError("请选择有效的 WAV 保存位置。")
        try:
            await asyncio.to_thread(copy_new, source, destination)
        except FileExistsError as exc:
            raise ValueError("目标文件已存在，请选择新的文件名。") from exc
        return str(destination)

    def manage(self, identifier, name=None, *, delete=False, output=False):
        self.idle()
        table = "voice_outputs" if output else "voice_profiles"
        self.row(table, identifier, "这条记录已不存在。")
        if delete:
            with self.db:
                self.db.execute(f"DELETE FROM {table} WHERE id=?", (identifier,))
            try:
                if output:
                    self.output_file(identifier).unlink(missing_ok=True)
                elif self.profile_dir(identifier).is_dir():
                    shutil.rmtree(self.profile_dir(identifier))
            except OSError:
                logging.warning("Could not clean up a deleted voice workspace file")
        else:
            name = clean_text(name, 80, "请输入 1 到 80 个字符的音色名称。")
            with self.db:
                self.db.execute("UPDATE voice_profiles SET name=? WHERE id=?", (name, identifier))
        self.changed()

    async def dispatch(self, method, args):
        key = args.get("model")
        identifier = args.get("id")
        if method == "snapshot":
            return self.snapshot()
        if method == "cancel":
            return await self.cancel()
        if method == "directory":
            return self.set_directory(args.get("path"))
        if method in {"runtime.install", "runtime.use"}:
            path = local_path(args.get("path")) if method == "runtime.use" else None
            if path and (path.name.lower() != "python.exe" or not path.is_file()):
                raise ValueError("请选择 Qwen3-TTS 环境的 python.exe。")
            return self.begin("runtime", "正在准备配音环境", self.prepare_runtime, path)
        if method in {"model.download", "model.use"}:
            self.model_spec(key)
            path = local_path(args.get("path")).resolve() if method == "model.use" else None
            return self.begin("model", "正在准备模型", self.prepare_model, key, path)
        if method == "reference.select":
            return await self.select_reference(args.get("path"))
        if method == "transcribe":
            return self.begin("transcribe", "正在读取参考录音", self.transcribe, self.selection(args), args.get("reference"))
        if method == "clone":
            name = clean_text(args.get("name"), 80, "请输入 1 到 80 个字符的音色名称。")
            text = clean_text(args.get("referenceText"), 2000, "请填写参考录音原文，也可以先自动识别。")
            self.engine_inputs(key)
            return self.begin("clone", "正在读取参考录音", self.clone, name, key, self.selection(args), text)
        if method == "import":
            folder = local_path(args.get("path")).resolve()
            if not folder.is_dir():
                raise ValueError("请选择一份已有音色的目录。")
            return self.begin("import", "正在读取旧音色", self.import_preset, folder)
        if method == "generate":
            row = self.row("voice_profiles", identifier, "音色已不存在。")
            text = clean_text(args.get("text"), MAX_TEXT, f"请填写 1 到 {MAX_TEXT} 个字符的配音文案。")
            language, mode = args.get("language"), args.get("mode")
            if not isinstance(language, str) or language not in LANGUAGES or mode not in ("icl", "timbre"):
                raise ValueError("请选择有效的配音语言和方式。")
            self.engine_inputs(row["model"])
            return self.begin("generate", "正在准备配音", self.generate, row, text, language, mode)
        if method == "profile.rename":
            return self.manage(identifier, args.get("name"))
        if method in {"profile.delete", "output.delete"}:
            return self.manage(identifier, delete=True, output=method == "output.delete")
        if method == "file":
            return self.file(identifier, args.get("kind"))
        if method == "output.export":
            return await self.export(identifier, args.get("path"))
        raise ValueError("未知的配音操作。")

"""Local material library and Bilibili download queue."""

import asyncio
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

from store import new_id, now

VIDEOS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
TEXT_SUBTITLES = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text", "ttml"}
SIDECAR_SUBTITLES = {".srt", ".vtt", ".ass", ".ssa"}
BILI_VIDEO = re.compile(r"/video/((?i:BV)[A-Za-z0-9]{10}|av[0-9]+)/?")
DOWNLOADER = ["--ignore-config", "--no-playlist", "--no-colors", "--no-warnings", "--socket-timeout", "15", "--retries", "1"]
DOWNLOAD_OPTIONS = DOWNLOADER + ["--use-extractors", "BiliBili"]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def bilibili_url(value):
    if not isinstance(value, str) or len(value) > 2000:
        raise ValueError("请粘贴 B 站视频链接。")
    for candidate in re.findall(r"https://[^\s<>\"]+", value):
        try:
            url = urlsplit(candidate.rstrip("，。！？、；）》】,.)"))
        except ValueError:
            continue
        if url.username or url.password or url.netloc not in {"bilibili.com", "www.bilibili.com", "m.bilibili.com", "b23.tv"}:
            continue
        if url.netloc == "b23.tv" and re.fullmatch(r"/[A-Za-z0-9]+/?", url.path):
            return f"https://b23.tv{url.path}"
        video = BILI_VIDEO.fullmatch(url.path)
        if video and url.netloc != "b23.tv":
            page = parse_qs(url.query).get("p", ["1"])[0]
            suffix = f"?p={page}" if re.fullmatch(r"[1-9][0-9]{0,3}", page) and page != "1" else ""
            return f"https://www.bilibili.com/video/{video[1]}{suffix}"
    raise ValueError("请输入 B 站视频链接或 b23.tv 分享短链接。")


def tool(name):
    executable = shutil.which(name)
    if not executable:
        raise ValueError(f"找不到 {name}。请安装 FFmpeg，并将其加入 PATH。")
    return executable


async def expand_short_link(url):
    if urlsplit(url).hostname != "b23.tv":
        return url
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=12) as client:
            async with client.stream("GET", url) as response:
                target = bilibili_url(response.headers.get("Location"))
    except (httpx.HTTPError, ValueError) as exc:
        raise ValueError("分享链接无法展开，请改用 B 站视频页面的完整链接。") from exc
    if urlsplit(target).hostname == "b23.tv":
        raise ValueError("分享链接无法展开，请改用 B 站视频页面的完整链接。")
    return target


async def start(*args, cwd=None, extra_env=None):
    return await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.DEVNULL,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                creationflags=NO_WINDOW,
                                                cwd=cwd,
                                                env={**os.environ, "PYTHONIOENCODING": "utf-8", **(extra_env or {})},
                                                limit=1024 * 1024)


async def stop(process):
    if process.returncode is not None:
        return
    if sys.platform == "win32":
        killer = await asyncio.create_subprocess_exec("taskkill.exe", "/PID", str(process.pid), "/T", "/F",
                                                     stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                                                     creationflags=NO_WINDOW)
        await killer.wait()
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    await process.wait()


async def run(*args, timeout=50, cwd=None, extra_env=None):
    process = await start(*args, cwd=cwd, extra_env=extra_env)
    try:
        output, errors = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError as exc:
        await stop(process)
        raise ValueError("媒体工具响应超时，请检查网络或文件后重试。") from exc
    except asyncio.CancelledError:
        await stop(process)
        raise
    if process.returncode:
        raise ValueError(command_error(errors))
    return output.decode("utf-8", errors="replace")


def command_error(output):
    lines = [line.strip() for line in output.decode("utf-8", errors="replace").splitlines() if line.strip()]
    return (lines[-1] if lines else "媒体工具没有完成任务。")[:650]


def ytdlp(*args):
    return (sys.executable, "-B", "-m", "yt_dlp", *DOWNLOAD_OPTIONS, *args)


def local_video(value):
    if not isinstance(value, str):
        raise ValueError("请选择本地视频。")
    path = Path(value)
    if not path.is_absolute() or path.suffix.lower() not in VIDEOS or not path.is_file():
        raise ValueError("视频文件不存在或格式不受支持。")
    return path.resolve()


async def probe(path):
    raw = await run(tool("ffprobe"), "-v", "error", "-protocol_whitelist", "file,pipe", "-show_streams",
                    "-show_format", "-of", "json", str(path))
    data = json.loads(raw)
    streams = data.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"
                  and not stream.get("disposition", {}).get("attached_pic")), None)
    if not video:
        raise ValueError("这个文件没有可识别的视频轨。")
    duration = data.get("format", {}).get("duration")
    seconds = float(duration) if duration and duration != "N/A" else None
    if seconds is not None and not math.isfinite(seconds):
        seconds = None
    tracks = []
    for stream in streams:
        if stream.get("codec_type") != "subtitle":
            continue
        tags = stream.get("tags", {})
        codec = stream.get("codec_name", "")
        index = stream["index"]
        tracks.append({"id": f"stream:{index}", "label": tags.get("title") or tags.get("language") or f"字幕轨 {len(tracks) + 1}",
                       "codec": codec, "convertible": codec in TEXT_SUBTITLES})
    for sidecar in sorted(path.parent.iterdir()):
        if (sidecar.suffix.lower() in SIDECAR_SUBTITLES and sidecar.is_file()
            and (sidecar.stem == path.stem or sidecar.stem.startswith(path.stem + "."))):
            tracks.append({"id": f"file:{sidecar.name}", "label": sidecar.name, "codec": sidecar.suffix[1:], "convertible": True})
            if len(tracks) >= 50:
                break
    rotation = next((entry["rotation"] for entry in video.get("side_data_list", []) if "rotation" in entry), 0)
    return {"duration": seconds, "width": video.get("width"), "height": video.get("height"), "rotation": rotation,
            "has_audio": any(stream.get("codec_type") == "audio" for stream in streams),
            "size": path.stat().st_size, "subtitles": tracks}


def srt_destination(value):
    path = Path(value) if isinstance(value, str) else Path()
    if not path.is_absolute() or path.suffix.lower() != ".srt" or not path.parent.is_dir():
        raise ValueError("请指定有效的 SRT 保存路径。")
    return path


class Materials:
    def __init__(self, store, root, emit):
        self.db = store.db
        preferred_directory = os.environ.get("RELAYFOLD_MATERIAL_ROOT")
        self.default_directory = Path(root / "materials").resolve()
        self.emit = emit
        self.resolved = {}
        self.jobs = {}
        self.queue = asyncio.Semaphore(1)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS material_assets (
                id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, title TEXT NOT NULL, source TEXT NOT NULL,
                details TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS material_downloads (
                id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT NOT NULL, height INTEGER NOT NULL,
                subtitle_language TEXT NOT NULL DEFAULT '',
                directory TEXT NOT NULL, status TEXT NOT NULL, progress REAL,
                detail TEXT NOT NULL, asset_id TEXT, created_at TEXT NOT NULL
            );
        """)
        with self.db:
            if preferred_directory:
                self.db.execute("INSERT OR IGNORE INTO settings VALUES ('material_directory', ?)",
                                (str(Path(preferred_directory).resolve()),))
            self.db.execute("""UPDATE material_downloads SET status='failed', detail='上次下载已中断，可以重试。'
                WHERE status IN ('queued','downloading')""")

    def changed(self):
        self.emit({"event": "materials"})

    def directory(self):
        entry = self.db.execute("SELECT value FROM settings WHERE key='material_directory'").fetchone()
        return Path(entry["value"]) if entry else self.default_directory

    def set_directory(self, value):
        path = Path(value)
        if not path.is_absolute() or not path.is_dir():
            raise ValueError("请选择存在的下载目录。")
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES ('material_directory', ?)", (str(path.resolve()),))
        self.changed()

    @staticmethod
    def public_asset(row):
        item = dict(row)
        details = json.loads(item.pop("details"))
        return {**item, **details, "available": Path(item["path"]).is_file()}

    def snapshot(self):
        return {"directory": str(self.directory()), "assets": [self.public_asset(row) for row in self.db.execute(
            "SELECT * FROM material_assets ORDER BY created_at DESC LIMIT 250")],
            "downloads": [dict(row) for row in self.db.execute(
            "SELECT id,title,height,status,progress,detail,asset_id FROM material_downloads ORDER BY created_at DESC LIMIT 100")]}

    def asset(self, identifier):
        row = self.db.execute("SELECT * FROM material_assets WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise ValueError("找不到这条素材。")
        return self.public_asset(row)

    async def add(self, value, title=None, source="local"):
        path = local_video(value)
        details = await probe(path)
        with self.db:
            asset = self.register(path, details, title or path.stem, source)
        self.changed()
        return asset

    def register(self, path, details, title, source):
        self.db.execute("""INSERT INTO material_assets VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET details=excluded.details""",
            (new_id(), str(path), title, source, json.dumps(details, ensure_ascii=False), now()))
        return self.public_asset(self.db.execute("SELECT * FROM material_assets WHERE path=?", (str(path),)).fetchone())

    async def resolve(self, value):
        url = await expand_short_link(bilibili_url(value))
        data = json.loads(await run(*ytdlp("--skip-download", "--dump-single-json", "--", url), timeout=65))
        if data.get("_type") == "playlist":
            raise ValueError("请粘贴单个视频或指定分 P 的链接。")
        heights = sorted({item["height"] for item in data.get("formats", [])
                          if item.get("vcodec") not in {None, "none"} and type(item.get("height")) is int
                          and 1 <= item["height"] <= 4320}, reverse=True)
        if not heights:
            raise ValueError("这个视频没有返回可供选择的清晰度。")
        languages = set(data.get("subtitles") or {}) | set(data.get("automatic_captions") or {})
        thumbnail = data.get("thumbnail") or ""
        image_url = urlsplit(thumbnail)
        result = {"id": new_id(), "title": data.get("title") or "B站视频", "url": url,
                  "duration": data.get("duration"), "resolutions": heights,
                  "thumbnail": thumbnail if image_url.scheme == "https" and (image_url.hostname or "").endswith(".hdslb.com") else "",
                  "subtitles": sorted(lang for lang in languages if re.fullmatch(r"[A-Za-z0-9_-]{1,35}", lang)
                                      and lang not in {"danmaku", "live_chat"})}
        self.resolved[result["id"]] = result
        if len(self.resolved) > 24:
            self.resolved.pop(next(iter(self.resolved)))
        return result

    def enqueue(self, resolution_id, height, language):
        video = self.resolved.get(resolution_id)
        if not video or type(height) is not int or height not in video["resolutions"]:
            raise ValueError("请重新解析链接并选择有效清晰度。")
        if not isinstance(language, str) or (language and language not in video["subtitles"]):
            raise ValueError("请选择有效的字幕语言。")
        identifier = new_id()
        with self.db:
            self.db.execute("""INSERT INTO material_downloads
                (id,url,title,height,subtitle_language,directory,status,progress,detail,asset_id,created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'queued', NULL, '', NULL, ?)""",
                (identifier, video["url"], video["title"], height, language, str(self.directory()), now()))
        self.launch(identifier)
        return identifier

    def update_job(self, identifier, status, detail="", progress=None, asset_id=None):
        with self.db:
            self.db.execute("UPDATE material_downloads SET status=?,detail=?,progress=?,asset_id=? WHERE id=?",
                            (status, detail, progress, asset_id, identifier))
        self.changed()

    def launch(self, identifier):
        self.jobs[identifier] = asyncio.create_task(self.download(identifier))
        self.jobs[identifier].add_done_callback(lambda _task: self.jobs.pop(identifier, None))
        self.changed()

    def job(self, identifier):
        row = self.db.execute("SELECT * FROM material_downloads WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise ValueError("找不到该下载任务。")
        return row

    async def cancel(self, identifier):
        job = self.jobs.get(identifier)
        if job and not job.done():
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)
            if self.job(identifier)["status"] in {"queued", "downloading"}:
                self.update_job(identifier, "canceled", "下载已取消。")

    def retry(self, identifier):
        if self.job(identifier)["status"] not in {"failed", "canceled"} or identifier in self.jobs:
            raise ValueError("当前下载不能重试。")
        self.update_job(identifier, "queued")
        self.launch(identifier)

    async def fetch_file(self, job, folder):
        identifier, height = job["id"], job["height"]
        selection = (f"bv*[height={height}][ext=mp4]+ba[ext=m4a]/bv*[height={height}]+ba/"
                     f"b[height={height}]")
        folder.mkdir(parents=True, exist_ok=True)
        subtitle = job["subtitle_language"]
        subtitles = ["--write-subs", "--write-auto-subs", "--sub-langs", f"^{re.escape(subtitle)}$",
                     "--sub-format", "srt/vtt/best", "--convert-subs", "srt"] if subtitle else []
        cmd = ytdlp("--ffmpeg-location", tool("ffmpeg"), "--format", selection, "--merge-output-format", "mp4",
                    "--remux-video", "mp4", "--paths", str(folder), "-o", "%(title).96B [%(id)s].%(ext)s",
                    *subtitles,
                    "--ignore-errors", "--progress", "--newline", "--progress-delta", "0.35",
                    "--progress-template", "download:relayprogress:%(progress._percent_str)s",
                    "--print", "after_move:relayfile:%(filepath)j", "--", job["url"])
        process = await start(*cmd)
        errors = asyncio.create_task(process.stderr.read())
        file = None
        try:
            while line := await asyncio.wait_for(process.stdout.readline(), timeout=120):
                text = line.decode("utf-8", errors="replace").strip()
                if text.startswith("relayfile:"):
                    file = Path(json.loads(text.removeprefix("relayfile:"))).resolve()
                elif text.startswith("relayprogress:"):
                    percent = re.search(r"(\d+(?:\.\d+)?)%", text)
                    if percent:
                        self.update_job(identifier, "downloading", "正在下载或合并", min(float(percent[1]), 99))
            await process.wait()
            error_data = await errors
            if file is None or file.parent != folder or not file.is_file():
                raise ValueError(command_error(error_data))
            return file
        finally:
            if process.returncode is None:
                await stop(process)
            await asyncio.gather(errors, return_exceptions=True)

    async def download(self, identifier):
        job = self.job(identifier)
        try:
            async with self.queue:
                self.update_job(identifier, "downloading", "正在下载视频")
                folder = (Path(job["directory"]) / identifier).resolve()
                file = await self.fetch_file(job, folder)
                asset = await self.add(str(file), title=job["title"], source="bilibili")
                self.update_job(identifier, "completed", "已加入素材库。", 100, asset["id"])
        except asyncio.CancelledError:
            self.update_job(identifier, "canceled", "下载已取消。")
            raise
        except (ValueError, OSError, TimeoutError) as exc:
            detail = str(exc) if str(exc) else "下载超时，请重试。"
            self.update_job(identifier, "failed", detail[:650])
        except Exception:
            self.update_job(identifier, "failed", "下载工具没有返回可用的素材，请重试。")

    async def extract_subtitle(self, asset, track_id, output):
        path = local_video(asset["path"])
        tracks = (await probe(path))["subtitles"]
        track = next((item for item in tracks if item["id"] == track_id and item["convertible"]), None)
        if not track:
            raise ValueError("这个文本字幕轨已不可用。")
        stream, key = track_id.split(":", 1)
        sidecar = path.parent / key if stream == "file" else path
        if output.resolve() == sidecar.resolve():
            raise ValueError("请选择不同的输出文件名，保留原始字幕。")
        temporary = output.with_name(f".relayfold-{new_id()}.srt")
        try:
            if sidecar.suffix.lower() == ".srt":
                await asyncio.to_thread(shutil.copyfile, sidecar, temporary)
            else:
                await run(tool("ffmpeg"), "-v", "error", "-protocol_whitelist", "file,pipe", "-i", str(sidecar),
                          "-map", f"0:{key}" if stream == "stream" else "0:s:0", "-c:s", "srt", str(temporary),
                          timeout=180)
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)

    async def close(self):
        jobs = list(self.jobs.values())
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)

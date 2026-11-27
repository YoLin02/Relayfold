"""Subtitle jobs and editable local subtitle projects for the material library."""

import asyncio
import hashlib
import json
import logging
import tempfile
from pathlib import Path

from caption_engine import LANGUAGES, Whisper, read_srt, render_srt, validate_cues
from materials import local_video, probe, srt_destination
from store import new_id

SUMMARY = "asset_id,status,progress,detail,source,revision,count"
ACTIVE = ("queued", "extracting", "setup", "audio", "recognizing")


class MaterialCaptions:
    def __init__(self, materials, root):
        self.materials = materials
        self.db = materials.db
        self.whisper = Whisper(root)
        self.queue = asyncio.Semaphore(1)
        self.jobs = {}
        self.imported = {}
        self.db.execute("""CREATE TABLE IF NOT EXISTS material_captions (
            asset_id TEXT PRIMARY KEY, status TEXT NOT NULL, progress INTEGER, detail TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '', track TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 0,
            count INTEGER NOT NULL DEFAULT 0, cues TEXT NOT NULL DEFAULT '[]'
        )""")
        with self.db:
            marks = ",".join("?" for _ in ACTIVE)
            self.db.execute(f"""UPDATE material_captions SET status='failed', progress=NULL,
                detail='上次字幕处理已中断，可以重新开始。' WHERE status IN ({marks})""", ACTIVE)

    def summaries(self):
        return {row["asset_id"]: dict(row) for row in self.db.execute(f"SELECT {SUMMARY} FROM material_captions")}

    def details(self, asset_id):
        self.materials.asset(asset_id)
        row = self.db.execute("SELECT revision,cues FROM material_captions WHERE asset_id=?", (asset_id,)).fetchone()
        return {"revision": row["revision"], "cues": json.loads(row["cues"])} if row else {"revision": 0, "cues": []}

    def report(self, asset_id, status, progress, detail):
        with self.db:
            self.db.execute("""INSERT INTO material_captions (asset_id,status,progress,detail) VALUES (?,?,?,?)
                ON CONFLICT(asset_id) DO UPDATE SET status=excluded.status,
                    progress=excluded.progress,detail=excluded.detail""", (asset_id, status, progress, detail))
        self.materials.changed()

    def persist(self, asset_id, cues, source, track):
        with self.db:
            self.db.execute("""UPDATE material_captions SET cues=?,count=?,revision=revision+1,source=?,track=?,
                status='ready',progress=NULL,detail='' WHERE asset_id=?""",
                (json.dumps(cues, ensure_ascii=False), len(cues), source, track, asset_id))
        self.materials.changed()

    def launch(self, asset_id, mode, track="", language="auto", *, replace=False):
        asset = self.materials.asset(asset_id)
        if not isinstance(mode, str) or mode not in {"auto", "extract", "speech"}:
            raise ValueError("请选择字幕处理方式。")
        if not isinstance(language, str) or language not in LANGUAGES:
            raise ValueError("请选择有效的语音语言。")
        if not asset["available"]:
            raise ValueError("素材文件已移动或删除。")
        if asset_id in self.jobs:
            raise ValueError("此素材的字幕正在处理。")
        if self.details(asset_id)["revision"] and replace is not True:
            raise ValueError("这条素材已有字幕，确认替换后再处理。")
        if mode == "extract" and not any(item["id"] == track and item["convertible"] for item in asset["subtitles"]):
            raise ValueError("请选择可提取的文本字幕轨。")
        self.report(asset_id, "queued", None, "等待处理字幕")
        job = asyncio.create_task(self.process(asset, mode, track, language))
        self.jobs[asset_id] = job
        job.add_done_callback(lambda _job: self.jobs.pop(asset_id, None))

    def extract_for_review(self, asset_id):
        asset = self.materials.asset(asset_id)
        if not asset["available"] or asset_id in self.jobs or self.details(asset_id)["revision"]:
            return
        # Probe lists embedded streams before sidecars, so the first text track is preferred.
        chosen = next((item for item in asset["subtitles"] if item["convertible"]), None)
        if chosen:
            self.launch(asset_id, "extract", chosen["id"])

    async def import_srt(self, value):
        path = Path(value) if isinstance(value, str) else Path()
        if not path.is_absolute() or path.suffix.lower() != ".srt" or not path.is_file():
            raise ValueError("请选择有效的本地 SRT 文件。")
        cues = await asyncio.to_thread(read_srt, path)
        identifier = hashlib.sha256(render_srt(cues).encode("utf-8")).hexdigest()
        self.imported.pop(identifier, None)
        self.imported[identifier] = cues
        if len(self.imported) > 24:
            self.imported.pop(next(iter(self.imported)))
        return {"id": identifier, "name": path.name, "cues": cues}

    def synthesis_source(self, source):
        if not isinstance(source, dict) or not isinstance(source.get("id"), str):
            raise ValueError("请选择用于合成的字幕。")
        identifier = source["id"]
        if source.get("kind") == "srt":
            cues = self.imported.get(identifier)
            if not cues:
                raise ValueError("请重新导入 SRT 文件。")
            return f"srt:{identifier}", 0, cues
        if source.get("kind") != "saved":
            raise ValueError("请选择有效的字幕来源。")
        document = self.details(identifier)
        if not document["cues"]:
            raise ValueError("所选来源没有已保存的字幕。")
        if type(source.get("revision")) is not int or source["revision"] != document["revision"]:
            raise ValueError("字幕有更新，请重新选择字幕来源。")
        if identifier in self.jobs:
            raise ValueError("请等字幕处理完成后再合成。")
        return f"saved:{identifier}:{document['revision']}", document["revision"], document["cues"]

    async def cancel(self, asset_id):
        job = self.jobs.get(asset_id)
        if job and not job.done():
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)
            self.report(asset_id, "canceled", None, "字幕处理已取消。")

    async def process(self, asset, mode, track, language):
        asset_id = asset["id"]
        def progress(status, percent, detail):
            self.report(asset_id, status, percent, detail)

        try:
            async with self.queue:
                path = local_video(asset["path"])
                details = await probe(path)
                chosen = track if mode == "extract" else next(
                    (item["id"] for item in details["subtitles"] if item["convertible"]), "")
                if mode != "speech" and chosen:
                    progress("extracting", None, "正在提取已有字幕")
                    try:
                        with tempfile.TemporaryDirectory(prefix="relayfold-caption-") as directory:
                            output = Path(directory) / "track.srt"
                            await self.materials.extract_subtitle(asset, chosen, output)
                            cues = await asyncio.to_thread(read_srt, output)
                    except (ValueError, OSError):
                        if mode == "extract":
                            raise
                    else:
                        self.persist(asset_id, cues, "extract", chosen)
                        return
                if not details["has_audio"]:
                    raise ValueError("视频没有音轨，无法生成语音字幕。")
                cues = await self.whisper.transcribe(path, language, progress)
                self.persist(asset_id, cues, "speech", "")
        except asyncio.CancelledError:
            progress("canceled", None, "字幕处理已取消。")
            raise
        except (ValueError, OSError) as exc:
            progress("failed", None, str(exc)[:450] or "字幕处理失败，请重试。")
        except Exception:
            logging.exception("Local subtitle processing failed")
            progress("failed", None, "字幕处理失败，请重试。")

    def save(self, asset_id, revision, cues):
        if asset_id in self.jobs:
            raise ValueError("字幕处理中，请完成后再保存。")
        row = self.db.execute("SELECT revision,source,track FROM material_captions WHERE asset_id=?", (asset_id,)).fetchone()
        if row is None or type(revision) is not int or row["revision"] != revision:
            raise ValueError("字幕已更新，请重新打开编辑器。")
        self.persist(asset_id, validate_cues(cues), row["source"], row["track"])
        return self.details(asset_id)

    async def export(self, asset_id, destination):
        asset = self.materials.asset(asset_id)
        output = srt_destination(destination)
        cues = self.details(asset_id)["cues"]
        if not cues:
            raise ValueError("这条素材没有可导出的字幕。")
        video = Path(asset["path"])
        if output.resolve().parent == video.resolve().parent:
            filename = output.resolve().stem.casefold()
            stem = video.stem.casefold()
            if (filename == stem or filename.startswith(stem + ".")) and output.exists():
                raise ValueError("请选择不同的文件名，保留原始字幕。")
        temporary = output.with_name(f".relayfold-{new_id()}.srt")
        try:
            await asyncio.to_thread(temporary.write_text, render_srt(cues), encoding="utf-8", newline="\n")
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)

    async def close(self):
        pending = list(self.jobs.values())
        for job in pending:
            job.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

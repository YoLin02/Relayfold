"""Render a saved subtitle revision into a new, publishable local video."""

import asyncio
import logging
import os
import tempfile
from collections import deque
from pathlib import Path

from caption_engine import render_srt
from materials import command_error, local_video, probe, start, stop, tool

STYLE = (
    "FontName=Microsoft YaHei,PrimaryColour=&H00FFFFFF,OutlineColour=&H00181818,"
    "BorderStyle=1,Shadow=0,Alignment=2,MarginV=16"
)


def subtitle_filter(info):
    width, height = info["width"] or 16, info["height"] or 9
    if info["rotation"] % 180:
        width, height = height, width
    size = max(8, round(22 * min(1, (width / height) / (16 / 9))))
    outline = max(1, round(size / 12, 1))
    style = f"{STYLE},FontSize={size},Outline={outline}"
    return f"subtitles=filename=captions.srt:force_style='{style}',pad=ceil(iw/2)*2:ceil(ih/2)*2"


class MaterialSynthesis:
    def __init__(self, materials, captions):
        self.materials = materials
        self.captions = captions
        self.db = materials.db
        self.jobs = {}
        self.queue = asyncio.Semaphore(1)
        with self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS material_renders (
                asset_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, destination TEXT NOT NULL,
                status TEXT NOT NULL, progress INTEGER, detail TEXT NOT NULL, output_id TEXT, source_key TEXT NOT NULL
            )""")
            columns = {row["name"] for row in self.db.execute("PRAGMA table_info(material_renders)")}
            if "source_key" not in columns:
                self.db.execute("ALTER TABLE material_renders ADD COLUMN source_key TEXT NOT NULL DEFAULT ''")
                self.db.execute("UPDATE material_renders SET source_key='saved:' || asset_id || ':' || revision")
            self.db.execute("""UPDATE material_renders SET status='failed', progress=NULL,
                detail='上次合成已中断，可以重新合成。' WHERE status IN ('queued','rendering')""")

    def summaries(self):
        return {row["asset_id"]: dict(row) for row in self.db.execute("SELECT * FROM material_renders")}

    def begin(self, asset_id, subtitle_source, destination):
        asset = self.materials.asset(asset_id)
        source = local_video(asset["path"])
        source_key, revision, cues = self.captions.synthesis_source(subtitle_source)
        if asset_id in self.jobs:
            raise ValueError("这条视频正在合成。")
        output = Path(destination) if isinstance(destination, str) else Path()
        if not output.is_absolute() or output.suffix.lower() != ".mp4" or not output.parent.is_dir():
            raise ValueError("请选择有效的 MP4 保存路径。")
        output = output.resolve()
        if output == source or output.exists():
            raise ValueError("请选择一个新的文件名，保留已有视频。")
        if self.db.execute("SELECT 1 FROM material_assets WHERE path=?", (str(output),)).fetchone():
            raise ValueError("素材库已记录这个路径，请使用新的文件名。")
        if self.db.execute("""SELECT 1 FROM material_renders WHERE destination=?
                              AND status IN ('queued','rendering')""", (str(output),)).fetchone():
            raise ValueError("已有合成任务使用此文件名。")
        with self.db:
            self.db.execute("""INSERT OR REPLACE INTO material_renders
                (asset_id,revision,destination,status,progress,detail,source_key) VALUES (?,?,?,'queued',NULL,?,?)""",
                (asset_id, revision, str(output), "等待合成", source_key))
        task = asyncio.create_task(self.render(asset, source, output, cues))
        self.jobs[asset_id] = task
        task.add_done_callback(lambda _task: self.jobs.pop(asset_id, None))
        self.materials.changed()

    def update(self, asset_id, status, detail, progress=None):
        with self.db:
            self.db.execute("UPDATE material_renders SET status=?,progress=?,detail=? WHERE asset_id=?",
                            (status, progress, detail, asset_id))
        self.materials.changed()

    async def cancel(self, asset_id):
        task = self.jobs.get(asset_id)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            row = self.db.execute("SELECT status FROM material_renders WHERE asset_id=?", (asset_id,)).fetchone()
            if row["status"] in {"queued", "rendering"}:
                self.update(asset_id, "canceled", "已取消合成。")

    async def render(self, asset, source, output, cues):
        asset_id = asset["id"]
        try:
            async with self.queue:
                current = await probe(local_video(str(source)))
                duration = current["duration"]
                if duration and not any(cue["startMs"] < duration * 1000 for cue in cues):
                    raise ValueError("字幕时间都超出视频长度，请校对时间轴。")
                self.update(asset_id, "rendering", "正在合成字幕", 0 if duration else None)
                with tempfile.TemporaryDirectory(prefix=".relayfold-render-", dir=output.parent) as directory:
                    scratch = Path(directory)
                    (scratch / "captions.srt").write_text(render_srt(cues), encoding="utf-8", newline="\n")
                    await self.encode(asset_id, source, scratch, current)
                    encoded = scratch / "video.mp4"
                    metadata = await probe(encoded)
                    if current["has_audio"] and not metadata["has_audio"]:
                        raise ValueError("合成文件缺少原视频的音轨。")
                    # Create the new file without replacing a destination that appeared during the encode.
                    if os.name == "nt":
                        encoded.rename(output)
                    else:
                        os.link(encoded, output)
                with self.db:
                    result = self.materials.register(output, metadata, output.stem, "captioned")
                    self.db.execute("""UPDATE material_renders SET status='ready',progress=100,detail='',
                        output_id=? WHERE asset_id=?""", (result["id"], asset_id))
                self.materials.changed()
        except asyncio.CancelledError:
            self.update(asset_id, "canceled", "已取消合成。")
            raise
        except FileExistsError:
            self.update(asset_id, "failed", "目标文件已存在，请选择新的文件名。")
        except (OSError, ValueError) as exc:
            self.update(asset_id, "failed", str(exc)[:450] or "视频合成失败。")
        except Exception:
            logging.exception("Local subtitle synthesis failed")
            self.update(asset_id, "failed", "视频合成失败，请重新选择保存位置。")

    async def encode(self, asset_id, source, scratch, info):
        duration = info["duration"]
        process = await start(tool("ffmpeg"), "-hide_banner", "-v", "error", "-nostats",
                              "-progress", "pipe:1", "-stats_period", "0.5", "-protocol_whitelist", "file,pipe",
                              "-i", str(source), "-map", "0:V:0", "-map", "0:a?", "-vf", subtitle_filter(info),
                              "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                              "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "video.mp4", cwd=scratch)
        errors = deque(maxlen=16)

        async def read_errors():
            while line := await process.stderr.readline():
                errors.append(line)

        stderr = asyncio.create_task(read_errors())
        try:
            previous = 0
            while line := await asyncio.wait_for(process.stdout.readline(), timeout=180):
                key, _, value = line.strip().partition(b"=")
                if key == b"out_time_us" and value.isdigit() and duration:
                    percent = min(99, int(100 * int(value) / (duration * 1_000_000)))
                    if percent > previous:
                        self.update(asset_id, "rendering", "正在合成字幕", percent)
                        previous = percent
            await process.wait()
            await stderr
            if process.returncode:
                messages = b"".join(errors)
                if b"No such filter" in messages or b"Unknown encoder" in messages:
                    raise ValueError("当前 FFmpeg 缺少字幕渲染或 H.264 编码组件，请使用完整版本。")
                raise ValueError(command_error(messages))
        except TimeoutError as exc:
            raise ValueError("视频合成长时间没有进度，请检查素材和保存目录后重试。") from exc
        finally:
            if process.returncode is None:
                await stop(process)
            await asyncio.gather(stderr, return_exceptions=True)

    async def close(self):
        await asyncio.gather(*(self.cancel(asset_id) for asset_id in tuple(self.jobs)))

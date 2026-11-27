"""Local Word script import and timeline-aware comparison."""

import asyncio
import hashlib
import json
import unicodedata
from bisect import bisect_right
from difflib import SequenceMatcher
from pathlib import Path
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

WORD_NAMESPACES = (
    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}",
    "{http://purl.oclc.org/ooxml/wordprocessingml/main}",
)
MAX_XML = 8 * 1024 * 1024
MAX_TEXT = 30_000
MAX_DIFFERENCES = 1200
CONTEXT = 12


def word_text(value):
    path = Path(value) if isinstance(value, str) else Path()
    if not path.is_absolute() or path.suffix.lower() != ".docx" or not path.is_file():
        raise ValueError("请选择本地 Word .docx 文件。")
    try:
        with ZipFile(path) as package:
            with package.open("word/document.xml") as body_xml:
                data = body_xml.read(MAX_XML + 1)
        if len(data) > MAX_XML:
            raise ValueError("Word 正文过大，请拆成多份后导入。")
        xml = data.replace(b"\x00", b"")
        if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
            raise ValueError("Word 正文含有不受支持的 XML 声明。")
        root = ElementTree.fromstring(data)
    except (KeyError, BadZipFile, ElementTree.ParseError, OSError, RuntimeError) as exc:
        raise ValueError("无法读取此 Word 文件，请确认它是未加密的 .docx。") from exc
    namespace = next((value for value in WORD_NAMESPACES if root.tag == value + "document"), "")
    body = root.find(namespace + "body") if namespace else None
    if body is None:
        raise ValueError("没有找到 Word 正文。")

    parts = []
    # Walk the main document in order, including paragraphs inside tables.
    def visit(node):
        name = node.tag.removeprefix(namespace)
        if name in {"del", "moveFrom", "pPr", "rPr"}:
            return
        if name == "t":
            parts.append(node.text or "")
        elif name in {"tab", "br", "cr"}:
            parts.append(" " if name == "tab" else "\n")
        else:
            for child in node:
                visit(child)
            if name == "p":
                parts.append("\n")

    try:
        visit(body)
    except RecursionError as exc:
        raise ValueError("Word 文档结构过深，无法读取正文。") from exc
    script = "\n".join(line.strip() for line in "".join(parts).splitlines() if line.strip())
    if len(script) > MAX_TEXT:
        raise ValueError("Word 正文最多支持 3 万字符，请分段导入。")
    if not canonical(script)[0]:
        raise ValueError("Word 正文没有可核对的文字。")
    return path.name, script


def canonical(text):
    tokens, offsets = [], []
    for index, original in enumerate(text):
        current = unicodedata.normalize("NFKC", original).casefold()
        previous = index > 0 and text[index - 1].isdigit()
        following = index + 1 < len(text) and text[index + 1].isdigit()
        for component in current:
            category = unicodedata.category(component)[0]
            numeric_mark = (
                (component in "./:" and previous and following)
                or (component in "-−" and following)
                or (component == "%" and previous)
            )
            if category in {"L", "M", "N", "S"} or numeric_mark:
                tokens.append(component)
                offsets.append(index)
    return "".join(tokens), offsets


def excerpt(text, offsets, start, end):
    if start == end:
        return None
    left = offsets[start]
    right = offsets[end - 1] + 1
    before = text[offsets[max(0, start - CONTEXT)]:left]
    after = text[right:offsets[min(len(offsets), end + CONTEXT) - 1] + 1]
    # Show bounded excerpts even when an entire paragraph was absent.
    change = text[left:right]
    return {"before": before[-36:], "text": change[:420], "after": (after[:36] if len(change) <= 420 else "…")}


def compare_script(script, cues):
    transcript_parts, cue_offsets = [], []
    offset = 0
    for cue in cues:
        cue_offsets.append(offset)
        transcript_parts.append(cue["text"])
        offset += len(cue["text"]) + 1
    transcript = "\n".join(transcript_parts)
    if len(transcript) > MAX_TEXT:
        raise ValueError("字幕正文超过 3 万字符，请按片段核对。")
    expected, expected_offsets = canonical(script)
    spoken, spoken_offsets = canonical(transcript)
    matcher = SequenceMatcher(None, expected, spoken, autojunk=max(len(expected), len(spoken)) > 4000)
    kinds = {"replace": "changed", "delete": "script-only", "insert": "transcript-only"}
    differences = []
    total = 0
    counts = dict.fromkeys(kinds.values(), 0)
    for tag, script_begin, script_end, spoken_begin, spoken_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        kind = kinds[tag]
        counts[kind] += 1
        total += 1
        if total > MAX_DIFFERENCES:
            continue
        anchor = spoken_offsets[spoken_begin] if spoken_begin < len(spoken_offsets) else len(transcript)
        end_anchor = spoken_offsets[spoken_end - 1] if spoken_end > spoken_begin else anchor
        first = max(0, bisect_right(cue_offsets, anchor) - 1)
        last = max(first, bisect_right(cue_offsets, end_anchor) - 1)
        cue = cues[first] if cues else None
        start_ms = cue["startMs"] if cue else None
        end_ms = cues[last]["endMs"] if cue else None
        cue_position = anchor - cue_offsets[first] if cue else 0
        key = json.dumps([
            kind, script_begin, script_end, spoken[spoken_begin:spoken_end], start_ms, end_ms, cue_position,
        ], ensure_ascii=False)
        differences.append({
            "id": hashlib.sha256(key.encode("utf-8")).hexdigest()[:32], "kind": kind,
            "script": excerpt(script, expected_offsets, script_begin, script_end),
            "transcript": excerpt(transcript, spoken_offsets, spoken_begin, spoken_end),
            "startMs": start_ms, "endMs": end_ms, "cueIndex": first if cue else None,
            "nearby": kind == "script-only",
        })
    return {"differences": differences, "counts": counts, "total": total}


class ScriptReview:
    def __init__(self, materials, captions):
        self.materials = materials
        self.captions = captions
        self.db = materials.db
        self.cache = {}
        with self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS material_scripts (
                asset_id TEXT PRIMARY KEY, script_id TEXT NOT NULL, name TEXT NOT NULL,
                body TEXT NOT NULL, marked TEXT NOT NULL DEFAULT '[]'
            )""")

    def row(self, asset_id):
        return self.db.execute("SELECT * FROM material_scripts WHERE asset_id=?", (asset_id,)).fetchone()

    async def import_word(self, asset_id, path):
        self.materials.asset(asset_id)
        name, body = await asyncio.to_thread(word_text, path)
        script_id = hashlib.sha256(body.encode("utf-8")).hexdigest()
        with self.db:
            self.db.execute("""INSERT INTO material_scripts (asset_id,script_id,name,body) VALUES (?,?,?,?)
                ON CONFLICT(asset_id) DO UPDATE SET name=excluded.name,body=excluded.body,
                    marked=CASE WHEN script_id=excluded.script_id THEN marked ELSE '[]' END,
                    script_id=excluded.script_id""", (asset_id, script_id, name, body))
        self.captions.extract_for_review(asset_id)
        return await self.review(asset_id)

    async def review(self, asset_id):
        self.materials.asset(asset_id)
        script = self.row(asset_id)
        if script is None:
            return None
        document = self.captions.details(asset_id)
        result = None
        error = ""
        if document["cues"]:
            key = (asset_id, script["script_id"], document["revision"])
            result = self.cache.get(key)
            if result is None:
                try:
                    result = await asyncio.to_thread(compare_script, script["body"], document["cues"])
                except ValueError as exc:
                    error = str(exc)
                else:
                    self.cache[key] = result
                    if len(self.cache) > 8:
                        self.cache.pop(next(iter(self.cache)))
        marks = self.row(asset_id)
        return {"id": script["script_id"], "name": script["name"], "revision": document["revision"],
                "marked": json.loads(marks["marked"]) if marks["script_id"] == script["script_id"] else [],
                "result": result, "error": error}

    async def mark(self, asset_id, script_id, revision, diff_id, reviewed):
        if not isinstance(reviewed, bool):
            raise ValueError("核对状态无效。")
        review = await self.review(asset_id)
        script = self.row(asset_id)
        if (not script or not review or script["script_id"] != script_id or review["id"] != script_id
                or self.captions.details(asset_id)["revision"] != revision or review["revision"] != revision):
            raise ValueError("脚本或字幕已更新，请刷新核对结果。")
        valid = {item["id"] for item in review["result"]["differences"]} if review["result"] else set()
        if not isinstance(diff_id, str) or diff_id not in valid:
            raise ValueError("找不到这条差异。")
        marked = set(json.loads(script["marked"])) & valid
        if reviewed:
            marked.add(diff_id)
        else:
            marked.discard(diff_id)
        saved = sorted(marked)
        with self.db:
            self.db.execute("UPDATE material_scripts SET marked=? WHERE asset_id=?", (json.dumps(saved), asset_id))
        return saved

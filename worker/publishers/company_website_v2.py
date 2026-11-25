"""企业官网文章 API 和内容转换。

"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Optional
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger("video_publisher")

_IMG_MARK_RE = re.compile(r"!\[[^\]]*\]\([^\)]*\)")
_IMG_MARK_CAPTURE_RE = re.compile(r"!\[([^\]]*)\]\(([^\)]*)\)")


def _get(account, name):
    return getattr(account, name, None)


def new_block_id() -> str:
    return uuid.uuid4().hex[:12]


async def _login(account) -> str:
    """POST {account.api_base}/auth/login 拿 accessToken；失败 raise。"""
    username = _get(account, "api_username")
    password = _get(account, "api_password")
    if not username or not password:
        raise RuntimeError("官网2.0 账号未配置 api_username/api_password")

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(f"{account.api_base}/auth/login", json={"username": username, "password": password})
        if resp.status_code == 429:
            raise RuntimeError("官网2.0 登录限流(429): 每分钟最多 10 次，请稍后再试")
        if resp.status_code >= 400:
            raise RuntimeError(f"官网2.0 登录失败 (HTTP {resp.status_code}): {resp.text[:200]}")
        data = resp.json()

    token = data.get("accessToken")
    if not token:
        raise RuntimeError("官网2.0 登录响应缺少 accessToken")
    return token


def domain_key(domain: Optional[str]) -> Optional[str]:
    if not domain:
        return None
    value = str(domain).strip().lower()
    host = urlsplit(value if "://" in value else f"https://{value}").hostname
    return host.removeprefix("www.") if host else None


def _as_list(payload) -> list:
    """兼容顶层数组与 `{data: [...]}` 包装。"""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return data
    return []


async def _get_sites(account, token: str) -> list:
    """GET /sites，返回当前账号名下站点列表。401 抛 RuntimeError（令牌过期，由调用方重登）。"""
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(f"{account.api_base}/sites", headers=headers)
        if resp.status_code == 401:
            raise RuntimeError("官网2.0 令牌过期(401)，需重新登录")
        if resp.status_code >= 400:
            raise RuntimeError(f"官网2.0 获取站点失败 (HTTP {resp.status_code}): {resp.text[:300]}")
        return _as_list(resp.json())


async def resolve_site_id(account, token: str) -> Optional[str]:
    """由账号 website_url(域名) 反查 siteId（GET /sites）。找不到返回 None；401 抛 RuntimeError。"""
    key = domain_key(_get(account, "website_url"))
    site_filter = _get(account, "cms_site_id") or ""
    for site in await _get_sites(account, token):
        site_id = str(site.get("id") or "")
        domains = {domain_key(site.get(field)) for field in ("customDomain", "domain", "websiteUrl")}
        if site_id and ((site_filter and site_id == site_filter) or (not site_filter and key and key in domains)):
            return site_id
    return None






async def _create_article(account, token: str, payload: dict) -> tuple[bool, dict]:
    """POST /sites/{siteId}/articles，返回 (成功, 响应)。401 不在此重发，由调用方处理。"""
    site_id = _get(account, "site_id")
    url = f"{account.api_base}/sites/{site_id}/articles"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code == 201:
            return True, resp.json()
        return False, {"status_code": resp.status_code, "body": resp.text[:500]}


def _slugify(title: str) -> str:
    """标题 → URL slug：小写、仅 [a-z0-9] 与 '-'；中文转拼音。无 pypinyin 时回退纯 ascii。"""
    text = (title or "").strip()
    if not text:
        return f"article-{uuid.uuid4().hex[:8]}"
    try:
        from pypinyin import lazy_pinyin
        text = "-".join(lazy_pinyin(text))
    except Exception:
        pass
    text = re.sub(r"[^a-z0-9]+", "-", text.lower())
    text = re.sub(r"-+", "-", text).strip("-")
    return text or f"article-{uuid.uuid4().hex[:8]}"


def _is_image_line(stripped: str) -> bool:
    leftover = _IMG_MARK_RE.sub("", stripped)
    return bool(stripped) and not leftover.strip()


_HEADING_RE = re.compile(r"^#{1,6}\s+")


def _description_to_content_by_blankline(lines: list[str]):
    """无章节标题时的回退：按空行分段（兼容旧内容）。"""
    blocks: list[dict] = []
    cover_url: Optional[str] = None
    text_buf: list[str] = []
    img_buf: list[tuple[str, str]] = []

    def flush_text():
        nonlocal text_buf
        text_lines = [re.sub(r"^#{1,6}\s+", "", t) for t in text_buf]
        text = "\n".join(t for t in text_lines if t.strip()).strip()
        if text:
            blocks.append({"id": new_block_id(), "type": "paragraph", "text": text})
        text_buf = []

    def flush_img():
        nonlocal img_buf
        if img_buf:
            if len(img_buf) == 1:
                url, alt = img_buf[0]
                blk = {"id": new_block_id(), "type": "image", "url": url}
                if alt:
                    blk["alt"] = alt
                blocks.append(blk)
            else:
                blocks.append({
                    "id": new_block_id(),
                    "type": "gallery",
                    "urls": [u for u, _ in img_buf],
                    "layout": "grid",
                })
            img_buf = []

    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            # 空行 = 段落分隔：把累积文本成独立一段
            flush_text()
            continue
        if _is_image_line(stripped):
            flush_text()
            for alt, url in _IMG_MARK_CAPTURE_RE.findall(stripped):
                url = url.strip()
                if not url:
                    continue
                if cover_url is None:
                    cover_url = url
                img_buf.append((url, alt.strip()))
        else:
            flush_img()
            text_buf.append(raw)

    flush_text()
    flush_img()
    return blocks, cover_url


def _description_to_content(description: Optional[str]):
    """markdown description → (content_blocks, cover_url)。

    优先按章节标题（`## 一、`）分段：每个 `##` 章节合成一个 paragraph 块
    （段内保留换行、剥每行 # 前缀），该章内图片独立成 image/gallery 块置于章段之后。
    全文无 `##` 标题时（旧内容）回退为按空行分段。
    """
    lines = (description or "").splitlines()
    if not any(_HEADING_RE.match(line.strip()) for line in lines if line.strip()):
        return _description_to_content_by_blankline(lines)

    blocks: list[dict] = []
    cover_url: Optional[str] = None
    text_buf: list[str] = []                # 当前章节文本行
    img_buf: list[tuple[str, str]] = []     # 当前章节图片 (url, alt)

    def flush_text():
        nonlocal text_buf
        text_lines = [re.sub(r"^#{1,6}\s+", "", t) for t in text_buf]
        text = "\n".join(t for t in text_lines if t.strip()).strip()
        if text:
            blocks.append({"id": new_block_id(), "type": "paragraph", "text": text})
        text_buf = []

    def flush_img():
        nonlocal img_buf
        if img_buf:
            if len(img_buf) == 1:
                url, alt = img_buf[0]
                blk = {"id": new_block_id(), "type": "image", "url": url}
                if alt:
                    blk["alt"] = alt
                blocks.append(blk)
            else:
                blocks.append({
                    "id": new_block_id(),
                    "type": "gallery",
                    "urls": [u for u, _ in img_buf],
                    "layout": "grid",
                })
            img_buf = []

    def flush_section():
        # 章节结束：先输出该章文本段，再输出该章收集的图片块
        flush_text()
        flush_img()

    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            # 空行：保留为章节内换行，不触发分段（整章一段）
            if text_buf:
                text_buf.append("")
            continue
        if _HEADING_RE.match(stripped):
            flush_section()            # 结束上一章节
            text_buf.append(raw)       # 开启新章节（剥 # 在 flush 时做）
            continue
        if _is_image_line(stripped):
            for alt, url in _IMG_MARK_CAPTURE_RE.findall(stripped):
                url = url.strip()
                if not url:
                    continue
                if cover_url is None:
                    cover_url = url
                img_buf.append((url, alt.strip()))
            continue
        # 普通文本行
        text_buf.append(raw)

    flush_section()
    return blocks, cover_url


def _build_payload(account, title: str, slug: str, blocks: list[dict], cover_url: Optional[str], category_id: Optional[str] = None) -> dict:
    payload = {
        "title": (title or "").strip()[:200],
        "slug": slug,
        "status": "published",
        "content": blocks,
    }
    if cover_url:
        payload["coverUrl"] = cover_url
    # categoryId 由分类名称运行时解析（账号未配置则省略）
    if category_id:
        payload["categoryId"] = category_id
    return payload

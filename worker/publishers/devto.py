"""Dev.to 纯 HTTP 发布器（官方 REST API）。

凭据：账号表 `api_password` 存 Dev.to 的 API Key
（https://dev.to/settings/extensions → DEV Community API Keys，免费）。

Dev.to 原生接受 Markdown，正文直接把 GEO 文章内容提交，不做格式转换；
文中图片用远程 URL 即可，Dev.to 会自行转存到它的 CDN。
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import httpx

logger = logging.getLogger("video_publisher")

API_BASE = "https://dev.to/api"
TIMEOUT = 60


def _get(account, name):
    return getattr(account, name, None)


def _strip_leading_title(text: str, title: Optional[str]) -> str:
    """去掉正文开头的重复标题

    GEO 文章正文偶尔会把标题作为 `# xxx` 起头，标题字段再填一次就会出现
    「标题重复两遍」。只有当第一行去掉 # 后与标题完全相同时才删。
    """
    if not text or not title:
        return text or ""
    lines = text.lstrip("\n").splitlines()
    if not lines:
        return text
    first = re.sub(r"^#{1,6}\s+", "", lines[0].strip())
    if first.strip().lower() == title.strip().lower():
        return "\n".join(lines[1:]).lstrip("\n")
    return text


async def publish(
    page,
    account,
    media_paths: list[str],
    title: Optional[str],
    description: Optional[str],
    *,
    before_submit,
) -> str | None:
    """Dev.to 文章发布（纯 HTTP，忽略 page）。

    失败一律抛异常：本地执行器会把异常文案写进发布记录，
    返回 False 只会得到笼统的「Publish returned False」，用户看不出原因。
    """
    key = (_get(account, "api_password") or "").strip()
    if not key:
        raise RuntimeError("Dev.to 账号未配置 API Key")
    if not (title or "").strip():
        raise RuntimeError("Dev.to 发布失败：文章标题为空")
    if not (description or "").strip():
        raise RuntimeError("Dev.to 发布失败：文章内容为空")

    payload = {
        "article": {
            "title": title.strip()[:128],
            "body_markdown": _strip_leading_title(description, title),
            "published": True,
        }
    }
    headers = {"api-key": key, "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            await before_submit()
            resp = await client.post(f"{API_BASE}/articles", json=payload, headers=headers)
    except httpx.HTTPError as e:
        raise RuntimeError(f"Dev.to 请求失败：{e}")

    if resp.status_code in (200, 201):
        try:
            data = resp.json()
        except Exception:
            data = {}
        logger.info(
            f"Dev.to 发布成功 account_id={_get(account, 'id')} url={data.get('url')}"
        )
        return str(data["id"]) if data.get("id") else None

    if resp.status_code == 401:
        raise RuntimeError("Dev.to API Key 无效或已过期，请重新生成")
    if resp.status_code == 429:
        raise RuntimeError("Dev.to 触发限流（429），请稍后再试")
    raise RuntimeError(f"Dev.to 发布失败 (HTTP {resp.status_code}): {resp.text[:300]}")

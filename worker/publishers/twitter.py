"""Twitter / X 视频推文发布 —— Playwright 浏览器自动化。

发布走 `x.com/compose/post` 弹窗：先挂视频文件，等上传进度条跑完，
再写正文，最后点 Post。X 的正文上限是 280 个字符（带不带媒体都一样）。
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from playwright.async_api import Page

from ._text import plain_text

logger = logging.getLogger("video_publisher")

COMPOSE_URL = "https://x.com/compose/post"

# 280 上限是「字符数」而不是字节数，留几个位置给末尾的省略号
MAX_TEXT_LEN = 275

_TEXT_TOO_LONG_HINTS = ("exceeded", "too long", "超出", "最长")


async def publish(
    page: Page,
    account,
    media_paths: list[str],
    title: Optional[str] = None,
    description: Optional[str] = None,
    *,
    before_submit,
) -> bool:
    logger.info(f"Twitter: 开始发布 {account.name}，media={media_paths}")

    if not media_paths:
        raise RuntimeError("Twitter 发布需要视频文件")
    video = media_paths[0]
    if not os.path.exists(video):
        raise RuntimeError(f"视频文件不存在：{os.path.basename(video)}")

    await page.goto(COMPOSE_URL, wait_until="domcontentloaded", timeout=90000)
    await asyncio.sleep(4)

    current = page.url.lower()
    if "/i/flow/login" in current or "/login" in current:
        raise RuntimeError("Twitter 登录已失效，请重新登录账号")

    # ① 挂视频文件
    try:
        file_input = await page.wait_for_selector(
            'input[data-testid="fileInput"]', state="attached", timeout=20000
        )
        await file_input.set_input_files(video)
        logger.info("Twitter: 视频已选择，等待上传")
    except Exception as e:
        raise RuntimeError(f"Twitter 未找到上传入口：{e}")

    # ② 等上传完成：上传中会出现进度条，媒体缩略图出现且进度条消失才算好
    if not await _wait_upload_done(page):
        raise RuntimeError("Twitter 视频上传超时（10 分钟）")

    # ③ 写正文
    text = plain_text(title, description)
    if len(text) > MAX_TEXT_LEN:
        logger.info(f"Twitter: 正文 {len(text)} 字符，截断到 {MAX_TEXT_LEN}")
        text = text[:MAX_TEXT_LEN - 1] + "…"
    if text:
        editor = await page.wait_for_selector('div[data-testid="tweetTextarea_0"]', timeout=15000)
        await editor.click()
        await asyncio.sleep(0.4)
        await page.keyboard.press("Control+a")
        await page.keyboard.press("Delete")
        await asyncio.sleep(0.3)
        await page.evaluate("t => navigator.clipboard.writeText(t)", text)
        await asyncio.sleep(0.3)
        await page.keyboard.press("Control+v")
        await asyncio.sleep(1.5)

    # ④ 点发布
    try:
        btn = await page.wait_for_selector(
            'button[data-testid="tweetButton"], button[data-testid="tweetButtonInline"]',
            timeout=20000,
        )
    except Exception:
        raise RuntimeError("Twitter 未找到 Post 按钮")

    if (await btn.get_attribute("aria-disabled")) == "true":
        # 上传没完成或正文超限时按钮是灰的，等一会儿再看；仍然灰的就判失败，
        # 别在这里让浏览器空等到任务超时
        for _ in range(12):
            await asyncio.sleep(10)
            if (await btn.get_attribute("aria-disabled")) != "true":
                break
        else:
            hint = await _toast_text(page)
            raise RuntimeError(f"Twitter Post 按钮一直不可用{('：' + hint) if hint else ''}")

    await before_submit()
    await btn.click()
    logger.info("Twitter: 已点击 Post")

    # ⑤ 等弹窗关闭 / 成功提示
    for _ in range(12):
        await asyncio.sleep(5)
        try:
            if not await page.query_selector('div[data-testid="tweetTextarea_0"]'):
                logger.info(f"Twitter: 发布完成 {account.name}")
                return True
        except Exception:
            return True
        hint = await _toast_text(page)
        if hint and any(k in hint.lower() for k in _TEXT_TOO_LONG_HINTS):
            raise RuntimeError(f"Twitter 发布被拒：{hint}")

    raise RuntimeError("Twitter 点击 Post 后没有完成（弹窗未关闭）")


async def _wait_upload_done(page: Page) -> bool:
    """上传中的进度条消失 + 媒体预览出现 = 上传完成。最多等 10 分钟。"""
    for _ in range(60):
        await asyncio.sleep(10)
        try:
            progress = await page.query_selector('div[role="progressbar"]')
            preview = await page.query_selector(
                'div[data-testid="attachments"] video, div[data-testid="attachments"] img'
            )
            if preview and not progress:
                await asyncio.sleep(3)
                return True
        except Exception:
            return False
    return False


async def _toast_text(page: Page) -> str:
    """读一下页面上的提示条，失败原因就写在这里。"""
    try:
        toast = await page.query_selector('div[data-testid="toast"], div[role="alert"]')
        if toast:
            return (await toast.inner_text()).strip()[:200]
    except Exception:
        pass
    return ""

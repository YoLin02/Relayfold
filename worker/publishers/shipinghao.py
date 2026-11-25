from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

from playwright.async_api import Frame, Page

logger = logging.getLogger("video_publisher")

PUBLISH_URL = "https://channels.weixin.qq.com/platform/post/create"

SELECTORS = {
    "upload_area": ".upload-wrap",
    "file_input": 'input[type="file"]',
    "desc_input": 'div.input-editor[data-placeholder="添加描述"]',
    # 新旧文案并列：视频号已把短标题框的 placeholder 从「概括视频主要内容」改成
    # 「填写短标题有机会获得更多流量」，只留旧选择器会 0 命中（实测）。
    "title_input": 'input[placeholder*="填写短标题"], input[placeholder*="概括视频主要内容"]',
    "publish_button": "button:not([disabled])",
}

# 文本为「直接发表」的按钮 class 是 weui-desktop-btn_default，而 :has-text() 是子串匹配 ——
# 原写法 button:not([disabled]):has-text("发表") 两个都能命中，靠 DOM 顺序侥幸选中「发表」。
# 限定 primary class 后只剩真正的「发表」按钮（class 值取自实测）。
PUBLISH_BTN_SELECTOR = 'button.weui-desktop-btn_primary:not([disabled]):has-text("发表")'


async def _safe_goto(page: Page, url: str, description: str = "") -> None:
    """安全导航到指定 URL，三层降级：domcontentloaded → load → commit"""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        logger.info(f"Shipinghao: {description} goto domcontentloaded ok, url={page.url}")
    except Exception as e:
        logger.warning(f"Shipinghao: {description} goto domcontentloaded failed: {e}")
        try:
            await page.goto(url, wait_until="load", timeout=30000)
            logger.info(f"Shipinghao: {description} goto load ok, url={page.url}")
        except Exception as e2:
            logger.warning(f"Shipinghao: {description} goto load also failed: {e2}")
            try:
                await page.goto(url, wait_until="commit", timeout=30000)
                await asyncio.sleep(5)
                logger.info(f"Shipinghao: {description} goto commit ok, url={page.url}")
            except Exception as e3:
                logger.error(f"Shipinghao: {description} goto completely failed: {e3}")


async def _safe_reload(page: Page, description: str = "") -> None:
    """安全刷新页面，三层降级：domcontentloaded → load → commit"""
    try:
        await page.reload(wait_until="domcontentloaded", timeout=60000)
        logger.info(f"Shipinghao: {description} reload domcontentloaded ok, url={page.url}")
    except Exception as e:
        logger.warning(f"Shipinghao: {description} reload domcontentloaded failed: {e}")
        try:
            await page.reload(wait_until="load", timeout=30000)
            logger.info(f"Shipinghao: {description} reload load ok, url={page.url}")
        except Exception as e2:
            logger.warning(f"Shipinghao: {description} reload load also failed: {e2}")
            try:
                await page.reload(wait_until="commit", timeout=30000)
                await asyncio.sleep(5)
                logger.info(f"Shipinghao: {description} reload commit ok, url={page.url}")
            except Exception as e3:
                logger.error(f"Shipinghao: {description} reload completely failed: {e3}")


async def _resolve_frame(
    page: Page, description: str = "", timeout_sec: int = 30
) -> Optional[Frame]:
    """找到真正承载发布表单的 frame。

    视频号的发布页是「外壳 + iframe」两层：主帧 /platform/post/create 只有顶部导航，
    真正的表单在 /micro/content/post/create 这个 iframe 里 —— 在主帧上任何选择器都等不到控件。
    形状与 xiaohongshu.py 里的同名函数一致。

    **必须轮询，不能扫一次就回落主帧**（实测）：iframe 的 DOM 是异步挂载的，goto 完
    domcontentloaded 再等 3 秒时，两个 frame 的选择器全是 0 命中，要更久才齐。扫一次就
    回落主帧，会在主帧上撞到一个还没挂稳的 input[type=file]（shell 的加载态），
    紧接着 set_input_files 报 "detached element" —— 一个没有任何指向性的报错。
    """
    frames = page.frames
    logger.info(f"Shipinghao: {description} total frames: {len(frames)}")
    for idx, f in enumerate(frames):
        logger.info(f"Shipinghao: {description} frame[{idx}]: url={f.url[:80] if f.url else 'about:blank'}")

    for attempt in range(timeout_sec):
        # 每轮重读 page.frames：路由切换时 iframe 会被整个换掉
        for f in reversed(page.frames):
            for sel in (SELECTORS["file_input"], SELECTORS["upload_area"], SELECTORS["desc_input"]):
                try:
                    if await f.locator(sel).count() > 0:
                        logger.info(
                            f"Shipinghao: {description} 命中发布表单 frame（第 {attempt + 1}s）: {f.url[:80]}"
                        )
                        return f
                except Exception:
                    pass
        await asyncio.sleep(1)

    logger.error(
        f"Shipinghao: {description} 等了 {timeout_sec}s 仍没找到发布控件，"
        f"frames={[f.url[:60] for f in page.frames]}"
    )
    return None


async def _upload_video(frame: Frame, media_path: str) -> bool:
    """上传视频。Playwright 原生 set_input_files 优先，pyautogui 仅作兜底。

    页面里的 <input type="file"> 是 AntD 的隐藏输入（display:none，但仍在 DOM 里），
    Playwright 可以直接给这个元素塞文件、不弹系统文件对话框 —— 不抢用户桌面、
    也不需要窗口在前台。

    用 locator 而不是先 query 出 element handle：locator 在调用那一刻才解析元素，
    并且自带重试，能躲开「拿到句柄之后 React 又把它重渲染掉」的 detached element
    （实测踩过）。set_input_files 的动作性检查只要求 attached，display:none 不受影响。
    """
    try:
        await frame.locator(SELECTORS["file_input"]).set_input_files(
            media_path, timeout=30000
        )
        logger.info(f"Shipinghao: 视频已通过原生 set_input_files 提交: {media_path}")
        return True
    except Exception as e:
        logger.warning(f"Shipinghao: 原生上传失败({e})，尝试 pyautogui 兜底")

    try:
        import pyperclip
        import pyautogui
    except ImportError:
        logger.error("Shipinghao: 原生上传失败，且 pyautogui 不可用（它也不在 requirements.txt 里）")
        return False

    try:
        # 兜底：点开系统文件对话框 → 剪贴板粘贴路径 → 回车。会抢桌面，只在原生失败时才走。
        upload_area = await frame.wait_for_selector(SELECTORS["upload_area"], timeout=10000)
        if upload_area:
            await upload_area.click()
            await asyncio.sleep(1)
        pyperclip.copy(os.path.abspath(media_path))
        await asyncio.sleep(0.5)
        pyautogui.hotkey("ctrl", "v")
        await asyncio.sleep(0.5)
        pyautogui.press("enter")
        logger.info("Shipinghao: 视频已通过 pyautogui 兜底提交")
        return True
    except Exception as e:
        logger.error(f"Shipinghao: pyautogui 兜底也失败: {e}")
        return False


async def _dump_visible_buttons(frame: Frame) -> None:
    """把当前 frame 里可见的按钮文本打进日志。

    这个平台此前两次失败都只留下一句笼统的 Publish error，日志里没有任何可定位的信息；
    下次再出问题，这一行就能直接看出按钮是不是换了文案。
    """
    try:
        texts = await frame.evaluate(
            "() => Array.from(document.querySelectorAll('button'))"
            "  .filter(b => b.offsetParent !== null && (b.innerText || '').trim())"
            "  .map(b => (b.innerText || '').trim().slice(0, 20))"
        )
        logger.error(f"Shipinghao: 当前可见按钮: {texts}")
    except Exception as e:
        logger.warning(f"Shipinghao: 列可见按钮失败: {e}")


async def publish(
    page: Page,
    account,
    media_paths: list[str],
    title: Optional[str],
    description: Optional[str],
    *,
    before_submit,
) -> bool:
    try:
        logger.info(f"Shipinghao: Starting publish for {account.name}")
        logger.info(f"Shipinghao: Title={title}, MediaPaths={media_paths}")
        
        if not media_paths:
            logger.error(f"Shipinghao: No media files provided for {account.name}")
            return False
        
        if not os.path.exists(media_paths[0]):
            logger.error(f"Shipinghao: Media file not found: {media_paths[0]}")
            return False
        
        # 6. 导航到发布页
        await _safe_goto(page, PUBLISH_URL, "导航到发布页")
        await asyncio.sleep(3)

        if "login" in page.url.lower():
            logger.error(f"Shipinghao: Account {account.name} session expired")
            return False

        # 7. 上传视频
        #    发布表单整个在 iframe 里，主帧只有顶部导航 —— 必须先在正确的 frame 里操作，
        #    否则下面每一个选择器都会超时（这是本函数此前一直失败的原因之一）。
        frame = await _resolve_frame(page, "发布页")
        if frame is None:
            await _dump_visible_buttons(page.main_frame)
            return False
        if not await _upload_video(frame, media_paths[0]):
            return False

        for i in range(60):
            await asyncio.sleep(5)
            try:
                btn = await frame.query_selector(PUBLISH_BTN_SELECTOR)
                if btn:
                    break
            except Exception:
                pass
            if i == 59:
                logger.error("Shipinghao: Video upload timeout")
                await _dump_visible_buttons(frame)
                return False

        if description:
            desc_input = await frame.wait_for_selector(
                SELECTORS["desc_input"], timeout=10000
            )
            if desc_input:
                await desc_input.click()
                await page.keyboard.type(description, delay=50)

        if title and len(title) >= 6:
            title_truncated = title[:16]
            title_input = await frame.wait_for_selector(
                SELECTORS["title_input"], timeout=10000
            )
            if title_input:
                await title_input.fill(title_truncated)

        try:
            publish_btn = await frame.wait_for_selector(
                PUBLISH_BTN_SELECTOR, timeout=10000
            )
        except Exception as e:
            logger.error(f"Shipinghao: 没等到可用的「发表」按钮: {e}")
            await _dump_visible_buttons(frame)
            return False
        if publish_btn:
            await before_submit()
            await publish_btn.click()
        else:
            logger.error("Shipinghao: Publish button not found or disabled")
            await _dump_visible_buttons(frame)
            return False

        await asyncio.sleep(30)

        logger.info(f"Shipinghao: Publish successful for {account.name}")
        return True

    except Exception as e:
        logger.error(f"Shipinghao: Publish error for {account.name}: {e}")
        return False

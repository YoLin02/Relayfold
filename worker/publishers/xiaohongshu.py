from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Optional
from urllib.parse import urlsplit

from playwright.async_api import Page, Frame, Locator
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout

logger = logging.getLogger("video_publisher")

VIDEO_PUBLISH_URL = "https://creator.xiaohongshu.com/publish/publish?from=menu&target=video"
VIDEO_PROCESS_SECONDS = 600
BUTTON_READY_SECONDS = 120
PUBLISH_LABEL = re.compile(r"^(发布|立即发布|发布笔记)$")
PUBLISH_HOST = 'xhs-publish-btn[is-publish="true"][submit-text]'

SELECTORS = {
    "file_input": 'input[type="file"]',
    "title_input": 'input[placeholder*="填写标题"]',
    "content_editor": "div.tiptap.ProseMirror",
    "publish_button": '.publish-page-publish-btn button:nth-child(2)',
    "image_preview": ".img-preview-area .pr",
}

# —— 标题输入：多级备选 ——
TITLE_SELECTORS = [
    'input[placeholder*="填写标题"]',
    'input.d-text',
    'div.d-input input',
    'input[placeholder*="标题"]',
]

# —— 正文编辑器：多级备选 ——
CONTENT_SELECTORS = [
    'div.tiptap.ProseMirror',
    'div.ProseMirror[contenteditable="true"]',
    'div.ql-editor',
    '[role="textbox"]',
]


async def _safe_goto(page: Page, url: str, description: str = "") -> None:
    """安全导航到指定 URL，三层降级：domcontentloaded → load → commit"""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        logger.info(f"Xiaohongshu: {description} goto domcontentloaded ok, url={page.url}")
    except Exception as e:
        logger.warning(f"Xiaohongshu: {description} goto domcontentloaded failed: {e}")
        try:
            await page.goto(url, wait_until="load", timeout=30000)
            logger.info(f"Xiaohongshu: {description} goto load ok, url={page.url}")
        except Exception as e2:
            logger.warning(f"Xiaohongshu: {description} goto load also failed: {e2}")
            try:
                await page.goto(url, wait_until="commit", timeout=30000)
                await asyncio.sleep(5)
                logger.info(f"Xiaohongshu: {description} goto commit ok, url={page.url}")
            except Exception as e3:
                logger.error(f"Xiaohongshu: {description} goto completely failed: {e3}")


async def _resolve_frame(page: Page, description: str = "") -> Frame:
    """检测页面是否在 iframe 中，返回包含发布表单的正确 frame"""
    frames = page.frames
    logger.info(f"Xiaohongshu: {description} total frames: {len(frames)}")
    for idx, f in enumerate(frames):
        logger.info(f"Xiaohongshu: {description} frame[{idx}]: url={f.url[:80] if f.url else 'about:blank'}")

    for f in reversed(frames):
        try:
            if await f.locator(SELECTORS["file_input"]).count() > 0:
                logger.info(f"Xiaohongshu: {description} found file input in frame")
                return f
        except Exception:
            pass
        try:
            if await f.locator(SELECTORS["publish_button"]).count() > 0:
                logger.info(f"Xiaohongshu: {description} found publish button in frame")
                return f
        except Exception:
            pass

    logger.warning(f"Xiaohongshu: {description} no publish form in any frame, using main frame")
    return page.main_frame


# ═══════════════════════════════════════════════════════════════
#  标题 / 正文 / 发布按钮  — 参考 XiaohongshuSkills 实现
# ═══════════════════════════════════════════════════════════════

async def _fill_title_js(frame: Frame, title: str) -> bool:
    """使用 JS native setter 设置标题，绕过 Vue 框架的双向绑定"""
    selector_list = ", ".join(TITLE_SELECTORS)
    result = await frame.evaluate(f"""(data) => {{
        const el = document.querySelector('{selector_list}');
        if (!el) return 'not_found';
        const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
        nativeSetter.call(el, data);
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        return 'ok';
    }}""", title)
    return result == "ok"


async def _fill_description_js(editor: Locator, description: str) -> None:
    """直接操作 DOM 填入正文，代替逐字键盘输入"""
    await editor.evaluate("""(el, text) => {
        el.focus();
        while (el.firstChild) el.removeChild(el.firstChild);
        const lines = text.split('\\n');
        lines.forEach(line => {
            const p = document.createElement('p');
            p.textContent = line;
            el.appendChild(p);
        });
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
    }""", description)


async def _fill_body(frame: Frame, description: str, tags) -> None:
    editor = frame.locator(", ".join(CONTENT_SELECTORS)).filter(visible=True).first
    await editor.wait_for(timeout=15000)
    await _fill_description_js(editor, description or "")
    if not tags:
        return
    await editor.focus()
    keyboard = frame.page.keyboard
    await keyboard.press("Control+End")
    topics = frame.locator("#creator-editor-topic-container .item")
    for tag in tags:
        await keyboard.type(f" #{tag}", delay=30)
        item = topics.filter(visible=True).filter(
            has=frame.get_by_text(tag, exact=True).or_(frame.get_by_text(f"#{tag}", exact=True)))
        # Some editor versions render the topic name directly on the item.
        exact_item = topics.and_(frame.get_by_text(tag, exact=True).or_(frame.get_by_text(f"#{tag}", exact=True)))
        try:
            await item.or_(exact_item).first.click(timeout=10000)
        except PlaywrightTimeout as exc:
            raise ValueError(f"小红书没有返回匹配的话题「{tag}」，请修改后重试。") from exc
    await keyboard.press("Escape")


async def _set_video_cover(frame: Frame, cover: str) -> None:
    trigger = frame.locator("div.upload-cover, div.cover-plugin-preview div.default.pointer").filter(visible=True)
    trigger = trigger.or_(frame.get_by_text("编辑封面", exact=True).filter(visible=True))
    modal = frame.locator('div.d-modal:visible, [role="dialog"]:visible').filter(has_text="上传封面").first
    try:
        await trigger.first.click(timeout=90000)
        await modal.get_by_text("上传封面", exact=True).first.click(timeout=10000)
        upload = modal.locator('input[type="file"][accept*="image"]').first
        await upload.set_input_files(cover, timeout=10000)
        footer = modal.locator("div.d-modal-footer").get_by_text("确定", exact=True)
        confirm = footer.or_(modal.get_by_role("button", name="确定", exact=True))
        await confirm.first.click(timeout=60000)
        await modal.wait_for(state="hidden", timeout=15000)
    except PlaywrightTimeout as exc:
        raise ValueError("未能设置小红书自定义封面。请检查图片规格后重试。") from exc


def _dom_subtree(node):
    yield node
    for child in node.get("children", ()):
        yield from _dom_subtree(child)


class _ClosedPublishButton:
    """Resolve the video editor's native button inside its closed shadow root."""

    def __init__(self, page: Page, host: Locator, label: str):
        self.page = page
        self.host = host
        self.label = label

    async def is_enabled(self) -> bool:
        return (await self.host.count() == 1 and
                await self.host.get_attribute("submit-disabled", timeout=2500) == "false")

    async def _target(self, cdp):
        root = (await cdp.send("DOM.getDocument", {"depth": 0}))["root"]
        matches = (await cdp.send("DOM.querySelectorAll", {
            "nodeId": root["nodeId"], "selector": PUBLISH_HOST,
        }))["nodeIds"]
        if len(matches) != 1:
            raise PlaywrightError("无法唯一定位小红书发布组件。")
        host = (await cdp.send("DOM.describeNode", {
            "nodeId": matches[0], "depth": -1, "pierce": True,
        }))["node"]
        buttons = []
        for shadow in host.get("shadowRoots", ()):
            if shadow.get("shadowRootType") != "closed":
                continue
            for node in _dom_subtree(shadow):
                if node.get("localName") != "button":
                    continue
                descendants = list(_dom_subtree(node))
                label = "".join(child.get("nodeValue", "") for child in descendants
                                if child.get("nodeType") == 3).strip()
                if label == self.label:
                    buttons.append((node, descendants))
        if len(buttons) != 1:
            raise PlaywrightError("发布组件内没有唯一的小红书发布按钮。")
        button, descendants = buttons[0]
        attrs = button.get("attributes", ())
        props = dict(zip(attrs[::2], attrs[1::2]))
        if ("disabled" in props or props.get("aria-disabled") == "true" or
                re.search(r"(^|[-_\s])disabled($|[-_\s])", props.get("class", ""))):
            raise PlaywrightError("小红书发布按钮仍处于禁用状态。")
        return button["backendNodeId"], {node["backendNodeId"] for node in descendants}

    async def click(self, *, timeout, trial=False):
        async with asyncio.timeout(timeout / 1000):
            if not await self.is_enabled():
                raise PlaywrightError("小红书发布组件尚未启用。")
            cdp = await self.page.context.new_cdp_session(self.page)
            try:
                button_id, subtree = await self._target(cdp)
                await cdp.send("DOM.scrollIntoViewIfNeeded", {"backendNodeId": button_id})
                quads = (await cdp.send("DOM.getContentQuads", {"backendNodeId": button_id}))["quads"]
                if len(quads) != 1:
                    raise PlaywrightError("小红书发布按钮没有唯一的可点击区域。")
                quad = quads[0]
                x = round(sum(quad[0::2]) / 4)
                y = round(sum(quad[1::2]) / 4)
                hit = await cdp.send("DOM.getNodeForLocation", {"x": x, "y": y, "includeUserAgentShadowDOM": True})
                if hit.get("backendNodeId") not in subtree:
                    raise PlaywrightError("小红书发布按钮当前无法接收点击。")
                if not trial:
                    await self.page.mouse.click(x, y)
            finally:
                try:
                    await cdp.detach()
                except PlaywrightError:
                    pass


async def _find_publish_button(frame: Frame, *, allow_closed=False) -> Optional[Locator | _ClosedPublishButton]:
    """Only choose a visible button with an exact publishing label."""
    container = frame.locator(".publish-page-publish-btn, xhs-publish-btn")
    buttons = container.get_by_role("button", name=PUBLISH_LABEL).filter(visible=True)
    if await buttons.count() == 1:
        return buttons.first
    if allow_closed:
        hosts = frame.locator(PUBLISH_HOST).filter(visible=True)
        count = await hosts.count()
        if count:
            if count == 1 and frame == frame.page.main_frame:
                host = hosts.first
                label = await host.get_attribute("submit-text", timeout=2500)
                if label and PUBLISH_LABEL.fullmatch(label):
                    return _ClosedPublishButton(frame.page, host, label)
            return None
    buttons = frame.get_by_role("button", name=PUBLISH_LABEL).filter(visible=True)
    return buttons.first if await buttons.count() == 1 else None


async def _is_publish_button_ready(btn: Locator | _ClosedPublishButton) -> bool:
    if isinstance(btn, _ClosedPublishButton):
        return await btn.is_enabled()
    return await btn.is_enabled(timeout=2500) and not await btn.evaluate(
        """element => [...element.classList].some(name => /(^|[-_])disabled($|[-_])/.test(name))""",
        timeout=2500,
    )


VIDEO_STATUS = r"""() => {
    const visible = el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
    const roots = [document];
    const panels = [];
    const controls = [];
    const previewStages = [];
    const transcodingIndicators = [];
    for (const root of roots) {
        panels.push(...root.querySelectorAll('.preview-new,[class*="upload-content"],[class*="video-upload"],[role="progressbar"]'));
        controls.push(...root.querySelectorAll('button,[role="button"]'));
        previewStages.push(...root.querySelectorAll('.preview-new .stage'));
        transcodingIndicators.push(...root.querySelectorAll('.cover-container .transcoding'));
        for (const element of root.querySelectorAll('*')) {
            if (element.shadowRoot) roots.push(element.shadowRoot);
        }
    }
    const body = document.body?.innerText || '';
    const uploadText = panels.filter(visible).map(el => el.innerText || el.textContent || '').join(' ');
    const candidates = controls.filter(visible).map(el => (el.innerText || el.textContent || '').trim());
    const lines = body.split(/[\r\n]+/).map(line => line.trim());
    const phase = /^(?:视频|文件)?(?:(?:正在)?上传中|正在上传|上传过程中|正在处理|处理中|处理视频|(?:正在)?转码中|正在转码|正在解析|解析中)(?:$|[：:，,。…(（\s\d]|请稍|请等待|视频|素材|文件)/;
    const transcoding = transcodingIndicators.some(visible);
    const busy = transcoding || lines.some(line => phase.test(line)) || panels.some(el => {
        if (!visible(el)) return false;
        if (el.getAttribute('aria-busy') === 'true') return true;
        const current = el.getAttribute('aria-valuenow');
        if (el.getAttribute('role') === 'progressbar' && current !== null &&
            Number(current) < Number(el.getAttribute('aria-valuemax') || 100)) return true;
        return (el.innerText || el.textContent || '').split(/[\r\n]+/).some(line => phase.test(line.trim()));
    });
    const uploadError = /上传失败|转码失败|视频处理失败|视频格式不支持/.test(body + ' ' + uploadText);
    // The video component renders these messages in its Preview state, after Transcoding.
    const previewReady = previewStages.some(el => visible(el) &&
        /检测为高清视频|视频分辨率较低/.test(el.innerText || el.textContent || ''));
    const complete = previewReady || /上传成功|视频已上传|上传完成|处理完成|重新上传|编辑封面/.test(uploadText) ||
        /上传成功|视频已上传|上传完成|视频处理完成/.test(body) ||
        candidates.some(text => /^(重新上传|编辑封面)$/.test(text));
    return { busy, uploadError, complete, transcoding };
}"""


async def _video_states(page):
    path = urlsplit(page.url).path.rstrip("/")
    if path in {"/new/note-manager", "/publish/success"}:
        raise ValueError("小红书页面已离开视频编辑区，Relayfold 尚未点击发布，请核对平台后台。")
    states = []
    for frame in page.frames:
        try:
            states.append((frame, await frame.evaluate(VIDEO_STATUS)))
        except PlaywrightError:
            if page.is_closed():
                raise ValueError("小红书发布页面已关闭。")
            # The upload UI can replace an iframe when the editor loads.
            continue
    return states


async def _wait_for_video_editor(page, progress):
    deadline = asyncio.get_running_loop().time() + VIDEO_PROCESS_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        states = await _video_states(page)
        if any(status["uploadError"] for _, status in states):
            raise ValueError("小红书页面报告视频上传或处理失败。")
        if any(status["transcoding"] for _, status in states):
            progress("小红书仍在转码，正在等待视频预览。")
        elif any(status["busy"] for _, status in states):
            progress("小红书仍在上传或处理视频。")
        elif any(status["complete"] for _, status in states):
            progress("小红书视频已处理完成，正在等待编辑区。")
            for frame, _ in states:
                try:
                    if await frame.locator(TITLE_SELECTORS[0]).filter(visible=True).count() == 1:
                        return frame
                except PlaywrightError:
                    continue
        else:
            progress("尚未识别到小红书的视频预览，正在等待状态更新。")
        await asyncio.sleep(1)
    raise ValueError("小红书等待视频处理或编辑区超时，还未提交。")


async def _wait_for_video_publish_button(page, progress):
    deadline = asyncio.get_running_loop().time() + BUTTON_READY_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        states = await _video_states(page)
        if any(status["uploadError"] for _, status in states):
            raise ValueError("小红书页面报告视频处理失败。")
        if any(status["busy"] for _, status in states):
            progress("小红书仍在处理视频，尚不能发布。")
        else:
            candidates = []
            for frame, _ in states:
                try:
                    if button := await _find_publish_button(frame, allow_closed=True):
                        candidates.append(button)
                except PlaywrightError:
                    continue
            if len(candidates) != 1:
                progress("正在定位小红书发布按钮，尚未找到唯一可见按钮。")
            else:
                button = candidates[0]
                try:
                    if await _is_publish_button_ready(button):
                        await button.click(trial=True, timeout=1800)
                        return button
                    progress("小红书发布按钮已出现，正在等待启用。")
                except (PlaywrightError, TimeoutError):
                    progress("小红书发布按钮尚未通过可点击检查。")
        await asyncio.sleep(1)
    raise ValueError("小红书发布按钮就绪等待超时，还未提交。")


async def _click_publish_button(btn: Locator) -> bool:
    """使用 Playwright 内置 click 点击发布按钮"""
    try:
        await btn.click()
        logger.info("Xiaohongshu: Publish button clicked via Playwright click()")
        return True
    except Exception as e:
        logger.error(f"Xiaohongshu: Playwright click() failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
#  发布入口
# ═══════════════════════════════════════════════════════════════

async def publish_video(
    page: Page,
    account,
    media_paths: list[str],
    title: Optional[str],
    description: Optional[str],
    before_submit,
    publish_url: str = VIDEO_PUBLISH_URL,
    *,
    tags=(),
    cover="",
    progress=None,
) -> bool:
    progress = progress or (lambda _detail: None)
    if not media_paths or not os.path.isfile(media_paths[0]):
        raise ValueError("小红书视频文件不存在。")

    progress("正在打开小红书视频发布页。")
    await _safe_goto(page, publish_url, "视频发布页导航")
    await asyncio.sleep(3)
    if "login" in page.url.lower():
        raise ValueError("小红书发布页跳回了登录页。")
    progress("正在查找小红书的视频上传控件。")
    frame = await _resolve_frame(page, "video")
    file_input = frame.locator('input[type="file"][accept*="video"], input[type="file"][accept*=".mp4"], input.upload-input')
    if not await file_input.count():
        file_input = frame.locator(SELECTORS["file_input"])
    await file_input.first.set_input_files(media_paths[0], timeout=15000)

    progress("小红书视频已选取，正在等待上传和处理完成。")
    frame = await _wait_for_video_editor(page, progress)
    progress("正在填写小红书标题、正文和话题。")
    if title:
        try:
            await frame.locator(TITLE_SELECTORS[0]).filter(visible=True).first.fill(title, timeout=10000)
        except PlaywrightError:
            if not await _fill_title_js(frame, title):
                raise ValueError("小红书视频标题未能填写。")
    await _fill_body(frame, description, tags)
    if cover:
        progress("正在设置小红书视频封面。")
        await _set_video_cover(frame, cover)

    progress("正在等待小红书发布按钮可点击。")
    button = await _wait_for_video_publish_button(page, progress)
    progress("小红书发布按钮已通过可点击检查，正在核对账号。")
    await before_submit()
    progress("正在点击小红书发布按钮。")
    await button.click(timeout=10000)
    progress("已点击小红书发布按钮，正在等待平台回执。")
    return True

async def publish_image(
    page: Page,
    account,
    media_paths: list[str],
    title: Optional[str],
    description: Optional[str],
    *,
    before_submit,
    publish_url: str,
    tags=(),
) -> bool:
    try:
        logger.info(f"Xiaohongshu: Starting image publish for {account.name}")

        if not media_paths:
            logger.error(f"Xiaohongshu: No media files provided for {account.name}")
            return False

        for p in media_paths:
            if not os.path.exists(p):
                logger.error(f"Xiaohongshu: Media file not found: {p}")
                return False

        await _safe_goto(page, publish_url, "图片发布页导航")
        await asyncio.sleep(3)
        frame = await _resolve_frame(page, "image")

        if "login" in page.url.lower():
            logger.error(f"Xiaohongshu: Account {account.name} session expired")
            return False

        file_input = frame.locator(SELECTORS["file_input"]).first
        await file_input.wait_for(state="attached", timeout=10000)
        if await file_input.get_attribute("multiple") is not None:
            await file_input.set_input_files(media_paths)
        else:
            for index, media_path in enumerate(media_paths):
                await file_input.set_input_files(media_path)
                await frame.locator(SELECTORS["image_preview"]).nth(index).wait_for(state="visible", timeout=20000)

        if title and not await _fill_title_js(frame, title):
            return False
        await _fill_body(frame, description, tags)

        publish_btn = await _find_publish_button(frame)
        if not publish_btn:
            logger.error("Xiaohongshu: Publish button not found")
            return False

        await publish_btn.click(trial=True, timeout=90000)
        await before_submit()
        if not await _click_publish_button(publish_btn):
            return False
        logger.info(f"Xiaohongshu: Image note published for {account.name}")
        await asyncio.sleep(5)
        return True

    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Xiaohongshu: Image publish error for {account.name}: {e}")
        return False



"""Instagram 视频（Reels）发布 —— Playwright 浏览器自动化。

网页端只能发到「当前登录的那个身份」，个人号直接发，专业号发到该号。
流程与网页端左侧「+」入口一致：
  创建弹窗 → 选文件 → 裁剪页（选「原版」→ 继续）→ 编辑页（继续）
  → 发布页（配文 → 打开「添加 AI 标签」→ 分享）→ 等待分享完成 → 完成
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from typing import Optional

from playwright.async_api import Page

from ._text import plain_text

logger = logging.getLogger("video_publisher")

HOME_URL = "https://www.instagram.com/"

# 左侧栏的「新建帖子 / +」（aria-label 跟随界面语言，中英文都试）
_NEW_POST_SELECTORS = (
    'svg[aria-label="新帖子"]',
    'svg[aria-label*="新帖子"]',
    'svg[aria-label="新建帖子"]',
    'svg[aria-label="New post"]',
    'svg[aria-label*="新建"]',
    'svg[aria-label*="new post" i]',
    'div[role="link"][aria-label*="新建帖子"]',
    'div[role="button"][aria-label*="新建帖子"]',
    'div[role="link"]:has(svg[aria-label*="新建"])',
    'a[href*="/create/"]',
)

# 弹窗里的按钮文案（中英文都试）。用 role + 文本精确定位，见 _click_dialog_button
_CONTINUE_NAMES = ("继续", "Next")
_SHARE_NAMES = ("分享", "Share")
_DONE_NAMES = ("完成", "Done")

# 发布完成后的提示文案（「分享了 Reels」/「已分享」）
_SHARED_TEXTS = ("分享了", "已分享", "Your reel has been shared", "Post shared")

# 裁剪页左下角那个按钮，点开才会出现比例选项列表
_ASPECT_MENU_NAMES = ("选择裁剪", "裁剪", "宽高比", "比例", "Select crop", "Crop", "Aspect ratio")

# 比例列表里的「原版」：平台默认是 1:1，不选原版视频会被裁成方的
_ORIGINAL_LABELS = ("原版", "原始", "原图", "原始比例", "原尺寸", "Original", "Original size")

_AI_LABEL_TEXTS = ("添加 AI 标签", "Add AI label")


async def publish(
    page: Page,
    account,
    media_paths: list[str],
    title: Optional[str] = None,
    description: Optional[str] = None,
    *,
    before_submit,
) -> bool:
    logger.info(f"Instagram: 开始发布 {account.name}，media={media_paths}")

    if not media_paths:
        raise RuntimeError("Instagram 发布需要视频文件")
    video = media_paths[0]
    if not os.path.exists(video):
        raise RuntimeError(f"视频文件不存在：{os.path.basename(video)}")

    await _open_create_dialog(page)

    # ① 选文件：直接喂给隐藏的 input，等价于点「从电脑中选择」后选文件
    try:
        file_input = await page.wait_for_selector(
            'div[role="dialog"] input[type="file"]', state="attached", timeout=15000
        )
        await file_input.set_input_files(video)
        logger.info("Instagram: 视频已选择，等待上传")
    except Exception as e:
        raise RuntimeError(f"Instagram 未找到上传入口：{e}")

    # ② 裁剪页：先把比例切成「原版」，再一路点「继续」到发布页
    # 顺序不能反：先点「继续」会直接离开裁剪页，比例就永远是平台默认的 1:1
    await _select_original_ratio(page)
    if not await _advance_to_publish_page(page):
        await _dump_debug(page)
        raise RuntimeError("Instagram 裁剪/编辑页的「继续」没能推进到发布页")

    # ③ 发布页：配文
    text = plain_text(title, description)
    if text:
        editor = await _first(
            page,
            ('div[role="dialog"] div[contenteditable="true"][aria-label*="caption" i]',
             'div[role="dialog"] textarea[aria-label*="caption" i]',
             'div[role="dialog"] div[contenteditable="true"]'),
            timeout=60000,
        )
        if not editor:
            raise RuntimeError("Instagram 未找到配文输入框")
        await editor.click()
        await asyncio.sleep(0.4)
        await page.keyboard.press("Control+a")
        await page.keyboard.press("Delete")
        await asyncio.sleep(0.3)
        await page.evaluate("t => navigator.clipboard.writeText(t)", text)
        await asyncio.sleep(0.3)
        await page.keyboard.press("Control+v")
        await asyncio.sleep(1.5)
        logger.info("Instagram: 配文已填写")

    # ⑤ 分享
    await before_submit()
    if not await _click_dialog_button(page, _SHARE_NAMES, timeout=30000):
        await _dump_debug(page)
        raise RuntimeError("Instagram 未找到「分享」按钮")
    logger.info("Instagram: 已点击「分享」，等待上传完成")

    # ⑥ 等「正在分享」走完，出现「分享了 Reels」
    shared = await _wait_shared(page, timeout=180)
    if not shared:
        raise RuntimeError("Instagram 点击分享后未出现完成提示，可能被风控拦截")

    # ⑦ 点「完成」，结束本次发布（浏览器由 runner 统一关闭）
    if await _click_dialog_button(page, _DONE_NAMES, timeout=15000):
        await asyncio.sleep(1.5)
    logger.info(f"Instagram: 发布完成 {account.name}")
    return True


async def _open_create_dialog(page: Page) -> None:
    """打开「创建新帖子」弹窗：进首页，点左侧栏的「+（新建帖子）」。"""
    await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=90000)
    await asyncio.sleep(5)
    _raise_if_blocked(page)
    logger.info(f"Instagram: 首页已加载 url={page.url}")

    if not await _click_new_post(page):
        await _dump_debug(page)
        raise RuntimeError(f"Instagram 未找到左侧「+」新建帖子入口（当前页 {page.url}）")

    try:
        await page.wait_for_selector('div[role="dialog"]', timeout=40000)
        logger.info("Instagram: 已通过左侧「+」打开创建弹窗")
    except Exception:
        await _dump_debug(page)
        raise RuntimeError(f"Instagram 点击「+」后创建弹窗没有打开（当前页 {page.url}）")


def _raise_if_blocked(page: Page) -> None:
    current = page.url.lower()
    if "/accounts/login" in current or "/challenge" in current:
        raise RuntimeError(f"Instagram 登录已失效或被风控拦截，当前页 {page.url}")


async def _click_new_post(page: Page) -> bool:
    """点左侧栏的「+ / 新建帖子」。

    每个选择器都真正等一会：首页首屏是懒渲染的，用 count() 即时判断会在
    左栏还没画出来时全部判空、直接返回失败。
    """
    for sel in _NEW_POST_SELECTORS:
        try:
            loc = page.locator(sel).first
            await loc.wait_for(state="visible", timeout=10000)
            try:
                await loc.click(timeout=5000)
            except Exception:
                # svg 图标本身可能被判为不可点击，强制点它的中心
                await loc.click(force=True, timeout=5000)
            await asyncio.sleep(3)
            return True
        except Exception:
            continue
    return False


async def _dump_debug(page: Page) -> None:
    """失败时留一张截图和左栏的 aria-label，省得只能看一句「没找到」。"""
    try:
        path = os.path.join(tempfile.gettempdir(), f"instagram_publish_{int(time.time())}.png")
        await page.screenshot(path=path)
        logger.error(f"Instagram: 失败现场截图 {path}，url={page.url}")
    except Exception:
        logger.error(f"Instagram: 失败现场截图失败，url={page.url}")
    try:
        labels = await page.evaluate(
            """() => Array.from(document.querySelectorAll('svg')).slice(0, 40).map(s => ({
                label: s.getAttribute('aria-label'),
                href: s.closest('a')?.getAttribute('href') || '',
                role: s.parentElement?.getAttribute('role') || ''
            }))"""
        )
        logger.error(f"Instagram: 页面 svg 清单 {labels}")
    except Exception as e:
        logger.error(f"Instagram: 读取页面 svg 清单失败: {e}")


async def _click_dialog_button(page: Page, names, timeout: int) -> bool:
    """点弹窗里文字精确匹配的按钮（继续 / 分享 / 完成）。

    Instagram 的按钮是 div[role="button"] 外包一层容器，用 has-text 定位会先命中
    外层父容器——点父容器的中心等于点在视频画面上，按钮毫无反应。role + exact
    只认最内层那个真正可点的元素。
    """
    per = max(5000, timeout // max(1, len(names)))
    dialog = page.locator('div[role="dialog"]').first
    deadline = asyncio.get_running_loop().time() + timeout
    for name in names:
        while asyncio.get_running_loop().time() < deadline:
            try:
                btn = dialog.get_by_role("button", name=name, exact=True).last
                await btn.wait_for(state="visible", timeout=per)
            except Exception:
                break  # 这个名字在这页不存在，换下一个（中/英）
            # 视频还在处理时「继续」是禁用的（aria-disabled），点它没有任何反应
            if (await btn.get_attribute("aria-disabled")) == "true":
                await asyncio.sleep(1)
                continue
            try:
                await btn.click(timeout=10000)
                return True
            except Exception:
                await asyncio.sleep(1)
    return False


async def _on_publish_page(page: Page) -> bool:
    """当前是否已经在最后那个发布页（有配文框或「分享」按钮）。"""
    dialog = page.locator('div[role="dialog"]').first
    try:
        if await dialog.locator('div[contenteditable="true"]').count():
            return True
    except Exception:
        pass
    for name in _SHARE_NAMES:
        try:
            if await dialog.get_by_role("button", name=name, exact=True).count():
                return True
        except Exception:
            continue
    return False


async def _advance_to_publish_page(page: Page, timeout: int = 240) -> bool:
    """反复点「继续」直到真正进入发布页。

    视频还在处理时「继续」画得出来、也点得下去，但页面不动；固定点两次必然
    漏掉，所以按「发布页特征出现」判断推进，没推进就再点一次。
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    clicks = 0
    while loop.time() < deadline:
        if await _on_publish_page(page):
            logger.info(f"Instagram: 已进入发布页（共点击 {clicks} 次「继续」）")
            return True
        if clicks >= 20:
            break
        if await _click_dialog_button(page, _CONTINUE_NAMES, timeout=8000):
            clicks += 1
            logger.info(f"Instagram: 已点击第 {clicks} 次「继续」")
        # 点完先让页面自己走，别连着点——连点会抢在裁剪页之前翻页
        await asyncio.sleep(5)
    return await _on_publish_page(page)


async def _select_original_ratio(page: Page) -> None:
    """把裁剪比例切成「原版」。

    平台默认是 1:1，不显式选原版视频会被裁成方的；选项默认收起，要先点
    左下角的比例按钮。视频还在处理时点了没反应，所以整段带重试；始终选不
    到就报错——宁可不发，也不能发一条被裁过的视频。
    """
    for _ in range(6):
        if await _open_aspect_menu(page) and await _pick_original(page):
            logger.info("Instagram: 裁剪比例已选「原版」")
            return
        await asyncio.sleep(2)

    await _dump_aspect_items(page)
    raise RuntimeError("Instagram 未能把裁剪比例选成「原版」")


async def _open_aspect_menu(page: Page) -> bool:
    """点开左下角的比例列表，返回「原版」选项是否真的出现了。

    只看「点到了按钮」不够：弹窗里还有「裁剪」这类同名页签，点上去列表不会
    展开，所以要按选项有没有露出来判断。
    """
    dialog = page.locator('div[role="dialog"]').first
    for name in _ASPECT_MENU_NAMES:
        try:
            btn = dialog.get_by_role("button", name=name, exact=False).first
            if not (await btn.count() and await btn.is_visible()):
                continue
            await btn.click(timeout=5000)
        except Exception:
            continue
        await asyncio.sleep(1)
        if await _original_visible(page):
            return True

    # 文案都对不上：按位置点弹窗下半部、左半边那个小按钮
    try:
        box = await dialog.bounding_box()
        if not box:
            return False
        best = None
        for h in await dialog.locator('div[role="button"], button').element_handles():
            try:
                b = await h.bounding_box()
            except Exception:
                continue
            if not b:
                continue
            rel_x, rel_y = b["x"] - box["x"], b["y"] - box["y"]
            if rel_y < box["height"] * 0.6 or rel_x > box["width"] * 0.4:
                continue
            if b["width"] > box["width"] * 0.25 or b["height"] > box["height"] * 0.25:
                continue
            key = (rel_x, -rel_y)
            if best is None or key < best[0]:
                best = (key, h)
        if not best:
            return False
        await best[1].click()
        await asyncio.sleep(1)
        return await _original_visible(page)
    except Exception:
        return False


async def _original_visible(page: Page) -> bool:
    """「原版」选项是否已经显示出来（列表可能挂在弹窗里，也可能是页面级浮层）。"""
    for text in _ORIGINAL_LABELS:
        for scope in (page.locator('div[role="dialog"]').first, page):
            try:
                el = scope.get_by_text(text, exact=True).first
                if await el.count() and await el.is_visible():
                    return True
            except Exception:
                continue
    return False


async def _pick_original(page: Page) -> bool:
    """在已弹出的比例列表里点「原版」。"""
    scopes = (page.locator('div[role="dialog"]').first, page)
    for text in _ORIGINAL_LABELS:
        for scope in scopes:
            for loc in (scope.get_by_role("button", name=text, exact=True),
                        scope.get_by_role("option", name=text, exact=True),
                        scope.get_by_text(text, exact=True)):
                try:
                    el = loc.first
                    if not await el.count() or not await el.is_visible():
                        continue
                    await el.click(timeout=5000)
                    await asyncio.sleep(1.2)
                    return True
                except Exception:
                    continue
    return False


async def _dump_aspect_items(page: Page) -> None:
    """选不到原版时把页面上的按钮/选项都打出来，省得靠猜文案。"""
    try:
        info = await page.evaluate(
            """() => Array.from(document.querySelectorAll(
                    '[role="button"], button, [role="option"], [role="menuitem"]'))
                .slice(0, 60)
                .map(b => {
                    const r = b.getBoundingClientRect();
                    return {
                        text: (b.innerText || '').trim().slice(0, 20),
                        label: b.getAttribute('aria-label') || '',
                        box: [Math.round(r.x), Math.round(r.y)]
                    };
                })"""
        )
        logger.error(f"Instagram: 裁剪页按钮清单 {info}")
    except Exception as e:
        logger.error(f"Instagram: 读取裁剪页按钮清单失败: {e}")


async def _wait_shared(page: Page, timeout: int) -> bool:
    """等待发布完成提示出现；超时返回 False。"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        await asyncio.sleep(3)
        for text in _SHARED_TEXTS:
            try:
                if await page.locator('div[role="dialog"]').get_by_text(text).count():
                    return True
            except Exception:
                continue
    return False


async def _first(page: Page, selectors, timeout: int):
    # 多个选择器平分等待时间：挨个等满 timeout 会让失败路径成倍变慢
    per_selector = max(3000, timeout // max(1, len(selectors)))
    for sel in selectors:
        try:
            el = await page.wait_for_selector(sel, timeout=per_selector)
            if el:
                return el
        except Exception:
            continue
    return None

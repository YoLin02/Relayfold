from __future__ import annotations

from typing import Optional

from patchright.async_api import TimeoutError as PatchrightTimeout
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeout
from publishers.social_auto_upload_douyin import prepare_video

PUBLISH_URL = "https://creator.douyin.com/creator-micro/content/upload"
TITLE = 'input[placeholder*="标题"]:visible'
EDITOR = ('div.zone-container[contenteditable="true"]:visible, '
          'div[contenteditable="true"][data-placeholder*="简介"]:visible, '
          'div[contenteditable="true"][data-placeholder*="描述"]:visible')
TIMEOUTS = (PlaywrightTimeout, PatchrightTimeout)


async def _fill_content(page, title, description, tags):
    await page.locator(TITLE).first.fill(title, timeout=180000)
    editor = page.locator(EDITOR).first
    await editor.fill(description or "", timeout=15000)
    if tags:
        await page.keyboard.press("Control+End")
        for tag in tags:
            await page.keyboard.type(f" #{tag}")
            await page.keyboard.press("Space")
        await page.keyboard.press("Escape")
        actual = (await editor.inner_text()).replace("\u00a0", " ")
        if any(f"#{tag}" not in actual for tag in tags):
            raise ValueError("抖音表单未能保留所选标签，发布已停止。")


async def _set_custom_cover(page, cover):
    modal = page.locator('div.dy-creator-content-modal:visible, [role="dialog"]:visible').filter(
        has_text="封面").first
    trigger = page.get_by_text("选择封面", exact=True).or_(
        page.get_by_text("编辑封面", exact=True)).or_(
        page.get_by_text("设置封面", exact=True)).filter(visible=True)
    if not await trigger.count():
        area = page.locator('[class*="cover-"]').filter(has=page.locator("img")).filter(visible=True).first
        if await area.count():
            await area.hover(timeout=4000)
    try:
        await trigger.first.click(timeout=12000)
        await modal.wait_for(timeout=10000)
        # Give the image to the real cover uploader rather than the adjacent AI reference slot.
        upload = modal.locator('.semi-upload:visible:has(.semi-upload-drag-area-main-text) input[type="file"]:not([class*="replace"]), '
                               '[class*="cover-upload"]:visible input[type="file"][accept*="image"]:not([class*="replace"])')
        await upload.first.set_input_files(cover, timeout=10000)
        button = modal.get_by_role("button", name="完成", exact=True).and_(modal.locator("button:not(.semi-button-disabled)"))
        await button.click(timeout=90000)
        if await modal.is_visible():
            confirm = page.get_by_role("button", name="确认", exact=True).or_(
                page.get_by_role("button", name="确定", exact=True)).filter(visible=True)
            if await confirm.count() == 1:
                await confirm.click(timeout=5000)
        await modal.wait_for(state="hidden", timeout=12000)
    except TIMEOUTS as exc:
        raise ValueError("未能设置抖音自定义封面。请检查图片规格后重试。") from exc


async def _set_declaration(page, declaration):
    entry = page.locator('div.selectBox-buZRzi').first
    if not await entry.is_visible() and declaration == "无需添加自主声明":
        return
    try:
        await entry.click(timeout=5000)
        option = page.get_by_text(declaration, exact=True).filter(visible=True)
        label = page.locator("label:visible").filter(has=option)
        await (label.first if await label.count() == 1 else option.last).click(timeout=5000)
        footer = page.locator('footer[class*="btnWrapper"]')
        await footer.get_by_role("button", name="确认", exact=True).or_(
            footer.get_by_role("button", name="确定", exact=True)).filter(visible=True).click(timeout=5000)
    except TIMEOUTS as exc:
        raise ValueError("未能设置抖音作品声明。") from exc


async def _submit(page, before_submit):
    button = page.locator("#popover-tip-container").get_by_role("button", name="发布", exact=True)
    if await button.count() != 1:
        button = page.get_by_role("button", name="发布", exact=True).filter(visible=True)
    await button.click(trial=True, timeout=15000)
    await before_submit()
    await button.click(timeout=10000)
    return True


async def publish_image(page, account, media_paths, title, description, declaration, before_submit, *, tags=()):
    await page.goto(PUBLISH_URL, wait_until="domcontentloaded", timeout=30000)
    await page.get_by_text("发布图文", exact=True).click(timeout=15000)
    upload = page.locator("div[class^='container'] input[type='file'][accept*='image']")
    await upload.first.set_input_files(media_paths, timeout=15000)
    await page.wait_for_url("**/creator-micro/content/post/image**", timeout=180000)
    await _fill_content(page, title, description, tags)
    await _set_declaration(page, declaration)
    await page.wait_for_function("""() =>
        !/文件解析中|上传过程中|图片上传中|正在上传/.test(document.body?.innerText || '')
    """, timeout=180000)
    return await _submit(page, before_submit)


async def publish(
    page: Page,
    account,
    media_paths: list[str],
    title: Optional[str],
    description: Optional[str],
    declaration: str,
    before_submit,
    *,
    tags=(),
    cover="",
) -> bool:
    if not media_paths:
        raise ValueError("请先选择抖音视频。")
    try:
        await prepare_video(page, media_paths[0])
    except TIMEOUTS as exc:
        raise ValueError("抖音未确认视频已上传并解析完成，发布已停止。") from exc

    if cover:
        await _set_custom_cover(page, cover)
    else:
        await _set_default_cover(page)
    await _set_declaration(page, declaration)
    await _fill_content(page, title, description, tags)
    await page.locator(EDITOR).first.blur()

    async def confirm_content():
        actual_title = await page.locator(TITLE).first.input_value(timeout=5000)
        actual_description = (await page.locator(EDITOR).first.inner_text(timeout=5000)).replace("\u00a0", " ")
        if actual_title != title or (description and description not in actual_description):
            raise ValueError("抖音发布前复核发现标题或正文未保留，已停止提交。")
        if any(f"#{tag}" not in actual_description for tag in tags):
            raise ValueError("抖音发布前复核发现标签未保留，已停止提交。")
        await before_submit()

    return await _submit(page, confirm_content)


async def _set_default_cover(page):
    trigger = page.get_by_text("选择封面", exact=True).or_(
        page.get_by_text("编辑封面", exact=True)).filter(visible=True)
    if not await trigger.count():
        trigger = page.get_by_text("设置封面", exact=True).filter(visible=True)
    if not await trigger.count():
        return

    modal = page.locator(".dy-creator-content-modal-wrap:visible").last
    try:
        await trigger.first.click(timeout=8000)
        await modal.wait_for(timeout=10000)
        horizontal = modal.get_by_role("button", name="设置横封面", exact=True).filter(visible=True)
        if await horizontal.count() == 1:
            await horizontal.click(timeout=8000)
        await modal.get_by_role("button", name="完成", exact=True).click(timeout=12000)
        await modal.wait_for(state="hidden", timeout=15000)
    except TIMEOUTS as exc:
        raise ValueError("抖音默认封面弹窗未完成，发布已停止。") from exc

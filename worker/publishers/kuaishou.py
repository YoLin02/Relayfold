from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from playwright.async_api import Page

logger = logging.getLogger("video_publisher")

PUBLISH_URL = "https://cp.kuaishou.com/article/publish/video?origin=www.kuaishou.com&source=NewReco"


async def publish(
    page: Page,
    account,
    media_paths: list[str],
    title: Optional[str],
    description: Optional[str],
    get_sms_code=None,
    *,
    before_submit,
) -> bool:
    try:
        logger.info(f"Kuaishou: Starting publish for {account.name}")
        logger.info(f"Kuaishou: Title={title}, Description={description}, MediaPaths={media_paths}")
        
        if not media_paths:
            logger.error(f"Kuaishou: No media files provided for {account.name}")
            return False
        
        if not os.path.exists(media_paths[0]):
            logger.error(f"Kuaishou: Media file not found: {media_paths[0]}")
            return False
        
        await page.goto(PUBLISH_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        if "login" in page.url.lower():
            logger.error(f"Kuaishou: Account {account.name} session expired")
            return False

        file_input = await page.wait_for_selector('input[type="file"]', state="attached", timeout=10000)
        if not file_input:
            return False
        await file_input.set_input_files(media_paths[0])
        await page.wait_for_function("""() => {
            const video = document.querySelector('video');
            const busy = /文件解析中|上传过程中|视频上传中|正在上传/.test(document.body?.innerText || '');
            return video && Number.isFinite(video.duration) && video.duration > 0 && !busy;
        }""", timeout=180000)

        # 2. 填写描述
        if description:
            try:
                logger.info("Kuaishou: Filling description...")
                desc_input = await page.wait_for_selector(
                    'div[contenteditable="true"]', timeout=10000
                )
                if desc_input:
                    await desc_input.scroll_into_view_if_needed()
                    await asyncio.sleep(0.5)
                    await desc_input.click()
                    await asyncio.sleep(0.5)
                    await page.keyboard.type(description, delay=50)
                    logger.info(f"Kuaishou: Description filled: {description}")
            except Exception as e:
                logger.error(f"Kuaishou: Failed to fill description: {e}")

        await asyncio.sleep(2)

        # 3. 点击发布按钮 - 使用正确的选择器（div 元素）
        logger.info("Kuaishou: Looking for publish button...")
        
        publish_btn = None
        
        # 选择器 1: div._button-primary_3a3lq_60 包含文本"发布"
        try:
            buttons = await page.query_selector_all('div._button-primary_3a3lq_60')
            for btn in buttons:
                text = await btn.inner_text()
                if '发布' in text:
                    publish_btn = btn
                    logger.info(f"Kuaishou: Found publish button (primary class), text: {text}")
                    break
        except Exception as e:
            logger.warning(f"Selector 1 failed: {e}")
        
        # 选择器 2: div._button_3a3lq_1 包含文本"发布"
        if not publish_btn:
            try:
                buttons = await page.query_selector_all('div._button_3a3lq_1')
                for btn in buttons:
                    text = await btn.inner_text()
                    if '发布' in text:
                        publish_btn = btn
                        logger.info(f"Kuaishou: Found publish button (button class), text: {text}")
                        break
            except Exception as e:
                logger.warning(f"Selector 2 failed: {e}")
        
        # 选择器 3: 任何 div 包含文本"发布"
        if not publish_btn:
            try:
                divs = await page.query_selector_all('div')
                for div in divs:
                    text = await div.inner_text()
                    if text == '发布':
                        publish_btn = div
                        logger.info(f"Kuaishou: Found publish button (exact text match)")
                        break
            except Exception as e:
                logger.warning(f"Selector 3 failed: {e}")
        
        # 选择器 4: 通过 XPath
        if not publish_btn:
            try:
                publish_btn = await page.query_selector('xpath=//div[contains(text(), "发布")]')
                if publish_btn:
                    logger.info(f"Kuaishou: Found publish button via XPath")
            except Exception as e:
                logger.warning(f"Selector 4 failed: {e}")
        
        if not publish_btn:
            logger.error("Kuaishou: Publish button not found")
            return False
        
        await before_submit()
        # 确保按钮可见并可点击
        try:
            await publish_btn.scroll_into_view_if_needed()
            await asyncio.sleep(0.5)
            
            # 检查按钮是否可点击
            is_disabled = await publish_btn.is_disabled() if hasattr(publish_btn, 'is_disabled') else False
            if is_disabled:
                logger.error("Kuaishou: Publish button is disabled")
                return False
            
            # 点击按钮
            await publish_btn.click()
            logger.info(f"Kuaishou: Publish button clicked for {account.name}")
            
            # 等待点击后的反应
            await asyncio.sleep(3)
        except Exception as e:
            logger.error(f"Kuaishou: Failed to click publish button: {e}")
            return False

        # 4. 处理短信验证（如果需要）
        try:
            sms_input = await page.wait_for_selector(
                'input[placeholder*="验证码"]', timeout=5000
            )
            if sms_input:
                logger.info(f"Kuaishou: SMS verification required")
                if not get_sms_code:
                    logger.error("Kuaishou: SMS callback not provided, cannot verify")
                    return False

                code = None
                for _ in range(60):
                    code = get_sms_code(account.id)
                    if code:
                        break
                    await asyncio.sleep(2)

                if code:
                    await sms_input.fill(code)
                    confirm_btn = await page.query_selector('button:has-text("确认")')
                    if confirm_btn:
                        await confirm_btn.click()
                else:
                    logger.warning(f"Kuaishou: SMS code timeout")
                    return False
        except Exception:
            pass

        await asyncio.sleep(5)
        logger.info(f"Kuaishou: Publish completed for {account.name}")
        return True

    except Exception as e:
        logger.error(f"Kuaishou: Publish error for {account.name}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

"""YouTube Shorts 发布模块 — Playwright 浏览器自动化"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from playwright.async_api import Page

logger = logging.getLogger("video_publisher")


async def publish(
    page: Page,
    account,
    media_paths: list[str],
    title: Optional[str],
    description: Optional[str],
    get_sms_code=None,
    declaration_type: int = 1,
    *,
    before_submit,
) -> bool:
    """
    YouTube Shorts 发布流程：
    ① 打开 Studio 上传页 → ② 选视频文件 → ③ 填标题+说明
    → ④ 儿童内容=否 → ⑤ 公开 → ⑥ 发布
    """
    try:
        logger.info(f"YouTube: Starting publish for {account.name}")
        logger.info(f"YouTube: Title={title}, Description={description}")

        if not media_paths or not os.path.exists(media_paths[0]):
            logger.error(f"YouTube: No valid media file for {account.name}")
            return False

        # ===== ① 打开 Studio 上传页 =====
        logger.info("YouTube: Opening Studio upload page...")
        await page.goto("https://studio.youtube.com/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        if "login" in page.url.lower() or "accounts.google.com" in page.url.lower():
            logger.error(f"YouTube: Account {account.name} not logged in")
            return False

        # 直接导航到上传页（YouTube Studio 会自动跳转到当前账号的频道）
        await page.goto("https://studio.youtube.com/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)
        # 点右上角"创建"→"上传视频"
        create_btn = await page.query_selector('button[aria-label="创建"], ytcp-button:has-text("创建")')
        if create_btn:
            await create_btn.click()
            await asyncio.sleep(1)
            upload_link = await page.query_selector('a:has-text("上传视频"), tp-yt-paper-item:has-text("上传")')
            if upload_link:
                await upload_link.click()
                await asyncio.sleep(3)
            else:
                # 降级：用已知的频道 ID
                await page.goto("https://studio.youtube.com/channel/UCsHq_u7IexsDWBZx-XMHieQ/videos/upload", wait_until="domcontentloaded", timeout=60000)
        else:
            # 降级：用已知的频道 ID
            await page.goto("https://studio.youtube.com/channel/UCsHq_u7IexsDWBZx-XMHieQ/videos/upload", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(5)

        # ===== ② 上传视频文件 =====
        logger.info("YouTube: Uploading video...")
        file_input = await page.wait_for_selector(
            'input[type="file"][name="Filedata"]',
            state="attached",
            timeout=15000
        )
        if not file_input:
            logger.error("YouTube: File input not found")
            return False

        await file_input.set_input_files(media_paths[0])
        logger.info(f"YouTube: Video uploaded for {account.name}")

        # 等待视频处理 + 转到详情编辑页
        await asyncio.sleep(10)

        # ===== ③ 填写标题和说明 =====
        # YouTube Studio 是 Polymer SPA，上传后自动跳到详情页
        textboxes = await page.query_selector_all('div#textbox[contenteditable="true"]')
        logger.info(f"YouTube: Found {len(textboxes)} contenteditable textboxes")

        if len(textboxes) >= 1 and title:
            try:
                logger.info("YouTube: Filling title...")
                await textboxes[0].click()
                await asyncio.sleep(0.5)
                await page.keyboard.press("Control+a")
                await page.keyboard.press("Delete")
                await asyncio.sleep(0.3)
                await page.keyboard.type(title, delay=30)
                logger.info(f"YouTube: Title filled: {title}")
            except Exception as e:
                logger.warning(f"YouTube: Failed to fill title: {e}")

        if len(textboxes) >= 2 and description:
            try:
                logger.info("YouTube: Filling description...")
                await textboxes[1].click()
                await asyncio.sleep(0.5)
                await page.keyboard.type(description, delay=20)
                logger.info(f"YouTube: Description filled: {description[:60]}...")
            except Exception as e:
                logger.warning(f"YouTube: Failed to fill description: {e}")

        await asyncio.sleep(2)

        # ===== ④ 儿童内容 = 否 =====
        try:
            not_kids_radio = await page.wait_for_selector(
                f'tp-yt-paper-radio-button[name="{("VIDEO_MADE_FOR_KIDS_MFK" if account.youtube_kids else "VIDEO_MADE_FOR_KIDS_NOT_MFK")}"]',
                timeout=10000
            )
            if not_kids_radio:
                # 检查是否已选中（active="" 或 checked=""）
                is_checked = await not_kids_radio.get_attribute("checked")
                if is_checked is None:
                    await not_kids_radio.click()
                    await asyncio.sleep(1)
                    logger.info("YouTube: Set 'not for kids'")
                else:
                    logger.info("YouTube: Already set 'not for kids'")
        except Exception:
            return False

        # ===== ⑤ 跳到公开范围步骤 =====
        try:
            review_btn = await page.wait_for_selector(
                'button[test-id="REVIEW"]',
                timeout=10000
            )
            if review_btn:
                await review_btn.click()
                await asyncio.sleep(3)
                logger.info("YouTube: Navigated to visibility step")
        except Exception:
            logger.warning("YouTube: Could not navigate to REVIEW step, may already be there")

        # ===== ⑥ 设为公开 =====
        try:
            public_radio = await page.wait_for_selector(
                f'tp-yt-paper-radio-button[name="{account.youtube_visibility}"]',
                timeout=10000
            )
            if public_radio:
                is_checked = await public_radio.get_attribute("checked")
                if is_checked is None:
                    await public_radio.click()
                    await asyncio.sleep(1)
                    logger.info("YouTube: Set visibility to Public")
                else:
                    logger.info("YouTube: Already set to Public")
        except Exception:
            return False

        await asyncio.sleep(2)

        await before_submit()
        # ===== ⑦ 点击发布 =====
        try:
            publish_btn = await page.wait_for_selector(
                'button[aria-label="发布"], button[aria-label="Publish"], button[aria-label="保存"], button[aria-label="Save"], #done-button',
                timeout=15000
            )
            if publish_btn:
                await publish_btn.click()
                await asyncio.sleep(5)
                logger.info(f"YouTube: Published for {account.name}")
                return True
            else:
                logger.error("YouTube: Publish button not found")
                return False
        except Exception as e:
            logger.error(f"YouTube: Failed to click publish: {e}")
            return False

    except Exception as e:
        error_str = str(e)
        if "Target page, context or browser has been closed" in error_str or "TargetClosedError" in error_str:
            raise
        logger.error(f"YouTube: Publish error for {account.name}: {e}")
        return False

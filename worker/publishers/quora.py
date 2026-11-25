from __future__ import annotations

import asyncio
import logging
from typing import Optional

from playwright.async_api import Page

logger = logging.getLogger("video_publisher")

QUORA_URL = "https://www.quora.com/"


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
        logger.info(f"Quora: Starting post publish for {account.name}")
        logger.info(f"Quora: Title={title}, Description length={len(description) if description else 0}")

        if not description:
            logger.error("Quora: No post content provided")
            return False

        await page.goto(QUORA_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)

        if "/login" in page.url.lower():
            logger.error(f"Quora: Account {account.name} session expired")
            return False

        # Step 1: 点击 "Add question" 按钮 → 弹出对话框
        try:
            await page.click('button[aria-label="Add question"]', timeout=5000)
            await asyncio.sleep(2)
            logger.info("Quora: Add question dialog opened")
        except Exception as e:
            logger.error(f"Quora: Add question button not found: {e}")
            return False

        # Step 2: 在弹窗中点击 "Create Post"
        try:
            await page.click('div.qu-dynamicFontSize--button:has-text("Create Post")', timeout=15000)
            await asyncio.sleep(3)
            logger.info("Quora: Create Post clicked, editor should be open")
        except Exception as e:
            logger.error(f"Quora: Create Post click failed: {e}")
            return False

        # Step 3: DOM 注入标题+正文到 contenteditable 编辑器（秒级完成）
        try:
            editor = await page.wait_for_selector(
                'div.doc[contenteditable="true"]',
                timeout=10000
            )
            if not editor:
                logger.error("Quora: Editor not found")
                return False

            full_content = ""
            if title:
                full_content += "<h1>" + title + "</h1>\n"
            full_content += "<p>" + description.replace("\n", "</p>\n<p>") + "</p>"

            injected = await page.evaluate('''html => {
                const editor = document.querySelector('div.doc[contenteditable="true"]');
                if (!editor) return false;
                editor.innerHTML = html;
                editor.dispatchEvent(new Event('input', {bubbles: true}));
                editor.dispatchEvent(new Event('change', {bubbles: true}));
                return true;
            }''', full_content)
            if injected:
                logger.info(f"Quora: Content injected via DOM ({len(full_content)} chars)")
            else:
                logger.warning("Quora: Editor not found for DOM injection")
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"Quora: Failed to fill content: {e}")
            return False

        await before_submit()
        # Step 4: 等 Post 按钮启用然后点击
        await asyncio.sleep(3)
        try:
            await page.wait_for_function('''() => {
                const btn = document.querySelector('.puppeteer_test_modal_submit');
                return btn && !btn.disabled && !btn.hasAttribute('disabled');
            }''', timeout=15000, polling=1000)
            logger.info("Quora: Post button enabled")

            await page.click('.puppeteer_test_modal_submit')
            logger.info(f"Quora: Post clicked for {account.name}")
        except Exception as e:
            logger.error(f"Quora: Post click failed: {e}")
            return False

        await asyncio.sleep(5)
        logger.info(f"Quora: Publish completed, URL: {page.url}")
        return True

    except Exception as e:
        logger.error(f"Quora: Publish error for {account.name}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

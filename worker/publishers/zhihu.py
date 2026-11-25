from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from playwright.async_api import Page

logger = logging.getLogger("video_publisher")

ZHIHU_WRITE_URL = "https://zhuanlan.zhihu.com/write"


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
        logger.info(f"Zhihu: Starting article publish for {account.name}")
        logger.info(f"Zhihu: Title={title}, Description length={len(description) if description else 0}")

        if not description:
            logger.error("Zhihu: No article content provided")
            return False

        await page.goto(ZHIHU_WRITE_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        if "signin" in page.url.lower():
            logger.error(f"Zhihu: Account {account.name} session expired")
            return False

        # 1. Fill title
        if title:
            try:
                title_input = await page.wait_for_selector(
                    'textarea[placeholder*="标题"], input[placeholder*="标题"]',
                    timeout=10000
                )
                if title_input:
                    await title_input.click()
                    await asyncio.sleep(0.3)
                    await title_input.fill(title)
                    logger.info(f"Zhihu: Title filled: {title}")
                else:
                    logger.warning("Zhihu: Title input not found")
            except Exception as e:
                logger.error(f"Zhihu: Failed to fill title: {e}")

        # 2. Fill content (article body from description field)
        if description:
            try:
                content_editor = await page.wait_for_selector(
                    '.ProseMirror, div[contenteditable="true"]',
                    timeout=10000
                )
                if content_editor:
                    await content_editor.click()
                    await asyncio.sleep(0.5)

                    await page.keyboard.insert_text(description)
                    logger.info(f"Zhihu: Content inserted ({len(description)} chars)")

                    # Cut and paste to trigger markdown format detection
                    await page.keyboard.press('Control+a')
                    await page.keyboard.press('Control+x')
                    await asyncio.sleep(0.3)
                    await page.keyboard.press('Control+v')
                    logger.info("Zhihu: Re-pasted to trigger format detection")

                    # Click confirm markdown parse button
                    await asyncio.sleep(1.5)
                    for _ in range(10):
                        clicked = await page.evaluate('''() => {
                            const buttons = document.querySelectorAll('button');
                            for (const btn of buttons) {
                                if (btn.textContent.trim() === '确认并解析') {
                                    btn.click();
                                    return true;
                                }
                            }
                            return false;
                        }''')
                        if clicked:
                            logger.info("Zhihu: Confirmed Markdown parse")
                            await asyncio.sleep(5)
                            break
                        await asyncio.sleep(1)
                else:
                    logger.warning("Zhihu: Content editor not found")
            except Exception as e:
                logger.error(f"Zhihu: Failed to fill content: {e}")

        await before_submit()
        # 3. Click publish button
        await asyncio.sleep(2)
        published = False
        for _ in range(10):
            published = await page.evaluate('''() => {
                const buttons = document.querySelectorAll('button');
                for (const btn of buttons) {
                    if (btn.textContent.trim() === '发布' && btn.classList.contains('Button--primary')) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            }''')
            if published:
                logger.info(f"Zhihu: Article published for {account.name}")
                break
            await asyncio.sleep(1)

        if not published:
            logger.error("Zhihu: Publish button not found")
            return False

        await asyncio.sleep(5)
        logger.info(f"Zhihu: Publish completed for {account.name}")
        return True

    except Exception as e:
        logger.error(f"Zhihu: Publish error for {account.name}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

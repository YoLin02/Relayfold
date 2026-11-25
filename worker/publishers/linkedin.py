from __future__ import annotations

import asyncio
import logging
from typing import Optional

from playwright.async_api import Page

logger = logging.getLogger("video_publisher")

LINKEDIN_ARTICLE_URL = "https://www.linkedin.com/article-editor/"


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
        logger.info(f"LinkedIn: Starting article publish for {account.name}")
        logger.info(f"LinkedIn: Title={title}, Description length={len(description) if description else 0}")

        if not description:
            logger.error("LinkedIn: No article content provided")
            return False

        await page.goto(LINKEDIN_ARTICLE_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)

        if "/login" in page.url.lower() or "/signup" in page.url.lower():
            logger.error(f"LinkedIn: Account {account.name} session expired")
            return False

        # 1. Fill title — LinkedIn uses h1 or input as title
        if title:
            try:
                title_el = await page.wait_for_selector(
                    'h1[data-testid="article-title"], '
                    'input[placeholder*="Title"], '
                    'div[role="textbox"][aria-label*="title" i]',
                    timeout=10000
                )
                if title_el:
                    await title_el.click()
                    await asyncio.sleep(0.3)
                    await page.keyboard.type(title, delay=20)
                    logger.info(f"LinkedIn: Title typed: {title}")
                else:
                    logger.warning("LinkedIn: Title element not found")
            except Exception as e:
                logger.error(f"LinkedIn: Failed to type title: {e}")

        # 2. Fill body — Tab from title to body editor + keyboard.type
        if description:
            try:
                title_el = await page.query_selector('h1[data-testid="article-title"]')
                if not title_el:
                    title_el = await page.query_selector('input[placeholder*="Title"]')
                if title_el:
                    await title_el.click()
                    await asyncio.sleep(0.2)
                await page.keyboard.press('Tab')
                await asyncio.sleep(0.15)
                await page.keyboard.press('Tab')
                await asyncio.sleep(0.4)
                await page.keyboard.type(description)
                await asyncio.sleep(1)
                logger.info(f"LinkedIn: Body typed ({len(description)} chars)")
            except Exception as e:
                logger.error(f"LinkedIn: Failed to type body: {e}")

        await before_submit()
        # 3. Click Publish
        await asyncio.sleep(5)
        try:
            await page.click('button:has-text("Publish")', timeout=10000)
            logger.info(f"LinkedIn: Publish clicked for {account.name}")
        except Exception as e:
            logger.error(f"LinkedIn: Publish click failed: {e}")
            return False

        await asyncio.sleep(5)
        logger.info(f"LinkedIn: Publish completed, URL: {page.url}")
        return True

    except Exception as e:
        logger.error(f"LinkedIn: Publish error for {account.name}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

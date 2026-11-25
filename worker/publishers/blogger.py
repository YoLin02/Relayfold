from __future__ import annotations

import asyncio
import logging
from typing import Optional

from playwright.async_api import Page

logger = logging.getLogger("video_publisher")

BLOGGER_HOME = "https://draft.blogger.com/home"


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
        logger.info(f"Blogger: Starting post publish for {account.name}")
        logger.info(f"Blogger: Title={title}, Description length={len(description) if description else 0}")

        if not description:
            logger.error("Blogger: No post content provided")
            return False

        # 从 Blogger 后台开始
        await page.goto(BLOGGER_HOME, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        if "accounts.google.com" in page.url.lower():
            logger.error(f"Blogger: Account {account.name} session expired")
            return False

        # 等跳转到文章列表页 /blog/posts/{blogId}
        await asyncio.sleep(2)
        logger.info(f"Blogger: Current page URL = {page.url}")

        # 点击"新建博文"按钮（Blogger 中文界面的实际文案）
        clicked_new = False
        for _ in range(5):
            clicked_new = await page.evaluate('''() => {
                const all = document.querySelectorAll('span, div, a, button');
                for (const el of all) {
                    const t = el.textContent.trim();
                    if (t === '新建博文' || t === 'New post' || t === 'New Post') {
                        el.click();
                        return true;
                    }
                }
                return false;
            }''')
            if clicked_new:
                logger.info("Blogger: New post button clicked")
                break
            await asyncio.sleep(1)

        await asyncio.sleep(4)
        logger.info(f"Blogger: Editor URL = {page.url}")

        # 1. Fill title — input[jsname="YPqjbf"] or input[aria-label="标题"]
        if title:
            try:
                title_el = await page.wait_for_selector(
                    'input[jsname="YPqjbf"], input[aria-label="标题"], '
                    'input[aria-label*="Title" i]',
                    timeout=10000
                )
                if title_el:
                    await title_el.click()
                    await asyncio.sleep(0.3)
                    await page.keyboard.type(title, delay=20)
                    logger.info(f"Blogger: Title typed: {title}")
                else:
                    logger.warning("Blogger: Title input not found")
            except Exception as e:
                logger.error(f"Blogger: Failed to type title: {e}")

        # 2. Fill body — 24 次 Tab 从标题跳到正文编辑器
        if description and title:
            try:
                title_el = await page.query_selector('input[jsname="YPqjbf"], input[aria-label="标题"]')
                if title_el:
                    await title_el.click()
                    await asyncio.sleep(0.2)
                # 用户实测：24 次 Tab 才能切到正文编辑器
                for _ in range(24):
                    await page.keyboard.press('Tab')
                    await asyncio.sleep(0.02)
                await asyncio.sleep(0.3)
                await page.keyboard.type(description)
                await asyncio.sleep(1)
                logger.info(f"Blogger: Body typed via 24xTab+type ({len(description)} chars)")
            except Exception as e:
                logger.error(f"Blogger: Failed to fill body: {e}")

        await before_submit()
        # 3. 点击"发布"按钮
        await asyncio.sleep(3)
        try:
            published = await page.evaluate('''() => {
                const all = document.querySelectorAll('span, div, button');
                for (const el of all) {
                    if (el.textContent.trim() === '发布' || el.textContent.trim() === 'Publish') {
                        el.click();
                        return true;
                    }
                }
                return false;
            }''')
            if published:
                logger.info("Blogger: Publish clicked, waiting for confirm dialog...")
            else:
                logger.error("Blogger: Publish button not found")
                return False
        except Exception as e:
            logger.error(f"Blogger: Publish click failed: {e}")
            return False

        # 4. 确认发布弹窗 —— 点击"确认"
        await asyncio.sleep(2)
        try:
            confirmed = await page.evaluate('''() => {
                const all = document.querySelectorAll('span, div, button');
                for (const el of all) {
                    const text = el.textContent.trim();
                    if (text === '确认' || text === 'Confirm') {
                        el.click();
                        return true;
                    }
                }
                return false;
            }''')
            if confirmed:
                logger.info(f"Blogger: Confirm clicked for {account.name}")
            else:
                logger.warning("Blogger: Confirm button not found, may already be published")
        except Exception as e:
            logger.warning(f"Blogger: Confirm click failed: {e}")

        await asyncio.sleep(5)
        logger.info(f"Blogger: Publish completed, URL: {page.url}")
        return True

    except Exception as e:
        logger.error(f"Blogger: Publish error for {account.name}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from playwright.async_api import Page

logger = logging.getLogger("video_publisher")

MEDIUM_NEW_STORY_URL = "https://medium.com/new-story"


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
        logger.info(f"Medium: Starting article publish for {account.name}")
        logger.info(f"Medium: Title={title}, Description length={len(description) if description else 0}")

        if not description:
            logger.error("Medium: No article content provided")
            return False

        await page.goto(MEDIUM_NEW_STORY_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)

        if "/m/signin" in page.url.lower() or "/m/signup" in page.url.lower():
            logger.error(f"Medium: Account {account.name} session expired")
            return False

        # 1. Fill title — 用 keyboard.type 模拟真实打字，避免 Medium 编辑器检测
        if title:
            try:
                title_el = await page.wait_for_selector(
                    'h3[data-testid="editorTitleParagraph"]',
                    timeout=10000
                )
                if title_el:
                    await title_el.click()
                    await asyncio.sleep(0.3)
                    # keyboard.type 发送完整 keydown→keypress→input→keyup 序列
                    await page.keyboard.type(title, delay=20)
                    logger.info(f"Medium: Title typed: {title}")
                else:
                    logger.warning("Medium: Title element not found")
            except Exception as e:
                logger.error(f"Medium: Failed to type title: {e}")

        # 2. Fill body — 两次 Tab 切到编辑器，再用 keyboard.type
        if description:
            try:
                # 点击标题获取焦点，然后 Tab 切到正文
                title_el = await page.query_selector('h3[data-testid="editorTitleParagraph"]')
                if title_el:
                    await title_el.click()
                    await asyncio.sleep(0.2)
                await page.keyboard.press('Tab')
                await asyncio.sleep(0.15)
                await page.keyboard.press('Tab')
                await asyncio.sleep(0.4)
                # keyboard.type 无 delay = 最快速度，但仍分派完整键盘事件
                await page.keyboard.type(description)
                await asyncio.sleep(1)
                logger.info(f"Medium: Body typed ({len(description)} chars)")
            except Exception as e:
                logger.error(f"Medium: Failed to type body: {e}")

        # 3. 等 auto-save 完成（js-buttonDisabledPrimary 消失），再点发布
        await asyncio.sleep(5)
        try:
            await page.wait_for_function('''() => {
                const btn = document.querySelector('.js-publishButton');
                return btn && !btn.classList.contains('js-buttonDisabledPrimary');
            }''', timeout=30000, polling=1000)
            logger.info("Medium: Publish button ready")
        except Exception:
            logger.warning("Medium: Publish button wait timeout, trying anyway...")

        await before_submit()
        # 第一步：点击 Publish → 弹出确认框（用 page.click 自动处理导航）
        try:
            await page.click('[data-action="show-prepublish"]', timeout=10000)
            logger.info("Medium: Pre-publish clicked")
        except Exception:
            try:
                await page.click('.js-publishButton', timeout=5000)
                logger.info("Medium: Pre-publish clicked (fallback selector)")
            except Exception as e:
                logger.error(f"Medium: Pre-publish button click failed: {e}")
                return False

        # 第二步：等导航到 submission 页面
        await asyncio.sleep(3)
        logger.info(f"Medium: Current URL after publish click: {page.url}")
        try:
            await page.wait_for_url('**/submission**', timeout=15000)
            logger.info("Medium: Navigated to submission page")
        except Exception:
            logger.warning(f"Medium: Not on submission page, URL: {page.url}")

        # 第三步：在 submission 页面点击最终 Publish
        try:
            await page.wait_for_selector('button:has-text("Publish")', state='visible', timeout=15000)
            await asyncio.sleep(1)
            await page.click('button:has-text("Publish")')
            logger.info(f"Medium: Final publish clicked for {account.name}")
        except Exception as e:
            logger.warning(f"Medium: Final publish failed, trying alternatives: {e}")
            for text in ["Publish now", "Submit", "Confirm"]:
                try:
                    await page.click(f'button:has-text("{text}")', timeout=5000)
                    logger.info(f"Medium: Fallback clicked '{text}'")
                    break
                except Exception:
                    continue

        await asyncio.sleep(5)
        logger.info(f"Medium: Publish completed, URL: {page.url}")
        return True

    except Exception as e:
        logger.error(f"Medium: Publish error for {account.name}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

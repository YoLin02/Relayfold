from __future__ import annotations

import asyncio
import logging
from typing import Optional
from urllib.parse import urlparse

from playwright.async_api import Page

logger = logging.getLogger("video_publisher")

REDDIT_BASE = "https://www.reddit.com"


def _build_submit_url(account) -> str:
    """根据账号配置构建 Reddit 发布地址"""
    # 策略1: website_url 填了 subreddit（如 r/technology 或完整 URL）
    website = (getattr(account, "website_url", "") or "").strip()
    if website:
        # 如果是完整 URL，提取路径
        if website.startswith("http"):
            path = urlparse(website).path.rstrip("/")
        else:
            path = website.rstrip("/")
        # 确保以 /r/ 或 /user/ 开头
        if path.startswith("/r/") or path.startswith("/user/"):
            return f"{REDDIT_BASE}{path}/submit"
        # 可能只写了社区名，如 "technology"
        if not path.startswith("/"):
            return f"{REDDIT_BASE}/r/{path}/submit"

    # 策略2: 默认发到用户个人主页（account.name = Reddit 用户名）
    username = (account.name or "").strip()
    if username:
        return f"{REDDIT_BASE}/user/{username}/submit"

    # 兜底
    return f"{REDDIT_BASE}/submit"


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
        logger.info(f"Reddit: Starting post publish for {account.name}")
        logger.info(f"Reddit: Title={title}, Description length={len(description) if description else 0}")

        if not description:
            logger.error("Reddit: No post content provided")
            return False
        if not title:
            logger.error("Reddit: No title provided — Reddit posts require a title")
            return False

        submit_url = _build_submit_url(account)
        logger.info(f"Reddit: Submit URL = {submit_url}")

        await page.goto(submit_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)  # Reddit React SPA 需要时间渲染

        # Check if logged in
        if "login" in page.url.lower():
            logger.error(f"Reddit: Account {account.name} session expired (redirected to login)")
            return False

        # If using /user/xxx/submit or /r/xxx/submit, community is pre-selected.
        # Only need community selector for plain /submit.
        if submit_url == f"{REDDIT_BASE}/submit":
            logger.info("Reddit: No community pre-selected, trying to pick first available...")
            try:
                selector = await page.wait_for_selector(
                    'shreddit-community-selector button, button[aria-haspopup="dialog"]',
                    timeout=5000
                )
                if selector:
                    await selector.click()
                    await asyncio.sleep(1)
                    first = await page.wait_for_selector(
                        'shreddit-community-selector-option:first-child, li:first-child button',
                        timeout=5000
                    )
                    if first:
                        await first.click()
                        await asyncio.sleep(1)
                        logger.info("Reddit: Community selected from dropdown")
            except Exception as e:
                logger.warning(f"Reddit: Community selection failed: {e}")

        # 1. Fill title
        title_input = None
        try:
            title_input = await page.wait_for_selector(
                'textarea[name="title"], input[name="title"]',
                timeout=10000
            )
            if title_input:
                await title_input.click()
                await asyncio.sleep(0.3)
                await title_input.fill(title)
                logger.info(f"Reddit: Title filled: {title}")
            else:
                logger.warning("Reddit: Title input not found")
        except Exception as e:
            logger.error(f"Reddit: Failed to fill title: {e}")

        # 2. Fill body — 两次 Tab 切到编辑器，用 insert_text 注入（Lexical 兼容）
        if description and title_input:
            try:
                await title_input.click()
                await asyncio.sleep(0.1)
                await title_input.press('Tab')
                await asyncio.sleep(0.15)
                await page.keyboard.press('Tab')
                await asyncio.sleep(0.4)
                # 焦点已在编辑器，insert_text 直接写入且触发 Lexical 状态更新
                await page.keyboard.insert_text(description)
                await asyncio.sleep(1)
                logger.info(f"Reddit: Content inserted via Tab+insert_text ({len(description)} chars)")
            except Exception as e:
                logger.error(f"Reddit: Failed to fill content: {e}")

        # 3. Click post button (穿透 Shadow DOM)
        await asyncio.sleep(3)
        # 调试：先检查按钮状态
        btn_info = await page.evaluate('''() => {
            function deepQueryAll(root, selector) {
                const results = [...root.querySelectorAll(selector)];
                for (const node of root.querySelectorAll('*')) {
                    if (node.shadowRoot) results.push(...deepQueryAll(node.shadowRoot, selector));
                }
                return results;
            }
            const byId = document.querySelector('#inner-post-submit-button');
            if (byId) return 'found-in-light:' + byId.disabled;
            const deepById = deepQueryAll(document, '#inner-post-submit-button');
            if (deepById.length) return 'found-in-shadow:' + deepById[0].disabled;
            const allBtns = deepQueryAll(document, 'button');
            for (const b of allBtns) {
                const t = (b.textContent||'').trim();
                if (t==='发帖'||t==='Post') return 'found-by-text:' + b.disabled;
            }
            return 'not-found, total buttons searched: ' + allBtns.length;
        }''')
        logger.info(f"Reddit: Post button debug: {btn_info}")
        await before_submit()
        posted = False
        for i in range(10):
            posted = await page.evaluate('''() => {
                function deepQueryAll(root, selector) {
                    const results = [...root.querySelectorAll(selector)];
                    for (const node of root.querySelectorAll('*')) {
                        if (node.shadowRoot) {
                            results.push(...deepQueryAll(node.shadowRoot, selector));
                        }
                    }
                    return results;
                }
                // 先按 ID 精确匹配
                let btn = document.querySelector('#inner-post-submit-button');
                if (!btn) {
                    const deepBtns = deepQueryAll(document, '#inner-post-submit-button');
                    btn = deepBtns[0];
                }
                if (btn && !btn.disabled) { btn.click(); return true; }
                // 兜底：按文本匹配（中/英文界面），也穿透 Shadow DOM
                const allBtns = deepQueryAll(document, 'button');
                for (const b of allBtns) {
                    const text = (b.textContent || '').trim();
                    if ((text === '发帖' || text === 'Post') && !b.disabled) {
                        b.click();
                        return true;
                    }
                }
                return false;
            }''')
            if posted:
                logger.info(f"Reddit: Post submitted for {account.name}")
                break
            await asyncio.sleep(1)

        if not posted:
            logger.error("Reddit: Post button not found or disabled")
            return False

        # Wait for redirect to post page
        await asyncio.sleep(5)
        current_url = page.url
        if "/comments/" in current_url or "/user/" in current_url or "/r/" in current_url:
            logger.info(f"Reddit: Post published successfully, URL: {current_url}")
        else:
            logger.warning(f"Reddit: Post may not have published — current URL: {current_url}")

        return True

    except Exception as e:
        logger.error(f"Reddit: Publish error for {account.name}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

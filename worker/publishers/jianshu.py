from __future__ import annotations

import asyncio
import logging
import markdown
import os
from typing import Optional

from playwright.async_api import Page

logger = logging.getLogger("video_publisher")

JIANSHU_WRITER_URL = "https://www.jianshu.com/writer"

async def _log_page_state(page: Page, step: str):
    try:
        url = page.url
        title = await page.title()
        logger.info(f"Jianshu [{step}] URL: {url}, Title: {title}")
    except Exception as e:
        logger.error(f"Jianshu [{step}] Failed to log page state: {e}")

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
        logger.info(f"Jianshu: === START publish for {account.name} (id={account.id}) ===")
        logger.info(f"Jianshu: Title={title}, Desc length={len(description) if description else 0}")

        if not description:
            logger.error("Jianshu: No article content provided")
            return False

        # Step 0: Navigate to writer page
        logger.info("Jianshu: Step 0 - Navigating to writer page...")
        try:
            await page.goto(JIANSHU_WRITER_URL, wait_until="networkidle", timeout=60000)
        except Exception as e:
            logger.warning(f"Jianshu: networkidle timeout: {e}")
            try:
                await page.goto(JIANSHU_WRITER_URL, wait_until="domcontentloaded", timeout=30000)
            except Exception as e2:
                logger.error(f"Jianshu: page.goto failed: {e2}")
                return False

        await asyncio.sleep(5)
        await _log_page_state(page, "after_goto")

        # Check login
        current_url = page.url
        if "login" in current_url.lower() or "sign_in" in current_url.lower():
            logger.error(f"Jianshu: Session expired! Redirected to: {current_url}")
            return False

        # Step 1: Click "新建文章" to create a NEW article
        # DOM: <div class="_1GsW5"><span>新建文章</span></div> at top-right of left panel
        # Also exists: "新建文集" (left sidebar) and "在下方新建文章" (bottom) - must avoid those
        logger.info("Jianshu: Step 1 - Creating new article...")
        new_article_created = False

        # Strategy 1: Click div._1GsW5 (the wrapper around "新建文章" span)
        try:
            new_article_div = page.locator('div._1GsW5').first
            if await new_article_div.is_visible(timeout=5000):
                await new_article_div.click()
                await asyncio.sleep(3)
                logger.info("Jianshu: Clicked 'div._1GsW5' (新建文章 container)")
                new_article_created = True
        except Exception as e:
            logger.warning(f"Jianshu: Strategy 1 (div._1GsW5) failed: {e}")

        # Strategy 2: JS - find span with exact text "新建文章" and click its parent
        if not new_article_created:
            try:
                clicked = await page.evaluate("""() => {
                    const spans = document.querySelectorAll('span');
                    for (const span of spans) {
                        if (span.textContent.trim() === '新建文章') {
                            if (span.parentElement) {
                                span.parentElement.click();
                                return 'parent-clicked';
                            }
                            span.click();
                            return 'span-clicked';
                        }
                    }
                    return false;
                }""")
                if clicked:
                    logger.info(f"Jianshu: Clicked '新建文章' via JS: {clicked}")
                    await asyncio.sleep(3)
                    new_article_created = True
            except Exception as e:
                logger.warning(f"Jianshu: Strategy 2 (JS span click) failed: {e}")

        # Strategy 3: get_by_text exact match
        if not new_article_created:
            try:
                new_article_btn = page.get_by_text("新建文章", exact=True).first
                if await new_article_btn.is_visible(timeout=3000):
                    await new_article_btn.click()
                    await asyncio.sleep(3)
                    logger.info("Jianshu: Clicked '新建文章' via get_by_text(exact)")
                    new_article_created = True
            except Exception as e:
                logger.warning(f"Jianshu: Strategy 3 (get_by_text exact) failed: {e}")

        if new_article_created:
            await asyncio.sleep(2)
            try:
                title_val = await page.evaluate("""() => {
                    const inputs = document.querySelectorAll('input[type="text"]');
                    for (const input of inputs) {
                        const rect = input.getBoundingClientRect();
                        if (rect.width > 300 && rect.y < 100) return input.value;
                    }
                    return '';
                }""")
                if title_val:
                    logger.warning(f"Jianshu: Title input not empty after new article: '{title_val}'")
                else:
                    logger.info("Jianshu: New article created, title input is empty")
            except Exception:
                pass
        else:
            logger.warning("Jianshu: Could not find '新建文章' button, continuing anyway")

        # Step 2: Fill title
        # Title input: <input type="text" class="_24i7u"> at rect x=583 y=20 w=817 h=44
        logger.info("Jianshu: Step 2 - Filling title...")
        if title:
            title_filled = False

            # Strategy 1: Find by class pattern
            try:
                title_input = page.locator('input[class*="24i7u"]').first
                if await title_input.is_visible(timeout=5000):
                    await title_input.click()
                    await asyncio.sleep(0.3)
                    await title_input.fill("")
                    await asyncio.sleep(0.2)
                    await title_input.fill(title)
                    await asyncio.sleep(0.5)
                    val = await title_input.input_value()
                    if val and len(val) > 0:
                        logger.info(f"Jianshu: Title filled via class selector ({len(val)} chars)")
                        title_filled = True
            except Exception as e:
                logger.warning(f"Jianshu: Title fill via class selector failed: {e}")

            # Strategy 2: JS nativeSetter on large input at top
            if not title_filled:
                try:
                    title_filled = await page.evaluate("""(title) => {
                        const inputs = document.querySelectorAll('input[type="text"]');
                        for (const input of inputs) {
                            const rect = input.getBoundingClientRect();
                            if (rect.width > 300 && rect.y < 100 && input.offsetParent !== null) {
                                const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                                nativeSetter.call(input, title);
                                input.dispatchEvent(new Event('input', { bubbles: true }));
                                input.dispatchEvent(new Event('change', { bubbles: true }));
                                return input.value.length > 0;
                            }
                        }
                        return false;
                    }""", title)
                    if title_filled:
                        logger.info("Jianshu: Title filled via JS nativeSetter")
                except Exception as e:
                    logger.warning(f"Jianshu: Title JS fill failed: {e}")

            # Strategy 3: Find by bounding box
            if not title_filled:
                try:
                    inputs = page.locator('input[type="text"]')
                    count = await inputs.count()
                    for i in range(count):
                        inp = inputs.nth(i)
                        if await inp.is_visible():
                            box = await inp.bounding_box()
                            if box and box['width'] > 300 and box['y'] < 150:
                                await inp.click()
                                await asyncio.sleep(0.2)
                                await inp.fill("")
                                await asyncio.sleep(0.2)
                                await inp.fill(title)
                                val = await inp.input_value()
                                if val and len(val) > 0:
                                    logger.info(f"Jianshu: Title filled via bounding box ({len(val)} chars)")
                                    title_filled = True
                                break
                except Exception as e:
                    logger.warning(f"Jianshu: Title fill via bounding box failed: {e}")

            if not title_filled:
                logger.error("Jianshu: Title fill FAILED")

        # Step 3: Fill content
        # Editor: <div class="kalamu-area" contenteditable="true"> at rect x=583 y=104 w=817 h=795
        # IMPORTANT: innerHTML injection doesn't update Jianshu's word count ("字数:0"),
        # which means the editor's internal model doesn't register the content.
        # We must use Playwright's type() to simulate real keyboard input for reliable content fill.
        logger.info("Jianshu: Step 3 - Filling content...")
        if description:
            content_filled = False

            # Convert markdown to plain text for keyboard input, but also prepare HTML for innerHTML fallback
            html_content = markdown.markdown(
                description,
                extensions=['extra', 'nl2br', 'sane_lists'],
            )
            logger.info(f"Jianshu: Converted markdown to HTML ({len(html_content)} chars)")

            # Strategy A: Playwright type() into contenteditable - most reliable for React-based editors
            try:
                editor = page.locator('div.kalamu-area[contenteditable="true"]')
                if await editor.is_visible(timeout=5000):
                    await editor.click()
                    await asyncio.sleep(0.5)

                    # Select all existing content and delete it
                    await page.keyboard.press("Control+a")
                    await asyncio.sleep(0.2)
                    await page.keyboard.press("Backspace")
                    await asyncio.sleep(0.3)

                    # Type the content character by character
                    # Use the plain text from description (strip markdown but keep line breaks)
                    plain_text = description
                    await page.keyboard.type(plain_text, delay=5)
                    await asyncio.sleep(1)

                    # Verify content was entered
                    content_len = await editor.evaluate("el => el.innerText.length")
                    if content_len and content_len > 0:
                        logger.info(f"Jianshu: Strategy A SUCCESS - keyboard type ({content_len} chars)")
                        content_filled = True
                    else:
                        logger.warning(f"Jianshu: Strategy A type() returned content_len={content_len}")
            except Exception as e:
                logger.warning(f"Jianshu: Strategy A (keyboard type) failed: {e}")

            # Strategy B: innerHTML into div.kalamu-area + dispatch proper events
            if not content_filled:
                try:
                    result = await page.evaluate("""(html) => {
                        const editor = document.querySelector('div.kalamu-area[contenteditable="true"]');
                        if (editor) {
                            editor.focus();
                            editor.innerHTML = html;
                            // Dispatch comprehensive events to notify React
                            editor.dispatchEvent(new Event('input', { bubbles: true }));
                            editor.dispatchEvent(new Event('change', { bubbles: true }));
                            editor.dispatchEvent(new Event('blur', { bubbles: true }));
                            editor.dispatchEvent(new Event('focus', { bubbles: true }));
                            // Keyboard event to trigger model update
                            editor.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: ' ' }));
                            return editor.innerText.length;
                        }
                        return 0;
                    }""", html_content)
                    if result and result > 0:
                        logger.info(f"Jianshu: Strategy B SUCCESS - innerHTML + events ({result} chars)")
                        content_filled = True
                    else:
                        logger.warning(f"Jianshu: Strategy B returned {result}")
                except Exception as e:
                    logger.warning(f"Jianshu: Strategy B failed: {e}")

            # Strategy C: Generic contenteditable fallback
            if not content_filled:
                try:
                    result = await page.evaluate("""(html) => {
                        const editors = document.querySelectorAll('[contenteditable="true"]');
                        for (const editor of editors) {
                            if (editor.offsetParent !== null && editor.getBoundingClientRect().height > 200) {
                                editor.focus();
                                editor.innerHTML = html;
                                editor.dispatchEvent(new Event('input', { bubbles: true }));
                                editor.dispatchEvent(new Event('change', { bubbles: true }));
                                editor.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: ' ' }));
                                return editor.innerText.length;
                            }
                        }
                        return 0;
                    }""", html_content)
                    if result and result > 0:
                        logger.info(f"Jianshu: Strategy C SUCCESS - generic contenteditable ({result} chars)")
                        content_filled = True
                    else:
                        logger.warning(f"Jianshu: Strategy C returned {result}")
                except Exception as e:
                    logger.warning(f"Jianshu: Strategy C failed: {e}")

            if not content_filled:
                logger.error("Jianshu: ALL content fill strategies FAILED!")

        # Verify content and word count
        try:
            verify = await page.evaluate("""() => {
                const editor = document.querySelector('div.kalamu-area[contenteditable="true"]')
                    || document.querySelector('#editor')
                    || document.querySelector('[contenteditable="true"]');
                const wordCountEl = document.querySelector('._29C-V');
                return {
                    contentLen: editor ? editor.innerText.length : 0,
                    wordCount: wordCountEl ? wordCountEl.textContent : 'not found',
                };
            }""")
            logger.info(f"Jianshu: Content verification: {verify.get('contentLen', 0)} chars, word count: {verify.get('wordCount', 'N/A')}")
        except Exception as e:
            logger.warning(f"Jianshu: Content verification failed: {e}")

        await before_submit()
        # Step 4: Click "发布文章" button
        # DOM: <li class="tGbI7 cztJE"><a>发布文章</a></li> at top-right toolbar (rect x=1290 y=64)
        # There's also a toolbar: H1, —, Σ, save icon, fullscreen icon, 发布文章
        logger.info("Jianshu: Step 4 - Clicking publish button...")
        await asyncio.sleep(2)

        published = False

        # Strategy 1: Click <li> containing exact "发布文章" text
        try:
            pub_li = page.locator('li:has-text("发布文章")').first
            if await pub_li.is_visible(timeout=5000):
                await pub_li.click()
                await asyncio.sleep(3)
                logger.info("Jianshu: Clicked '发布文章' via li locator")
                published = True
        except Exception as e:
            logger.warning(f"Jianshu: Strategy 1 (li:has-text) failed: {e}")

        # Strategy 2: Click <a> with exact text "发布文章"
        if not published:
            try:
                pub_link = page.get_by_text("发布文章", exact=True).first
                if await pub_link.is_visible(timeout=3000):
                    await pub_link.click()
                    await asyncio.sleep(3)
                    logger.info("Jianshu: Clicked '发布文章' via get_by_text")
                    published = True
            except Exception as e:
                logger.warning(f"Jianshu: Strategy 2 (get_by_text) failed: {e}")

        # Strategy 3: JS click - find element with exact "发布文章" text
        if not published:
            try:
                result = await page.evaluate("""() => {
                    // First try <li> elements (most specific based on diagnostic)
                    const lis = document.querySelectorAll('li');
                    for (const li of lis) {
                        if (li.textContent.trim() === '发布文章' && li.offsetParent !== null) {
                            li.click();
                            return 'li-clicked';
                        }
                    }
                    // Then try <a> elements
                    const links = document.querySelectorAll('a');
                    for (const a of links) {
                        if (a.textContent.trim() === '发布文章' && a.offsetParent !== null) {
                            a.click();
                            return 'a-clicked';
                        }
                    }
                    // Generic fallback
                    const all = document.querySelectorAll('*');
                    for (const el of all) {
                        if (el.textContent.trim() === '发布文章' 
                            && el.offsetParent !== null 
                            && el.getBoundingClientRect().width > 0
                            && el.getBoundingClientRect().width < 200) {
                            el.click();
                            return el.tagName.toLowerCase() + '-clicked';
                        }
                    }
                    return false;
                }""")
                if result:
                    logger.info(f"Jianshu: Clicked '发布文章' via JS: {result}")
                    await asyncio.sleep(3)
                    published = True
            except Exception as e:
                logger.warning(f"Jianshu: Strategy 3 (JS click) failed: {e}")

        # Strategy 4: Broader search for any "发布" button
        if not published:
            try:
                for btn_text in ["发布"]:
                    btn = page.get_by_text(btn_text, exact=True).first
                    if await btn.is_visible(timeout=3000):
                        await btn.scroll_into_view_if_needed()
                        await asyncio.sleep(0.5)
                        await btn.click(force=True)
                        published = True
                        logger.info(f"Jianshu: Clicked '{btn_text}' via get_by_text")
                        break
            except Exception:
                pass

        if not published:
            logger.error("Jianshu: Publish button not found after all attempts!")
            return False

        await asyncio.sleep(5)
        await _log_page_state(page, "after_publish_click")

        # Step 5: Check for publish confirmation dialog or success
        # Jianshu may show a confirmation dialog after clicking "发布文章"
        # or may show "已保存" status
        logger.info("Jianshu: Step 5 - Checking publish result...")
        await asyncio.sleep(3)

        # Check if a confirmation dialog appeared
        dialog_result = await page.evaluate("""() => {
            const results = {};
            
            // Check for modal/dialog
            const modals = document.querySelectorAll('[class*="modal"], [role="dialog"], [class*="dialog"], [class*="popup"]');
            for (const m of modals) {
                const style = window.getComputedStyle(m);
                if (style.display !== 'none' && style.visibility !== 'hidden') {
                    results.modal = m.textContent.trim().substring(0, 200);
                }
            }
            
            // Check for "已发布" or success text
            const all = document.querySelectorAll('*');
            for (const el of all) {
                const text = el.textContent.trim();
                if ((text === '已发布' || text.includes('发布成功') || text.includes('审核'))
                    && el.offsetParent !== null && text.length < 30) {
                    results.status = text;
                }
            }
            
            // Check URL for article ID (published article URL pattern)
            results.url = window.location.href;
            
            return results;
        }""")
        logger.info(f"Jianshu: Post-publish dialog check: {dialog_result}")

        # If there's a confirmation dialog, try to click confirm/submit
        if dialog_result.get('modal'):
            logger.info("Jianshu: Confirmation dialog detected, looking for confirm button...")
            confirm_clicked = False

            # Try clicking "确认" or "发布" in the dialog
            for text in ["确认发布", "确认", "发布", "提交"]:
                try:
                    confirm_btn = page.get_by_text(text, exact=True).first
                    if await confirm_btn.is_visible(timeout=2000):
                        await confirm_btn.click()
                        confirm_clicked = True
                        logger.info(f"Jianshu: Clicked '{text}' in dialog")
                        break
                except Exception:
                    pass

            if not confirm_clicked:
                try:
                    confirm_clicked = await page.evaluate("""() => {
                        const buttons = document.querySelectorAll('button, a, [role="button"], div');
                        for (const btn of buttons) {
                            const text = btn.textContent.trim();
                            const rect = btn.getBoundingClientRect();
                            if ((text === '确认' || text === '发布' || text === '提交' || text === '确认发布')
                                && btn.offsetParent !== null && rect.width > 0 && rect.width < 200
                                && rect.x > 400) {
                                btn.click();
                                return text;
                            }
                        }
                        return false;
                    }""")
                    if confirm_clicked:
                        logger.info(f"Jianshu: Clicked '{confirm_clicked}' in dialog via JS")
                except Exception as e:
                    logger.warning(f"Jianshu: Dialog confirm JS failed: {e}")

            await asyncio.sleep(5)

        # Final check: verify published
        final_url = page.url
        final_check = await page.evaluate("""() => {
            const results = {};
            // Check for "已发布" status text
            const all = document.querySelectorAll('*');
            for (const el of all) {
                const text = el.textContent.trim();
                if (text === '已发布' && el.offsetParent !== null && el.getBoundingClientRect().width < 200) {
                    results.published = true;
                    results.statusText = text;
                }
            }
            // Check for error messages
            for (const el of all) {
                const text = el.textContent.trim();
                if ((text.includes('发布失败') || text.includes('频率限制') || text.includes('不能发布'))
                    && el.offsetParent !== null && text.length < 50) {
                    results.error = text;
                }
            }
            return results;
        }""")
        logger.info(f"Jianshu: Final check: url={final_url}, result={final_check}")

        logger.info(f"Jianshu: === Publish COMPLETED for {account.name} ===")
        return True

    except Exception as e:
        logger.error(f"Jianshu: Publish EXCEPTION for {account.name}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

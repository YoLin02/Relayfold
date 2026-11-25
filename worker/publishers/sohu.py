from __future__ import annotations

import asyncio
import logging
import markdown
import os
from typing import Optional

from playwright.async_api import Page

logger = logging.getLogger("video_publisher")

SOHU_EDITOR_URL = "https://mp.sohu.com/mpfe/v4/contentManagement/news/addarticle"
SOHU_MP_URL = "https://mp.sohu.com/"

async def _log_page_state(page: Page, step: str):
    try:
        url = page.url
        title = await page.title()
        logger.info(f"Sohu [{step}] URL: {url}, Title: {title}")
    except Exception as e:
        logger.error(f"Sohu [{step}] Failed to log page state: {e}")

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
        logger.info(f"Sohu: === START publish for {account.name} (id={account.id}) ===")
        logger.info(f"Sohu: Title={title}, Desc length={len(description) if description else 0}")

        if not description:
            logger.error("Sohu: No article content provided")
            return False

        # Step 0: Navigate to editor
        logger.info("Sohu: Step 0 - Navigating to editor page...")
        try:
            await page.goto(SOHU_EDITOR_URL, wait_until="networkidle", timeout=60000)
        except Exception as e:
            logger.warning(f"Sohu: networkidle timeout: {e}")
            try:
                await page.goto(SOHU_EDITOR_URL, wait_until="domcontentloaded", timeout=30000)
            except Exception as e2:
                logger.error(f"Sohu: page.goto failed: {e2}")
                return False

        await asyncio.sleep(8)
        await _log_page_state(page, "after_goto")

        # Check login - if redirected to login page
        current_url = page.url
        if "login" in current_url.lower():
            logger.error(f"Sohu: Session expired! Redirected to: {current_url}")
            return False

        # Step 1: Fill title
        # Title input: <input type="text" placeholder="请输入标题（5-72字）">
        # Parent class: "publish-title", Grandparent class: "editor-main"
        logger.info("Sohu: Step 1 - Filling title...")
        if title:
            title_filled = False

            # Strategy 1: By placeholder text
            try:
                title_input = page.locator('input[placeholder*="标题"]').first
                if await title_input.is_visible(timeout=5000):
                    await title_input.click()
                    await asyncio.sleep(0.3)
                    await title_input.fill("")
                    await asyncio.sleep(0.2)
                    await title_input.fill(title)
                    await asyncio.sleep(0.5)
                    val = await title_input.input_value()
                    if val and len(val) > 0:
                        logger.info(f"Sohu: Title filled via placeholder selector ({len(val)} chars)")
                        title_filled = True
            except Exception as e:
                logger.warning(f"Sohu: Title fill via placeholder failed: {e}")

            # Strategy 2: By parent class "publish-title"
            if not title_filled:
                try:
                    title_input = page.locator('.publish-title input[type="text"]').first
                    if await title_input.is_visible(timeout=3000):
                        await title_input.click()
                        await asyncio.sleep(0.3)
                        await title_input.fill("")
                        await asyncio.sleep(0.2)
                        await title_input.fill(title)
                        val = await title_input.input_value()
                        if val and len(val) > 0:
                            logger.info(f"Sohu: Title filled via .publish-title selector ({len(val)} chars)")
                            title_filled = True
                except Exception as e:
                    logger.warning(f"Sohu: Title fill via .publish-title failed: {e}")

            # Strategy 3: JS fill
            if not title_filled:
                try:
                    title_filled = await page.evaluate("""(title) => {
                        const inputs = document.querySelectorAll('input[type="text"]');
                        for (const input of inputs) {
                            const ph = input.placeholder || '';
                            if (ph.includes('标题') && input.offsetParent !== null) {
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
                        logger.info("Sohu: Title filled via JS")
                except Exception as e:
                    logger.warning(f"Sohu: Title JS fill failed: {e}")

            if not title_filled:
                logger.error("Sohu: Title fill FAILED")

        # Step 2: Fill content via Quill editor
        # Editor: div.ql-editor.ql-blank (contenteditable="true")
        # Container: div#editor.ql-container.ql-snow
        # Quill uses innerHTML injection + Quill API
        logger.info("Sohu: Step 2 - Filling content...")
        if description:
            content_filled = False

            html_content = markdown.markdown(
                description,
                extensions=['extra', 'nl2br', 'sane_lists'],
            )
            logger.info(f"Sohu: Converted markdown to HTML ({len(html_content)} chars)")

            # Strategy A: Use Quill API (most reliable for Quill editors)
            try:
                result = await page.evaluate("""(html) => {
                    // Try Quill instance - it's usually attached to the container
                    const container = document.querySelector('#editor') || document.querySelector('.ql-container');
                    if (container && container.__quill) {
                        container.__quill.clip.dangerouslyPasteHTML(html);
                        return 'quill-api';
                    }
                    // Check Quill on window
                    if (typeof Quill !== 'undefined') {
                        // Find Quill instance
                        const qlEditor = document.querySelector('.ql-editor');
                        if (qlEditor) {
                            // Quill stores its instance on the DOM element sometimes
                            const parent = qlEditor.parentElement;
                            if (parent && parent.__quill) {
                                parent.__quill.clip.dangerouslyPasteHTML(html);
                                return 'quill-parent-api';
                            }
                        }
                    }
                    return false;
                }""", html_content)
                if result:
                    logger.info(f"Sohu: Strategy A SUCCESS - {result}")
                    await asyncio.sleep(2)
                    content_filled = True
                else:
                    logger.warning("Sohu: Strategy A - no Quill API instance found")
            except Exception as e:
                logger.warning(f"Sohu: Strategy A (Quill API) failed: {e}")

            # Strategy B: innerHTML into .ql-editor
            if not content_filled:
                try:
                    result = await page.evaluate("""(html) => {
                        const editor = document.querySelector('.ql-editor');
                        if (editor) {
                            editor.innerHTML = html;
                            // Dispatch input event to notify Quill
                            editor.dispatchEvent(new Event('input', { bubbles: true }));
                            editor.dispatchEvent(new Event('change', { bubbles: true }));
                            // Also trigger Quill's text-change
                            editor.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: ' ' }));
                            return editor.innerText.length;
                        }
                        return 0;
                    }""", html_content)
                    if result and result > 0:
                        logger.info(f"Sohu: Strategy B SUCCESS - innerHTML into .ql-editor ({result} chars)")
                        content_filled = True
                    else:
                        logger.warning(f"Sohu: Strategy B returned {result}")
                except Exception as e:
                    logger.warning(f"Sohu: Strategy B (innerHTML) failed: {e}")

            # Strategy C: Playwright type into contenteditable
            if not content_filled:
                try:
                    ql_editor = page.locator('.ql-editor')
                    if await ql_editor.is_visible(timeout=5000):
                        await ql_editor.click()
                        await asyncio.sleep(0.3)
                        await page.keyboard.press("Control+a")
                        await asyncio.sleep(0.2)
                        # Type plain text content
                        plain_text = description
                        await page.keyboard.type(plain_text, delay=3)
                        await asyncio.sleep(1)
                        content_len = await ql_editor.evaluate("el => el.innerText.length")
                        if content_len and content_len > 0:
                            logger.info(f"Sohu: Strategy C SUCCESS - keyboard type ({content_len} chars)")
                            content_filled = True
                except Exception as e:
                    logger.warning(f"Sohu: Strategy C (keyboard type) failed: {e}")

            if not content_filled:
                logger.error("Sohu: ALL content fill strategies FAILED!")

        # Verify content
        try:
            content_verify = await page.evaluate("""() => {
                const editor = document.querySelector('.ql-editor');
                return editor ? editor.innerText.length : 0;
            }""")
            logger.info(f"Sohu: Content verification: {content_verify} chars")
        except Exception as e:
            logger.warning(f"Sohu: Content verification failed: {e}")

        # Step 2.5: 选择创作声明"无需声明"
        # 创作声明 radio 位于正文下方、默认未选中，需滚动到可见并点击选中
        logger.info("Sohu: Step 2.5 - Selecting creation declaration '无需声明'...")
        try:
            decl_label = page.locator('label[role="radio"].el-radio:has-text("无需声明")').first
            await decl_label.scroll_into_view_if_needed(timeout=5000)
            await asyncio.sleep(0.3)
            await decl_label.click(timeout=5000)
            await asyncio.sleep(0.5)

            # 验证选中态：label 带 is-checked class 或 aria-checked="true"
            checked = await decl_label.evaluate(
                "el => el.classList.contains('is-checked') || el.getAttribute('aria-checked') === 'true'"
            )
            if checked:
                logger.info("Sohu: 创作声明 '无需声明' selected")
            else:
                logger.warning("Sohu: 创作声明 '无需声明' NOT selected, retrying once...")
                await decl_label.click(timeout=5000)
                await asyncio.sleep(0.5)
                checked = await decl_label.evaluate(
                    "el => el.classList.contains('is-checked') || el.getAttribute('aria-checked') === 'true'"
                )
                if checked:
                    logger.info("Sohu: 创作声明 '无需声明' selected (retry)")
                else:
                    logger.warning("Sohu: 创作声明 '无需声明' still NOT selected")
        except Exception as e:
            logger.warning(f"Sohu: Declaration selection failed (non-fatal): {e}")

        await before_submit()
        # Step 3: Click "发布" button
        # Publish button: <li class="publish-report-btn active positive-butto">发布</li>
        # Also: 定时发布, 存草稿, 预览
        logger.info("Sohu: Step 4 - Clicking publish button...")
        await asyncio.sleep(2)

        published = False

        # Strategy 1: Click li.publish-report-btn with text "发布"
        try:
            pub_btn = page.locator('li.publish-report-btn.positive-butto, li.publish-report-btn.active').first
            if await pub_btn.is_visible(timeout=5000):
                await pub_btn.click()
                published = True
                logger.info("Sohu: Clicked publish via li.publish-report-btn")
        except Exception as e:
            logger.warning(f"Sohu: Strategy 1 (li.publish-report-btn) failed: {e}")

        # Strategy 2: get_by_text exact match "发布"
        if not published:
            try:
                pub_btn = page.get_by_text("发布", exact=True).first
                if await pub_btn.is_visible(timeout=3000):
                    await pub_btn.click()
                    published = True
                    logger.info("Sohu: Clicked '发布' via get_by_text(exact)")
            except Exception as e:
                logger.warning(f"Sohu: Strategy 2 (get_by_text) failed: {e}")

        # Strategy 3: JS click
        if not published:
            try:
                result = await page.evaluate("""() => {
                    const lis = document.querySelectorAll('li');
                    for (const li of lis) {
                        if (li.textContent.trim() === '发布' && li.offsetParent !== null) {
                            li.click();
                            return 'li-clicked';
                        }
                    }
                    const all = document.querySelectorAll('button, a, span, div');
                    for (const el of all) {
                        if (el.textContent.trim() === '发布' && el.offsetParent !== null
                            && el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().width < 200) {
                            el.click();
                            return el.tagName.toLowerCase() + '-clicked';
                        }
                    }
                    return false;
                }""")
                if result:
                    logger.info(f"Sohu: Clicked '发布' via JS: {result}")
                    published = True
            except Exception as e:
                logger.warning(f"Sohu: Strategy 3 (JS click) failed: {e}")

        if not published:
            logger.error("Sohu: Publish button not found after all attempts!")
            return False

        await asyncio.sleep(5)
        await _log_page_state(page, "after_publish_click")

        # Step 5: Check for confirmation dialog or success
        logger.info("Sohu: Step 5 - Checking publish result...")
        await asyncio.sleep(3)

        # Check for dialogs/modals
        dialog_check = await page.evaluate("""() => {
            const results = {};
            results.url = window.location.href;
            
            // Check for el-message or el-dialog (Sohu uses Element UI)
            const dialogs = document.querySelectorAll('.el-message-box, .el-dialog, [class*="modal"], [role="dialog"]');
            for (const d of dialogs) {
                const style = window.getComputedStyle(d);
                if (style.display !== 'none' && style.visibility !== 'hidden') {
                    results.dialog = d.textContent.trim().substring(0, 300);
                }
            }
            
            // Check for success/error messages
            const msgs = document.querySelectorAll('.el-message, [class*="success"], [class*="error"]');
            for (const m of msgs) {
                if (m.offsetParent !== null && m.textContent.trim().length < 100 && m.textContent.trim().length > 0) {
                    results.message = m.textContent.trim();
                }
            }
            
            return results;
        }""")
        logger.info(f"Sohu: Post-publish check: {dialog_check}")

        # Handle dialog if present
        if dialog_check.get('dialog'):
            logger.info("Sohu: Dialog detected, attempting to confirm...")
            for text in ["确定", "确认", "发布", "OK"]:
                try:
                    btn = page.get_by_text(text, exact=True).first
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        logger.info(f"Sohu: Clicked '{text}' in dialog")
                        break
                except Exception:
                    pass
            await asyncio.sleep(5)

        # Final URL check
        final_url = page.url
        logger.info(f"Sohu: Final URL: {final_url}")

        logger.info(f"Sohu: === Publish COMPLETED for {account.name} ===")
        return True

    except Exception as e:
        logger.error(f"Sohu: Publish EXCEPTION for {account.name}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

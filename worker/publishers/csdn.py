from __future__ import annotations

import asyncio
import logging
import markdown
import os
from typing import Optional

from playwright.async_api import Page

logger = logging.getLogger("video_publisher")

CSDN_EDITOR_URL = "https://mp.csdn.net/mp_blog/creation/editor"
CSDN_HOME_URL = "https://www.csdn.net/"

async def _log_page_state(page: Page, step: str):
    try:
        url = page.url
        title = await page.title()
        logger.info(f"CSDN [{step}] URL: {url}, Title: {title}")
    except Exception as e:
        logger.error(f"CSDN [{step}] Failed to log page state: {e}")

async def publish(
    page: Page,
    account,
    media_paths: list[str],
    title: Optional[str],
    description: Optional[str],
    keywords: str = '',
    *,
    before_submit,
) -> bool:
    try:
        logger.info(f"CSDN: === START publish for {account.name} (id={account.id}) ===")
        logger.info(f"CSDN: Title={title}, Desc length={len(description) if description else 0}")

        if not description:
            logger.error("CSDN: No article content provided")
            return False

        # Step 0: Navigate to editor
        logger.info("CSDN: Step 0 - Navigating to editor page...")
        try:
            await page.goto(CSDN_EDITOR_URL, wait_until="networkidle", timeout=60000)
        except Exception as e:
            logger.warning(f"CSDN: networkidle timeout: {e}")
            try:
                await page.goto(CSDN_EDITOR_URL, wait_until="domcontentloaded", timeout=30000)
            except Exception as e2:
                logger.error(f"CSDN: page.goto failed: {e2}")
                return False

        await asyncio.sleep(8)
        await _log_page_state(page, "after_goto")

        # Check login
        current_url = page.url
        if "login" in current_url.lower() or "passport" in current_url.lower():
            logger.error(f"CSDN: Session expired! Redirected to: {current_url}")
            return False

        # Step 1: Fill title - CSDN uses <textarea id="txtTitle">
        logger.info("CSDN: Step 1 - Filling title...")
        if title:
            title_filled = False

            # Strategy 1: #txtTitle textarea
            try:
                title_textarea = page.locator('#txtTitle')
                if await title_textarea.is_visible(timeout=10000):
                    await title_textarea.click()
                    await asyncio.sleep(0.3)
                    await title_textarea.fill("")
                    await asyncio.sleep(0.2)
                    await title_textarea.fill(title)
                    await asyncio.sleep(0.5)
                    val = await title_textarea.input_value()
                    if val and len(val) > 0:
                        logger.info(f"CSDN: Title filled via #txtTitle ({len(val)} chars)")
                        title_filled = True
            except Exception as e:
                logger.warning(f"CSDN: #txtTitle fill failed: {e}")

            # Strategy 2: JS nativeSetter on textarea
            if not title_filled:
                try:
                    title_filled = await page.evaluate("""(title) => {
                        const ta = document.getElementById('txtTitle');
                        if (ta) {
                            ta.focus();
                            const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                            nativeSetter.call(ta, title);
                            ta.dispatchEvent(new Event('input', { bubbles: true }));
                            ta.dispatchEvent(new Event('change', { bubbles: true }));
                            return ta.value.length > 0;
                        }
                        return false;
                    }""", title)
                    if title_filled:
                        logger.info("CSDN: Title filled via JS nativeSetter")
                except Exception as e:
                    logger.warning(f"CSDN: JS title fill failed: {e}")

            if not title_filled:
                logger.error("CSDN: Title fill FAILED")

        # Step 2: Fill content - CSDN uses CKEditor inside an iframe
        # Key discovery: The iframe is in #cke_1_contents, with class "cke_wysiwyg_frame cke_reset"
        # The iframe body has contentEditable="true"
        # Also: CKEDITOR.instances exists in the main page
        logger.info("CSDN: Step 2 - Filling content via CKEditor iframe...")
        if description:
            content_filled = False

            html_content = markdown.markdown(
                description,
                extensions=['extra', 'nl2br', 'sane_lists'],
            )
            logger.info(f"CSDN: Converted markdown to HTML ({len(html_content)} chars)")

            # Strategy A: Use CKEditor API in main page (most reliable)
            try:
                result = await page.evaluate("""(html) => {
                    if (window.CKEDITOR && window.CKEDITOR.instances) {
                        for (const name in window.CKEDITOR.instances) {
                            const editor = window.CKEDITOR.instances[name];
                            editor.setData(html);
                            return 'ckeditor-api:' + name;
                        }
                    }
                    return false;
                }""", html_content)
                if result:
                    logger.info(f"CSDN: Strategy A SUCCESS - {result}")
                    await asyncio.sleep(2)
                    # Verify content
                    verify = await page.evaluate("""() => {
                        if (window.CKEDITOR && window.CKEDITOR.instances) {
                            for (const name in window.CKEDITOR.instances) {
                                const editor = window.CKEDITOR.instances[name];
                                const data = editor.getData();
                                return data.length;
                            }
                        }
                        return 0;
                    }""")
                    logger.info(f"CSDN: CKEditor API verification: {verify} chars")
                    if verify and verify > 0:
                        content_filled = True
                    else:
                        logger.warning(f"CSDN: CKEditor API setData returned 0 length")
            except Exception as e:
                logger.warning(f"CSDN: Strategy A (CKEditor API) failed: {e}")

            # Strategy B: Access CKEditor iframe and inject HTML into body
            if not content_filled:
                try:
                    # Find the CKEditor content iframe
                    ckeditor_frame = None
                    for frame in page.frames:
                        frame_url = frame.url or ""
                        # The CKEditor content iframe src matches the editor URL
                        if "mp_blog/creation/editor" in frame_url and frame != page.main_frame:
                            ckeditor_frame = frame
                            logger.info(f"CSDN: Found CKEditor iframe: {frame_url[:80]}")
                            break
                    
                    # Also try via frame_locator
                    if not ckeditor_frame:
                        try:
                            fl = page.frame_locator('#cke_1_contents iframe')
                            # Test access by getting body text
                            body_el = fl.locator('body')
                            _ = await body_el.inner_text(timeout=3000)
                            # If we get here, the frame is accessible - get the Frame object
                            logger.info("CSDN: Frame locator works for #cke_1_contents iframe")
                            # We need the Frame object for evaluate, so look again
                            for frame in page.frames:
                                if frame != page.main_frame and "about:blank" in (frame.url or ""):
                                    # The CKEditor iframe might have about:blank as src
                                    ckeditor_frame = frame
                                    break
                        except Exception as fl_err:
                            logger.warning(f"CSDN: Frame locator approach failed: {fl_err}")

                    # Try all non-main frames
                    if not ckeditor_frame:
                        for frame in page.frames:
                            if frame != page.main_frame:
                                try:
                                    ce_count = await frame.evaluate("() => document.querySelectorAll('[contenteditable=\"true\"]').length")
                                    if ce_count > 0 or (await frame.evaluate("() => document.body ? document.body.contentEditable : 'false'")) == "true":
                                        ckeditor_frame = frame
                                        logger.info(f"CSDN: Found content iframe by contentEditable: {frame.url[:80]}")
                                        break
                                except Exception:
                                    continue

                    if ckeditor_frame:
                        # Wait for body
                        try:
                            await ckeditor_frame.wait_for_selector('body', timeout=5000)
                        except Exception:
                            pass

                        # B1: innerHTML injection
                        try:
                            result = await ckeditor_frame.evaluate("""(html) => {
                                const body = document.body;
                                if (body) {
                                    body.innerHTML = html;
                                    body.dispatchEvent(new Event('input', { bubbles: true }));
                                    body.dispatchEvent(new Event('change', { bubbles: true }));
                                    return body.innerText.length;
                                }
                                return 0;
                            }""", html_content)
                            if result and result > 0:
                                logger.info(f"CSDN: Strategy B1 SUCCESS - iframe innerHTML ({result} chars)")
                                content_filled = True
                            else:
                                logger.warning(f"CSDN: Strategy B1 returned {result}")
                        except Exception as e:
                            logger.warning(f"CSDN: Strategy B1 (iframe innerHTML) failed: {e}")

                        # B2: execCommand insertHTML
                        if not content_filled:
                            try:
                                await ckeditor_frame.evaluate("() => { document.body.focus(); }")
                                await asyncio.sleep(0.5)
                                await ckeditor_frame.evaluate("() => { document.execCommand('selectAll', false, null); }")
                                await asyncio.sleep(0.2)
                                insert_ok = await ckeditor_frame.evaluate("(html) => document.execCommand('insertHTML', false, html)", html_content)
                                await asyncio.sleep(2)
                                content_len = await ckeditor_frame.evaluate("() => document.body ? document.body.innerText.length : 0")
                                if content_len and content_len > 0:
                                    logger.info(f"CSDN: Strategy B2 SUCCESS - execCommand insertHTML ({content_len} chars)")
                                    content_filled = True
                                else:
                                    logger.warning(f"CSDN: Strategy B2 - insertHTML returned {insert_ok}, body len={content_len}")
                            except Exception as e:
                                logger.warning(f"CSDN: Strategy B2 (execCommand) failed: {e}")

                        # B3: Playwright locator approach via frame_locator
                        if not content_filled:
                            try:
                                fl = page.frame_locator('#cke_1_contents iframe')
                                body_el = fl.locator('body')
                                await body_el.click()
                                await asyncio.sleep(0.3)
                                await page.keyboard.press("Control+a")
                                await asyncio.sleep(0.2)
                                await page.keyboard.press("Backspace")
                                await asyncio.sleep(0.3)
                                # Type content as plain text
                                plain_text = description
                                await page.keyboard.type(plain_text, delay=2)
                                await asyncio.sleep(2)
                                # Verify
                                body_text = await body_el.inner_text(timeout=5000)
                                if len(body_text) > 0:
                                    logger.info(f"CSDN: Strategy B3 SUCCESS - keyboard type ({len(body_text)} chars)")
                                    content_filled = True
                            except Exception as e:
                                logger.warning(f"CSDN: Strategy B3 (keyboard type via frame_locator) failed: {e}")
                    else:
                        logger.warning("CSDN: Could not find CKEditor iframe!")

                except Exception as e:
                    logger.warning(f"CSDN: Strategy B (iframe) failed: {e}")

            # Strategy C: Direct CKEditor setData from iframe context (check if CKEditor is in iframe)
            if not content_filled:
                try:
                    for frame in page.frames:
                        if frame != page.main_frame:
                            try:
                                result = await frame.evaluate("""(html) => {
                                    if (window.CKEDITOR && window.CKEDITOR.instances) {
                                        for (const name in window.CKEDITOR.instances) {
                                            window.CKEDITOR.instances[name].setData(html);
                                            return 'iframe-ckeditor:' + name;
                                        }
                                    }
                                    try {
                                        if (parent && parent.CKEDITOR && parent.CKEDITOR.instances) {
                                            for (const name in parent.CKEDITOR.instances) {
                                                parent.CKEDITOR.instances[name].setData(html);
                                                return 'parent-ckeditor:' + name;
                                            }
                                        }
                                    } catch(e) {}
                                    return false;
                                }""", html_content)
                                if result:
                                    logger.info(f"CSDN: Strategy C SUCCESS - {result}")
                                    await asyncio.sleep(2)
                                    content_filled = True
                                    break
                            except Exception:
                                continue
                except Exception as e:
                    logger.warning(f"CSDN: Strategy C (iframe CKEditor API) failed: {e}")

            if not content_filled:
                logger.error("CSDN: ALL content fill strategies FAILED!")

        # Verify content
        try:
            # Try CKEditor API first
            content_len = await page.evaluate("""() => {
                if (window.CKEDITOR && window.CKEDITOR.instances) {
                    for (const name in window.CKEDITOR.instances) {
                        return window.CKEDITOR.instances[name].getData().length;
                    }
                }
                return 0;
            }""")
            if content_len and content_len > 0:
                logger.info(f"CSDN: Content verification via CKEditor API: {content_len} chars")
            else:
                # Try iframe
                for frame in page.frames:
                    if frame != page.main_frame:
                        try:
                            iframe_len = await frame.evaluate("() => document.body ? document.body.innerText.length : 0")
                            if iframe_len > 0:
                                logger.info(f"CSDN: Content verification in iframe: {iframe_len} chars")
                                break
                        except Exception:
                            continue
        except Exception as e:
            logger.warning(f"CSDN: Content verification failed: {e}")

        # Step 2.5: Fill article tags (keywords)
        if keywords:
            logger.info(f"CSDN: Step 2.5 - Filling tags: {keywords}")
            try:
                # Click the "添加标签" button
                tag_btn = page.locator('span.tag-box button.tag__btn-tag')
                if await tag_btn.is_visible(timeout=5000):
                    await tag_btn.click()
                    await asyncio.sleep(0.5)
                    logger.info("CSDN: Clicked tag button")

                    # Find the tag input and type keywords
                    tag_input = page.get_by_placeholder("请输入文字搜索，Enter键入可添加自定义标签")
                    if await tag_input.is_visible(timeout=3000):
                        await tag_input.click()
                        await asyncio.sleep(0.3)

                        # Input keywords one by one (comma/Chinese comma separated) and press Enter for each
                        import re
                        kw_list = re.split(r'[,，]', keywords)
                        for kw in kw_list:
                            kw = kw.strip()
                            if kw:
                                await tag_input.fill(kw)
                                await asyncio.sleep(0.3)
                                await page.keyboard.press('Enter')
                                await asyncio.sleep(0.5)
                                logger.info(f"CSDN: Tag added: {kw}")
                    else:
                        logger.warning("CSDN: Tag input not found")
                else:
                    logger.warning("CSDN: Tag button not found")
            except Exception as e:
                logger.warning(f"CSDN: Tag fill failed (non-critical): {e}")

        # Step 3: Select "原创" article type
        logger.info("CSDN: Step 3 - Selecting '原创'...")
        try:
            original_checked = await page.evaluate("""() => {
                const radio = document.querySelector('input[type="radio"][value="original"]');
                if (radio && radio.checked) return true;
                // Click the label/span wrapping the radio
                const label = radio ? radio.closest('label') : null;
                if (label) { label.click(); return 'clicked-label'; }
                if (radio) { radio.click(); return 'clicked-radio'; }
                return false;
            }""")
            logger.info(f"CSDN: '原创' selection: {original_checked}")
        except Exception as e:
            logger.warning(f"CSDN: '原创' selection failed (non-critical): {e}")

        await before_submit()
        # Step 4: Click "发布博客" button
        # From diagnostic: 3 buttons at bottom-right: 保存草稿(x=780), 定时发布(x=912), 发布博客(x=1044)
        # All are <button class="el_mcm-button el_mcm-button--primary is-round ...">
        logger.info("CSDN: Step 4 - Clicking '发布博客' button...")
        await asyncio.sleep(2)

        published = False

        # Strategy 1: Exact text match via get_by_text
        try:
            btn = page.get_by_text("发布博客", exact=True).first
            if await btn.is_visible(timeout=5000):
                await btn.scroll_into_view_if_needed()
                await asyncio.sleep(0.5)
                await btn.click(force=True)
                published = True
                logger.info("CSDN: Clicked '发布博客' via get_by_text(exact)")
        except Exception as e:
            logger.info(f"CSDN: Strategy 1 failed: {e}")

        # Strategy 2: JS click on button with exact text "发布博客"
        if not published:
            try:
                result = await page.evaluate("""() => {
                    const buttons = document.querySelectorAll('button');
                    for (const btn of buttons) {
                        if (btn.textContent.trim() === '发布博客') {
                            btn.scrollIntoView({ behavior: 'instant', block: 'center' });
                            btn.click();
                            return btn.textContent.trim();
                        }
                    }
                    return false;
                }""")
                if result:
                    logger.info(f"CSDN: Clicked '{result}' via JS")
                    published = True
            except Exception as e:
                logger.warning(f"CSDN: Strategy 2 failed: {e}")

        # Strategy 3: Rightmost primary button containing "发布"
        if not published:
            try:
                result = await page.evaluate("""() => {
                    const buttons = document.querySelectorAll('button.el_mcm-button--primary');
                    const publishBtns = [];
                    for (const btn of buttons) {
                        const t = btn.textContent.trim();
                        if (t.includes('发布') && !t.includes('定时') && !t.includes('草稿')) {
                            publishBtns.push({ text: t, x: btn.getBoundingClientRect().x });
                        }
                    }
                    publishBtns.sort((a, b) => b.x - a.x);
                    if (publishBtns.length > 0) {
                        const target = publishBtns[0];
                        const buttons = document.querySelectorAll('button');
                        for (const btn of buttons) {
                            if (btn.textContent.trim() === target.text) {
                                btn.scrollIntoView({ behavior: 'instant', block: 'center' });
                                btn.click();
                                return target.text;
                            }
                        }
                    }
                    return false;
                }""")
                if result:
                    logger.info(f"CSDN: Clicked '{result}' via rightmost-primary strategy")
                    published = True
            except Exception as e:
                logger.warning(f"CSDN: Strategy 3 failed: {e}")

        if not published:
            logger.error("CSDN: '发布博客' button not found after all attempts!")
            return False

        await asyncio.sleep(5)
        await _log_page_state(page, "after_publish")

        # Step 5: Check for publish result / dialog
        logger.info("CSDN: Step 5 - Checking publish result...")
        await asyncio.sleep(3)

        # Check if a dialog appeared (e.g., missing category, tags, etc.)
        dialog_check = await page.evaluate("""() => {
            const results = {};
            // Check for modal/dialog
            const modals = document.querySelectorAll('.el_mcm-message-box, .el_mcm-dialog, [class*="modal"], [role="dialog"]');
            for (const m of modals) {
                const style = window.getComputedStyle(m);
                if (style.display !== 'none' && style.visibility !== 'hidden') {
                    results.modal = m.textContent.trim().substring(0, 300);
                }
            }
            // Check URL change
            results.url = window.location.href;
            // Check for success/error messages
            const msgs = document.querySelectorAll('.el_mcm-message, .el_mcm-notification, [class*="success"], [class*="error"]');
            for (const m of msgs) {
                if (m.offsetParent !== null && m.textContent.trim().length < 100 && m.textContent.trim().length > 0) {
                    results['msg'] = m.textContent.trim();
                }
            }
            return results;
        }""")
        logger.info(f"CSDN: Post-publish check: {dialog_check}")

        # If a dialog appeared, try to handle it
        if dialog_check.get('modal'):
            logger.info("CSDN: Dialog detected, attempting to close/confirm...")
            # Try clicking confirm/ok in the dialog
            for text in ["确定", "确认", "发布", "OK"]:
                try:
                    btn = page.get_by_text(text, exact=True).first
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        logger.info(f"CSDN: Clicked '{text}' in dialog")
                        break
                except Exception:
                    pass

            await asyncio.sleep(5)

        logger.info(f"CSDN: === Publish COMPLETED for {account.name} ===")
        return True

    except Exception as e:
        logger.error(f"CSDN: Publish EXCEPTION for {account.name}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

from __future__ import annotations

import asyncio
import logging
import markdown
import os
from typing import Optional

from playwright.async_api import Page

logger = logging.getLogger("video_publisher")

TOUTIAO_PUBLISH_URL = "https://mp.toutiao.com/profile_v4/graphic/publish"
TOUTIAO_INDEX_URL = "https://mp.toutiao.com/profile_v4/index"

async def _log_page_state(page: Page, step: str):
    try:
        url = page.url
        title = await page.title()
        logger.info(f"Toutiao [{step}] URL: {url}, Title: {title}")
    except Exception as e:
        logger.error(f"Toutiao [{step}] Failed to log page state: {e}")

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
        logger.info(f"Toutiao: === START publish for {account.name} (id={account.id}) ===")
        logger.info(f"Toutiao: Title length={len(title) if title else 0}, Desc length={len(description) if description else 0}")

        if not description:
            logger.error("Toutiao: No article content provided")
            return False

        # Step 0: Navigate
        logger.info("Toutiao: Step 0 - Navigating to publish page...")
        try:
            await page.goto(TOUTIAO_PUBLISH_URL, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            logger.error(f"Toutiao: page.goto failed: {e}")
            await _log_page_state(page, "goto_failed")
            return False

        await asyncio.sleep(5)
        await _log_page_state(page, "after_goto")

        # Check login
        current_url = page.url
        if "login" in current_url.lower() or "passport" in current_url.lower():
            logger.error(f"Toutiao: Session expired! Redirected to: {current_url}")
            return False

        # Step 1: Fill title
        logger.info("Toutiao: Step 1 - Filling title...")
        if title:
            try:
                title_input = page.locator(
                    'input[placeholder*="标题"], input[placeholder*="请输入标题"], textarea[placeholder*="标题"]'
                ).first
                await title_input.wait_for(state="visible", timeout=10000)
                await title_input.click()
                await asyncio.sleep(0.3)
                await title_input.fill(title)
                logger.info(f"Toutiao: Title filled OK ({len(title)} chars)")
            except Exception as e:
                logger.error(f"Toutiao: Title fill FAILED: {e}")
                # Don't return False - continue trying

        # Step 2: Fill content
        logger.info("Toutiao: Step 2 - Filling content...")
        if description:
            try:
                content_editor = page.locator(
                    'div[contenteditable="true"], div.tiger-editor-content, div.ProseMirror'
                ).first
                await content_editor.wait_for(state="visible", timeout=10000)
                await content_editor.click()
                await asyncio.sleep(0.5)

                html_content = markdown.markdown(
                    description,
                    extensions=['extra', 'nl2br', 'sane_lists'],
                )

                await page.evaluate("""(html) => {
                    const editor = document.querySelector('div[contenteditable="true"]')
                        || document.querySelector('div.tiger-editor-content')
                        || document.querySelector('div.ProseMirror');
                    if (editor) {
                        editor.innerHTML = html;
                        editor.dispatchEvent(new Event('input', { bubbles: true }));
                        editor.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }""", html_content)
                logger.info(f"Toutiao: Content injected as HTML ({len(html_content)} chars)")
                await asyncio.sleep(3)

                # Verify content
                content_len = await page.evaluate("""() => {
                    const editor = document.querySelector('div[contenteditable="true"]')
                        || document.querySelector('div.tiger-editor-content')
                        || document.querySelector('div.ProseMirror');
                    return editor ? editor.innerText.length : 0;
                }""")
                logger.info(f"Toutiao: Editor content length: {content_len}")

                if content_len == 0:
                    logger.warning("Toutiao: Content empty after HTML injection, trying paste fallback")
                    try:
                        await content_editor.click()
                        await asyncio.sleep(0.3)
                        await page.keyboard.press("Control+a")
                        await page.keyboard.insert_text(description)
                        await asyncio.sleep(1)
                    except Exception as e2:
                        logger.warning(f"Toutiao: Paste fallback also failed: {e2}")
            except Exception as e:
                logger.error(f"Toutiao: Content fill FAILED: {e}")

        # Step 3: Select "无封面"
        logger.info("Toutiao: Step 3 - Selecting '无封面'...")

        # First, dump all cover-related elements for debugging
        try:
            cover_debug = await page.evaluate("""() => {
                const results = [];
                const all = document.querySelectorAll('*');
                for (const el of all) {
                    const text = el.textContent.trim();
                    if (el.children.length <= 5 && text.includes('封面') && text.length < 30) {
                        const rect = el.getBoundingClientRect();
                        results.push({
                            tag: el.tagName,
                            text: text.substring(0, 50),
                            cls: (el.className || '').toString().substring(0, 80),
                            visible: el.offsetParent !== null,
                            inViewport: rect.top >= 0 && rect.top <= window.innerHeight,
                            rect: { t: Math.round(rect.top), l: Math.round(rect.left), w: Math.round(rect.width), h: Math.round(rect.height) },
                        });
                    }
                }
                // Also check scrollable containers
                const containers = [];
                for (const el of all) {
                    if (el.tagName === 'HTML' || el.tagName === 'BODY') continue;
                    try {
                        const s = window.getComputedStyle(el);
                        if ((s.overflowY === 'auto' || s.overflowY === 'scroll') && el.scrollHeight > el.clientHeight + 50) {
                            containers.push({
                                tag: el.tagName,
                                cls: (el.className || '').toString().substring(0, 60),
                                scrollH: el.scrollHeight,
                                clientH: el.clientHeight,
                            });
                        }
                    } catch(e) {}
                }
                return { elements: results.slice(0, 30), scrollContainers: containers };
            }""")
            logger.info(f"Toutiao: Cover debug - elements: {cover_debug.get('elements', [])}, "
                         f"scrollContainers: {cover_debug.get('scrollContainers', [])}")
        except Exception as e:
            logger.error(f"Toutiao: Cover debug FAILED: {e}")

        cover_selected = False

        # Strategy 1: Use Playwright get_by_text to find and click "无封面", then click its parent
        try:
            no_cover_text = page.get_by_text("无封面", exact=True).first
            if await no_cover_text.is_visible(timeout=5000):
                logger.info("Toutiao: Strategy 1 - Found '无封面' text element, clicking parent...")
                # Click the parent span which contains the radio
                parent = no_cover_text.locator("..")
                await parent.scroll_into_view_if_needed()
                await asyncio.sleep(0.3)
                await parent.click(force=True)
                await asyncio.sleep(1)

                # Verify
                checked = await page.evaluate("""() => {
                    const all = document.querySelectorAll('*');
                    for (const el of all) {
                        if (el.children.length <= 5 && el.textContent.trim() === '无封面') {
                            const p = el.parentElement;
                            if (p) {
                                const inner = p.querySelector('div');
                                if (inner && inner.classList.contains('checked')) return true;
                                if (p.classList.contains('checked') || p.classList.contains('selected')) return true;
                            }
                        }
                    }
                    return false;
                }""")
                if checked:
                    logger.info("Toutiao: Strategy 1 SUCCESS - '无封面' selected via get_by_text + parent click")
                    cover_selected = True
                else:
                    logger.info("Toutiao: Strategy 1 clicked parent but not checked, trying text element click...")
                    await no_cover_text.click(force=True)
                    await asyncio.sleep(1)
                    checked2 = await page.evaluate("""() => {
                        const all = document.querySelectorAll('*');
                        for (const el of all) {
                            if (el.children.length <= 5 && el.textContent.trim() === '无封面') {
                                const p = el.parentElement;
                                if (p) {
                                    const inner = p.querySelector('div');
                                    if (inner && inner.classList.contains('checked')) return true;
                                }
                            }
                        }
                        return false;
                    }""")
                    if checked2:
                        logger.info("Toutiao: Strategy 1b SUCCESS - '无封面' selected via text click")
                        cover_selected = True
            else:
                logger.info("Toutiao: Strategy 1 - '无封面' text not visible (timeout 5s)")
        except Exception as e:
            logger.info(f"Toutiao: Strategy 1 failed: {e}")

        # Strategy 2: JS find "无封面" element, get its coordinates, mouse.click
        if not cover_selected:
            try:
                coords = await page.evaluate("""() => {
                    const all = document.querySelectorAll('*');
                    for (const el of all) {
                        if (el.children.length <= 5 && el.textContent.trim() === '无封面') {
                            // Try clicking the first div child (the radio circle)
                            const parent = el.parentElement;
                            if (parent) {
                                const radioDiv = parent.querySelector('div');
                                if (radioDiv) {
                                    const rect = radioDiv.getBoundingClientRect();
                                    if (rect.width > 0 && rect.height > 0) {
                                        radioDiv.scrollIntoView({ behavior: 'instant', block: 'center' });
                                        return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2, target: 'radio-div' };
                                    }
                                }
                                // Try parent itself
                                const pRect = parent.getBoundingClientRect();
                                if (pRect.width > 0 && pRect.height > 0) {
                                    parent.scrollIntoView({ behavior: 'instant', block: 'center' });
                                    return { x: pRect.x + 15, y: pRect.y + pRect.height / 2, target: 'parent-left' };
                                }
                            }
                            // Try the element itself
                            const rect = el.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                el.scrollIntoView({ behavior: 'instant', block: 'center' });
                                return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2, target: 'self' };
                            }
                        }
                    }
                    return null;
                }""")
                if coords:
                    logger.info(f"Toutiao: Strategy 2 - Found coords: {coords}, clicking...")
                    await asyncio.sleep(0.5)
                    await page.mouse.click(coords['x'], coords['y'])
                    await asyncio.sleep(1)

                    checked = await page.evaluate("""() => {
                        const all = document.querySelectorAll('*');
                        for (const el of all) {
                            if (el.children.length <= 5 && el.textContent.trim() === '无封面') {
                                const p = el.parentElement;
                                if (p) {
                                    const inner = p.querySelector('div');
                                    if (inner && inner.classList.contains('checked')) return true;
                                }
                            }
                        }
                        return false;
                    }""")
                    if checked:
                        logger.info(f"Toutiao: Strategy 2 SUCCESS - mouse.click on {coords.get('target')}")
                        cover_selected = True
                    else:
                        logger.info("Toutiao: Strategy 2 clicked but not checked")
                else:
                    logger.info("Toutiao: Strategy 2 - Could not find '无封面' element with coords")
            except Exception as e:
                logger.info(f"Toutiao: Strategy 2 failed: {e}")

        # Strategy 3: Wait and retry (element might need time to render)
        if not cover_selected:
            logger.info("Toutiao: Strategy 3 - Waiting 5s and retrying...")
            await asyncio.sleep(5)
            try:
                no_cover_text = page.get_by_text("无封面", exact=True).first
                if await no_cover_text.is_visible(timeout=5000):
                    await no_cover_text.scroll_into_view_if_needed()
                    await asyncio.sleep(0.3)
                    await no_cover_text.click(force=True)
                    await asyncio.sleep(1)

                    checked = await page.evaluate("""() => {
                        const all = document.querySelectorAll('*');
                        for (const el of all) {
                            if (el.children.length <= 5 && el.textContent.trim() === '无封面') {
                                const p = el.parentElement;
                                if (p) {
                                    const inner = p.querySelector('div');
                                    if (inner && inner.classList.contains('checked')) return true;
                                }
                            }
                        }
                        return false;
                    }""")
                    if checked:
                        logger.info("Toutiao: Strategy 3 SUCCESS - '无封面' selected after wait+retry")
                        cover_selected = True
                else:
                    logger.info("Toutiao: Strategy 3 - '无封面' still not visible after 5s wait")
            except Exception as e:
                logger.info(f"Toutiao: Strategy 3 failed: {e}")

        if cover_selected:
            logger.info("Toutiao: Cover set to '无封面' ✓")
        else:
            logger.warning("Toutiao: FAILED to select '无封面' - continuing anyway")

        await before_submit()
        # Step 4: Click "预览并发布"
        logger.info("Toutiao: Step 4 - Clicking publish button...")
        await asyncio.sleep(2)

        preview_clicked = False
        for btn_text in ["预览并发布", "预览发布", "发布"]:
            try:
                btn = page.locator(f'button:has-text("{btn_text}")').first
                if await btn.is_visible(timeout=3000):
                    await btn.scroll_into_view_if_needed()
                    await asyncio.sleep(0.5)
                    await btn.click(force=True)
                    preview_clicked = True
                    logger.info(f"Toutiao: Clicked '{btn_text}' button")
                    break
            except Exception:
                pass

        if not preview_clicked:
            # Try JS
            try:
                preview_clicked = await page.evaluate("""() => {
                    const buttons = document.querySelectorAll('button');
                    for (const btn of buttons) {
                        const t = btn.textContent.trim();
                        if (t === '预览并发布' || t === '预览发布' || (t.includes('预览') && t.includes('发布'))) {
                            btn.scrollIntoView({ behavior: 'instant', block: 'center' });
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                }""")
            except Exception:
                pass

        if not preview_clicked:
            logger.info("Toutiao: Publish button not found, waiting 8s...")
            await asyncio.sleep(8)
            for btn_text in ["预览并发布", "预览发布", "发布"]:
                try:
                    btn = page.locator(f'button:has-text("{btn_text}")').first
                    if await btn.is_visible(timeout=3000):
                        await btn.scroll_into_view_if_needed()
                        await asyncio.sleep(0.5)
                        await btn.click(force=True)
                        preview_clicked = True
                        logger.info(f"Toutiao: Clicked '{btn_text}' after extended wait")
                        break
                except Exception:
                    pass

        if not preview_clicked:
            logger.error("Toutiao: '预览并发布' button not found!")
            # Dump all buttons for debugging
            try:
                buttons_info = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('button')).map(b => ({
                        text: b.textContent.trim().substring(0, 50),
                        disabled: b.disabled,
                        visible: b.offsetParent !== null,
                    })).filter(b => b.text);
                }""")
                logger.info(f"Toutiao: All buttons on page: {buttons_info}")
            except Exception:
                pass
            return False

        # Check if preview click triggered a dialog or an error
        await asyncio.sleep(2)
        try:
            page_check = await page.evaluate("""() => {
                // Check for error messages
                const errors = Array.from(document.querySelectorAll(
                    '.error, .alert, .warning, [class*="error"], [class*="Error"], [class*="warning"], [class*="Warning"], [class*="message"], [class*="Message"], [class*="toast"], [class*="Toast"]'
                )).map(e => ({
                    text: e.textContent.trim().substring(0, 100),
                    visible: e.offsetParent !== null,
                })).filter(e => e.visible && e.text.length > 0 && e.text.length < 100);
                // Check for dialog/modal
                const modals = Array.from(document.querySelectorAll(
                    '[role="dialog"], .modal, .dialog, .byte-modal, .ant-modal, [class*="modal"], [class*="Modal"], [class*="dialog"], [class*="Dialog"]'
                )).map(m => ({
                    visible: m.offsetParent !== null,
                    text: m.textContent.trim().substring(0, 200),
                })).filter(m => m.visible);
                // Check current URL
                return { errors: errors.slice(0, 5), modals: modals.slice(0, 3), url: window.location.href };
            }""")
            logger.info(f"Toutiao: After preview click - URL: {page_check.get('url')}, "
                         f"errors: {page_check.get('errors', [])}, modals: {page_check.get('modals', [])}")
        except Exception as e:
            logger.error(f"Toutiao: Page check after preview failed: {e}")

        # Step 5: Click "确认发布" (or whatever the confirm button says)
        logger.info("Toutiao: Step 5 - Waiting for confirm dialog...")
        await asyncio.sleep(3)

        # Dump all visible buttons and dialog elements for debugging
        try:
            dialog_debug = await page.evaluate("""() => {
                const buttons = Array.from(document.querySelectorAll('button')).map(b => ({
                    text: b.textContent.trim().substring(0, 50),
                    disabled: b.disabled,
                    visible: b.offsetParent !== null,
                    cls: (b.className || '').toString().substring(0, 60),
                })).filter(b => b.text && b.visible);
                // Check for dialog/modal
                const modals = Array.from(document.querySelectorAll('[role="dialog"], .modal, .dialog, .byte-modal, .ant-modal')).map(m => ({
                    tag: m.tagName,
                    cls: (m.className || '').toString().substring(0, 60),
                    visible: m.offsetParent !== null,
                    text: m.textContent.trim().substring(0, 100),
                }));
                // Check for error messages
                const errors = Array.from(document.querySelectorAll('.error, .alert, .warning, [class*="error"], [class*="Error"], [class*="warning"], [class*="Warning"]')).map(e => ({
                    tag: e.tagName,
                    cls: (e.className || '').toString().substring(0, 60),
                    text: e.textContent.trim().substring(0, 100),
                    visible: e.offsetParent !== null,
                })).filter(e => e.visible && e.text);
                return { buttons: buttons.slice(0, 20), modals, errors: errors.slice(0, 10) };
            }""")
            logger.info(f"Toutiao: Dialog debug - buttons: {dialog_debug.get('buttons', [])}, "
                         f"modals: {dialog_debug.get('modals', [])}, "
                         f"errors: {dialog_debug.get('errors', [])}")
        except Exception as e:
            logger.error(f"Toutiao: Dialog debug failed: {e}")

        confirmed = False
        for attempt in range(15):
            # Try multiple button texts
            for btn_text in ["确认发布", "确认", "确定", "发布", "提交", "完成"]:
                try:
                    btn = page.locator(f'button:has-text("{btn_text}")').first
                    if await btn.is_visible(timeout=1500):
                        await btn.scroll_into_view_if_needed()
                        await asyncio.sleep(0.3)
                        await btn.click(force=True)
                        confirmed = True
                        logger.info(f"Toutiao: Clicked '{btn_text}' (attempt {attempt + 1})")
                        break
                except Exception:
                    pass
            if confirmed:
                break

            # Try JS click
            try:
                confirmed = await page.evaluate("""() => {
                    const buttons = document.querySelectorAll('button');
                    for (const btn of buttons) {
                        const t = btn.textContent.trim();
                        if (t === '确认发布' || t === '确认' || t === '确定' || t === '发布' || t === '提交' || t === '完成') {
                            btn.click();
                            return t;
                        }
                    }
                    // Also check for clickable elements that look like buttons
                    const allBtns = document.querySelectorAll('[role="button"], .byte-btn, .ant-btn, [class*="btn-primary"], [class*="Btn"]');
                    for (const btn of allBtns) {
                        const t = btn.textContent.trim();
                        if (t === '确认发布' || t === '确认' || t === '确定') {
                            btn.click();
                            return 'role-button:' + t;
                        }
                    }
                    return false;
                }""")
                if confirmed:
                    logger.info(f"Toutiao: Clicked '{confirmed}' via JS (attempt {attempt + 1})")
                    confirmed = True
            except Exception:
                pass

            if confirmed:
                break

            if attempt == 4:
                # Dump buttons again at this point
                try:
                    buttons_now = await page.evaluate("""() => {
                        return Array.from(document.querySelectorAll('button')).map(b => ({
                            text: b.textContent.trim().substring(0, 50),
                            disabled: b.disabled,
                            visible: b.offsetParent !== null,
                        })).filter(b => b.text && b.visible);
                    }""")
                    logger.info(f"Toutiao: Buttons at attempt 5: {buttons_now}")
                except Exception:
                    pass
                logger.info("Toutiao: Still waiting for confirm button after 5 attempts...")

            await asyncio.sleep(1)

        if not confirmed:
            logger.error("Toutiao: Confirm button not found after 15 attempts")
            # Final dump of ALL buttons
            try:
                all_buttons = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('button, [role="button"], .byte-btn')).map(b => ({
                        text: b.textContent.trim().substring(0, 50),
                        disabled: b.disabled,
                        visible: b.offsetParent !== null,
                        cls: (b.className || '').toString().substring(0, 60),
                    }));
                }""")
                logger.info(f"Toutiao: ALL buttons/controls on page: {all_buttons}")
            except Exception:
                pass
            return False

        await asyncio.sleep(5)
        logger.info(f"Toutiao: === Publish COMPLETED for {account.name} ===")
        return True

    except Exception as e:
        logger.error(f"Toutiao: Publish EXCEPTION for {account.name}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

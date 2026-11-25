from __future__ import annotations

import asyncio
import json
import logging
import markdown
import os
from typing import Optional

from playwright.async_api import Page

logger = logging.getLogger("video_publisher")


async def _log_page_state(page: Page, step: str):
    try:
        url = page.url
        title = await page.title()
        logger.info(f"CompanyWebsite [{step}] URL: {url}, Title: {title}")
    except Exception as e:
        logger.error(f"CompanyWebsite [{step}] Failed to log page state: {e}")

async def publish(
    page: Page,
    account,
    media_paths: list[str],
    title: Optional[str],
    description: Optional[str],
    *,
    before_submit,
) -> bool:
    """公司管网 CMS 文章发布（PbootCMS + LayUI + UEditor）

    流程：导航到内容管理页 → 切换新增Tab → 选栏目 → 填标题 → 填正文 → 提交。
    """
    try:
        logger.info(f"CompanyWebsite: === START publish for {account.name} (id={account.id}) ===")
        logger.info(f"CompanyWebsite: Title={title}, Desc length={len(description) if description else 0}")

        if not description:
            logger.error("CompanyWebsite: No article content provided")
            return False

        # ── Step 0: 导航 + 切换 Tab ──
        logger.info("CompanyWebsite: Step 0 - Navigating to CMS...")
        try:
            await page.goto(account.website_url, wait_until="networkidle", timeout=60000)
        except Exception:
            try:
                await page.goto(account.website_url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                logger.error(f"CompanyWebsite: page.goto failed: {e}")
                return False

        await asyncio.sleep(3)

        # 显式点击"新增" Tab
        try:
            add_tab = page.locator('li[lay-id="t2"]').first
            if await add_tab.is_visible(timeout=5000):
                await add_tab.click()
                await asyncio.sleep(2)
                logger.info("CompanyWebsite: '新增' tab clicked")
        except Exception:
            logger.warning("CompanyWebsite: Tab click failed, continuing anyway")

        # 检查是否被重定向到登录页
        has_login_form = await page.evaluate("() => !!document.querySelector('#dologin')")
        if has_login_form:
            return False

        # ── Step 1: 选择栏目 "新闻" ──
        # 纯 JS 操作，绕过 LayUI 动画和 Playwright 可见性检测
        logger.info("CompanyWebsite: Step 1 - Selecting '新闻' column...")
        try:
            result = await page.evaluate("""() => {
                // 遍历原生 <select> 的 option，找文本含"新闻"的
                const selects = document.querySelectorAll('select[name="scode"]');
                for (const select of selects) {
                    for (const opt of select.options) {
                        if (opt.text.includes('新闻')) {
                            select.value = opt.value;
                            select.dispatchEvent(new Event('change', {bubbles: true}));
                            if (typeof layui !== 'undefined' && layui.form) {
                                layui.form.render('select');
                            }
                            return 'native-' + opt.value;
                        }
                    }
                }
                // 兜底：点击 dd[lay-value="3"]
                const dd = document.querySelector('dd[lay-value="3"]');
                if (dd) {
                    const input = document.querySelector('input[placeholder="请选择内容栏目"]');
                    if (input) input.click();
                    setTimeout(() => dd.click(), 300);
                    return 'dd-click';
                }
                return false;
            }""")
            if result:
                logger.info(f"CompanyWebsite: '新闻' column selected via {result}")
            else:
                logger.warning("CompanyWebsite: Could not find '新闻' option")
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.warning(f"CompanyWebsite: Column selection failed (non-fatal): {e}")

        # ── Step 2: 填写标题 ──
        logger.info("CompanyWebsite: Step 2 - Filling title...")
        if title:
            try:
                title_input = page.locator('input[name="title"]').first
                if await title_input.is_visible(timeout=10000):
                    await title_input.click()
                    await title_input.fill("")
                    await asyncio.sleep(0.2)
                    await title_input.fill(title)
                    await asyncio.sleep(0.3)
                    val = await title_input.input_value()
                    logger.info(f"CompanyWebsite: Title filled ({len(val)} chars)")
                else:
                    # JS 兜底
                    await page.evaluate("""(t) => {
                        const el = document.querySelector('input[name="title"]');
                        if (el) { const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                            s.call(el, t); el.dispatchEvent(new Event('input', {bubbles:true})); }
                    }""", title)
                    logger.info("CompanyWebsite: Title filled via JS fallback")
            except Exception as e:
                logger.warning(f"CompanyWebsite: Title fill failed: {e}")

        # ── Step 3: 填写正文到 UEditor ──
        logger.info("CompanyWebsite: Step 3 - Filling UEditor content...")
        html_content = markdown.markdown(description, extensions=['extra', 'nl2br', 'sane_lists'])
        logger.info(f"CompanyWebsite: Markdown->HTML ({len(html_content)} chars)")

        content_filled = False

        # 策略 A: UEditor API
        try:
            result = await page.evaluate("""(html) => {
                try { const ue = UE.getEditor('editor'); if (ue && ue.setContent) { ue.setContent(html); return true; } } catch(e) {}
                return false;
            }""", html_content)
            if result:
                logger.info("CompanyWebsite: UEditor content via API")
                content_filled = True
        except Exception as e:
            logger.warning(f"CompanyWebsite: UEditor API failed: {e}")

        # 策略 B: 直接写入 UEditor iframe 的 contenteditable body
        if not content_filled:
            try:
                for frame in page.frames:
                    if frame == page.main_frame:
                        continue
                    try:
                        is_editable = await frame.evaluate(
                            "() => document.body && document.body.getAttribute('contenteditable') === 'true'"
                        )
                        if is_editable:
                            await frame.evaluate("""(html) => {
                                document.body.innerHTML = html;
                                document.body.dispatchEvent(new Event('input', {bubbles:true}));
                            }""", html_content)
                            await asyncio.sleep(1)
                            text_len = await frame.evaluate("() => document.body ? document.body.innerText.length : 0")
                            if text_len > 0:
                                logger.info(f"CompanyWebsite: UEditor iframe body filled ({text_len} chars)")
                                content_filled = True
                            break
                    except Exception:
                        continue
            except Exception as e:
                logger.warning(f"CompanyWebsite: iframe body fill failed: {e}")

        if not content_filled:
            # 策略 C: 主页面 contenteditable body
            try:
                result = await page.evaluate("""(html) => {
                    const b = document.querySelector('body[contenteditable="true"]');
                    if (b) { b.innerHTML = html; b.dispatchEvent(new Event('input', {bubbles:true})); return b.innerText.length; }
                    return 0;
                }""", html_content)
                if result and result > 0:
                    logger.info(f"CompanyWebsite: contenteditable body filled ({result} chars)")
                    content_filled = True
            except Exception:
                pass

        if not content_filled:
            logger.error("CompanyWebsite: ALL content strategies FAILED!")

        await before_submit()
        # ── Step 4: 点击"立即提交" ──
        logger.info("CompanyWebsite: Step 4 - Clicking submit...")
        await asyncio.sleep(2)

        submitted = False
        for attempt, btn_text in enumerate(["立即提交", "提交", "发布", "保存"]):
            try:
                btn = page.get_by_text(btn_text, exact=True).first
                if await btn.is_visible(timeout=2000):
                    await btn.scroll_into_view_if_needed()
                    await asyncio.sleep(0.3)
                    await btn.click(force=True)
                    submitted = True
                    logger.info(f"CompanyWebsite: Clicked '{btn_text}' (attempt {attempt+1})")
                    break
            except Exception:
                continue

        if not submitted:
            # JS 兜底
            try:
                result = await page.evaluate("""() => {
                    for (const btn of document.querySelectorAll('button[lay-submit]')) {
                        if (btn.offsetParent) { btn.click(); return 'clicked'; }
                    }
                    return false;
                }""")
                if result:
                    submitted = True
                    logger.info("CompanyWebsite: Submit via JS click")
            except Exception:
                pass

        if not submitted:
            logger.error("CompanyWebsite: Submit button NOT found!")
            return False

        # ── Step 5: 等待提交完成 + 检查结果 ──
        logger.info("CompanyWebsite: Step 5 - Waiting for submit result...")
        # 等待页面跳转或弹窗
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        await asyncio.sleep(2)

        result_check = {}
        try:
            result_check = await page.evaluate("""() => {
                const r = {url: location.href};
                const layer = document.querySelector('.layui-layer-dialog, .layui-layer-msg');
                if (layer && layer.offsetParent) r.layer = layer.textContent.trim().substring(0, 200);
                for (const el of document.querySelectorAll('*')) {
                    const t = el.textContent.trim();
                    if ((t.includes('成功') || t.includes('发布成功') || t.includes('添加成功')) && el.offsetParent && t.length < 50) r.success = t;
                    if ((t.includes('失败') || t.includes('错误')) && el.offsetParent && t.length < 50) r.error = t;
                }
                return r;
            }""")
        except Exception as e:
            logger.warning(f"CompanyWebsite: Result check failed (page may have navigated): {e}")
            result_check = {"url": str(page.url) if page else "unknown", "note": "page closed after submit"}

        logger.info(f"CompanyWebsite: Result: {json.dumps(result_check, ensure_ascii=False)}")

        # 关闭可能的 LayUI 弹窗
        if result_check.get("layer"):
            for ok_text in ["确定", "确认", "知道了"]:
                try:
                    btn = page.get_by_text(ok_text, exact=True).first
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        break
                except Exception:
                    continue
            await asyncio.sleep(1)

        logger.info(f"CompanyWebsite: === COMPLETED for {account.name} ===")
        # 有成功提示 或 无错误提示 = 成功
        return bool(result_check.get("success")) or not result_check.get("error")

    except Exception as e:
        logger.error(f"CompanyWebsite: EXCEPTION: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

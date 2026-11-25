"""
微信公众号发布器 — 浏览器自动化（Playwright）

流程：登录公众号后台 → 草稿箱 → 新建文章 → 填标题 → 填内容 → 声明AI生成 → 保存草稿
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from playwright.async_api import Page

logger = logging.getLogger("video_publisher")

WECHAT_MP_URL = "https://mp.weixin.qq.com"

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
        logger.info(f"WechatMP: === START publish for {account.name} (id={account.id}) ===")
        logger.info(f"WechatMP: Title={title[:50] if title else 'N/A'}, Desc length={len(description) if description else 0}")

        if not description:
            logger.error("WechatMP: No article content provided")
            return False

        # Step 0: 导航到公众号后台首页
        logger.info("WechatMP: Step 0 - Navigating to MP home...")
        try:
            await page.goto(WECHAT_MP_URL, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            logger.error(f"WechatMP: page.goto failed: {e}")
            return False

        await asyncio.sleep(3)

        # 检查当前页面状态
        current_url = page.url
        page_title = await page.title()
        logger.info(f"WechatMP: Current URL={current_url}, Title={page_title}")

        # 检查登录状态
        if "login" in current_url.lower():
            logger.error(f"WechatMP: Not logged in! URL: {current_url}")
            return False

        # Step 1: 先点击"内容管理"展开菜单
        logger.info("WechatMP: Step 1 - Clicking 内容管理...")
        try:
            content_mgmt = page.locator('span.weui-desktop-menu__name:has-text("内容管理")').first
            await content_mgmt.wait_for(state="visible", timeout=10000)
            await content_mgmt.click()
            logger.info("WechatMP: 内容管理 clicked")
        except Exception as e:
            logger.error(f"WechatMP: 内容管理 not found: {e}")
            return False

        await asyncio.sleep(1)

        # Step 2: 点击"草稿箱"
        logger.info("WechatMP: Step 2 - Clicking 草稿箱...")
        try:
            draft_btn = page.locator('a[title="草稿箱"]').first
            await draft_btn.wait_for(state="visible", timeout=10000)
            await draft_btn.click()
            logger.info("WechatMP: 草稿箱 clicked")
        except Exception as e:
            logger.error(f"WechatMP: 草稿箱 not found: {e}")
            return False

        await asyncio.sleep(2)

        # Step 3: 点击"新的创作"
        logger.info("WechatMP: Step 3 - Clicking 新的创作...")
        try:
            new_create_btn = page.locator('button.weui-desktop-btn_primary:has-text("新的创作")').first
            await new_create_btn.wait_for(state="visible", timeout=10000)
            await new_create_btn.click()
            logger.info("WechatMP: 新的创作 clicked")
        except Exception as e:
            logger.error(f"WechatMP: 新的创作 not found: {e}")
            return False

        await asyncio.sleep(1)

        # Step 4: 点击下拉菜单中的"文章"
        logger.info("WechatMP: Step 4 - Clicking 文章...")
        try:
            article_item = page.locator('span.weui-desktop-dropdown__list-ele__text:has-text("文章")').first
            await article_item.wait_for(state="visible", timeout=10000)
            await article_item.click()
            logger.info("WechatMP: 文章 clicked")
        except Exception as e:
            logger.error(f"WechatMP: 文章 not found: {e}")
            return False

        # Step 4 会打开新窗口，等待并切换到新页面
        logger.info("WechatMP: Waiting for editor page to open...")
        await asyncio.sleep(3)
        # 获取最新的页面（编辑页通常是最后一个打开的）
        all_pages = page.context.pages
        if len(all_pages) > 1:
            page = all_pages[-1]  # 切换到新窗口
            logger.info(f"WechatMP: Switched to new page, URL={page.url}")
        else:
            logger.warning("WechatMP: No new page detected, staying on current page")

        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(2)

        # Step 5: 填标题
        logger.info("WechatMP: Step 5 - Filling title...")
        if title:
            try:
                title_editor = page.locator('div.ProseMirror[data-placeholder="请在这里输入标题"]').first
                await title_editor.wait_for(state="visible", timeout=10000)
                await title_editor.click()
                await asyncio.sleep(0.3)
                # 全选并替换
                await page.keyboard.press("Control+a")
                await page.keyboard.press("Backspace")
                await page.keyboard.type(title, delay=10)
                logger.info(f"WechatMP: Title filled: {title}")
            except Exception as e:
                logger.error(f"WechatMP: Title fill FAILED: {e}")
                # 不中断，继续

        await asyncio.sleep(0.5)

        # Step 6: 填内容
        logger.info("WechatMP: Step 6 - Filling content...")
        content_filled = False

        # 策略A: 定位正文 ProseMirror，用 JS innerHTML 注入（与头条方式一致）
        try:
            # 找到所有 contenteditable="true" 的 ProseMirror
            editors = page.locator('div.ProseMirror[contenteditable="true"]')
            count = await editors.count()
            logger.info(f"WechatMP: Found {count} ProseMirror editors")
            if count >= 2:
                body_editor = editors.nth(1)  # 第2个是正文
                await body_editor.wait_for(state="visible", timeout=10000)
                await body_editor.click()
                await asyncio.sleep(0.3)

                # 转换 Markdown 为 HTML（与头条一致）
                import markdown
                html_content = markdown.markdown(
                    description,
                    extensions=['extra', 'nl2br', 'sane_lists'],
                )

                # JS 注入 innerHTML
                injected = await page.evaluate("""(html) => {
                    const editors = document.querySelectorAll('div.ProseMirror[contenteditable="true"]');
                    if (editors.length >= 2) {
                        const editor = editors[1];
                        editor.innerHTML = html;
                        editor.dispatchEvent(new Event('input', { bubbles: true }));
                        editor.dispatchEvent(new Event('change', { bubbles: true }));
                        return editor.innerText.length;
                    }
                    return 0;
                }""", html_content)
                logger.info(f"WechatMP: Content injected via HTML, length={injected}")

                if injected > 0:
                    content_filled = True
                    await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"WechatMP: HTML injection failed: {e}")

        # 策略B: JS 兜底 - 直接操作 ProseMirror 的 innerHTML
        if not content_filled:
            try:
                logger.info("WechatMP: Trying JS innerHTML fallback...")
                # 去掉 markdown 标记，用纯文本
                plain = description.replace('#', '').replace('*', '').replace('`', '')
                injected = await page.evaluate("""(text) => {
                    const editors = document.querySelectorAll('div.ProseMirror[contenteditable="true"]');
                    for (const editor of editors) {
                        const rect = editor.getBoundingClientRect();
                        if (rect.height > 200) {  // 正文编辑器通常比较高
                            editor.innerHTML = '<p>' + text.replace(/\\n/g, '</p><p>') + '</p>';
                            editor.dispatchEvent(new Event('input', { bubbles: true }));
                            editor.dispatchEvent(new Event('change', { bubbles: true }));
                            return editor.innerText.length;
                        }
                    }
                    return 0;
                }""", plain)
                if injected > 0:
                    content_filled = True
                    logger.info(f"WechatMP: Content filled via JS fallback, length={injected}")
            except Exception as e:
                logger.warning(f"WechatMP: JS fallback failed: {e}")

        if not content_filled:
            logger.warning("WechatMP: All content fill strategies failed")

        await asyncio.sleep(1)

        if not content_filled:
            return False

        await before_submit()
        # Step 8: 保存草稿（先点编辑区获取焦点，再 Ctrl+S）
        logger.info("WechatMP: Step 8 - Saving draft (Ctrl+S)...")
        try:
            editors = page.locator('div.ProseMirror[contenteditable="true"]')
            count = await editors.count()
            if count >= 2:
                await editors.nth(1).click()
            else:
                await editors.first.click()
            await asyncio.sleep(0.3)
            await page.keyboard.press("Control+s")
            logger.info("WechatMP: Ctrl+S pressed")
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"WechatMP: Ctrl+S failed: {e}")
            return False

        try:
            await page.get_by_text("保存成功", exact=False).first.wait_for(state="visible", timeout=5000)
            return "draft"
        except Exception:
            return False

    except Exception as e:
        logger.error(f"WechatMP: Publish EXCEPTION for {account.name}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False
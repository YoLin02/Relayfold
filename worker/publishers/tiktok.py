"""TikTok 发布模块 — Playwright 浏览器自动化"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from playwright.async_api import Page

logger = logging.getLogger("video_publisher")

PUBLISH_URL = "https://www.tiktok.com/tiktokstudio/upload?from=webapp&tab=video"


async def publish(
    page: Page,
    account,
    media_paths: list[str],
    title: Optional[str],
    description: Optional[str],
    get_sms_code=None,
    declaration_type: int = 1,
    *,
    before_submit,
) -> bool:
    """
    TikTok 视频发布流程：
    1. 打开上传页面
    2. 上传视频文件
    3. 填写描述（Draft.js 编辑器）
    4. 点击发布
    """
    try:
        logger.info(f"TikTok: Starting publish for {account.name}")
        logger.info(f"TikTok: Title={title}, Description={description}, MediaPaths={media_paths}")

        if not media_paths:
            logger.error(f"TikTok: No media files provided for {account.name}")
            return False

        if not os.path.exists(media_paths[0]):
            logger.error(f"TikTok: Media file not found: {media_paths[0]}")
            return False

        # ===== 1. 打开上传页面 =====
        # TikTok 走代理，加载慢，timeout 给 90s
        goto_timeout = 90000
        try:
            await page.goto(PUBLISH_URL, wait_until="domcontentloaded", timeout=goto_timeout)
        except Exception:
            # 超时不一定是失败——TikTok 海外资源可能慢，只要页面没跳去登录就算成功
            logger.warning(f"TikTok: Page load timeout after {goto_timeout // 1000}s, checking current url...")
            try:
                _ = page.url
            except Exception:
                logger.error(f"TikTok: Page unresponsive after timeout")
                raise
            # 如果已经在目标页面上，继续执行
            if "tiktokstudio" in page.url.lower() or "upload" in page.url.lower():
                logger.info(f"TikTok: Page seems loaded despite timeout, url={page.url}")
            else:
                logger.error(f"TikTok: Unexpected url after timeout: {page.url}")
                return False

        await asyncio.sleep(3)

        # 检查是否被重定向到登录
        current_url = page.url.lower()
        if "login" in current_url or "signin" in current_url or "sign-in" in current_url:
            logger.error(f"TikTok: Account {account.name} session expired (redirected to auth page)")
            return False

        logger.info(f"TikTok: Upload page loaded, url={page.url}")

        # ===== 2. 上传视频 =====
        # TikTok 的上传区域是 div[data-e2e="select_video_container"]
        # 内部通常有一个隐藏的 input[type="file"]
        logger.info("TikTok: Uploading video...")

        # 先尝试直接找 file input
        file_input = await page.query_selector('input[type="file"]')
        if not file_input:
            # 如果没有暴露的 file input，点击上传区域触发文件选择
            logger.info("TikTok: No visible file input, clicking upload container...")
            upload_container = await page.wait_for_selector(
                'div[data-e2e="select_video_container"]',
                state="visible",
                timeout=15000
            )
            await upload_container.click()
            await asyncio.sleep(1)
            # 点击后 input[type="file"] 通常会出现（由 JS 动态创建）
            file_input = await page.wait_for_selector(
                'input[type="file"]',
                state="attached",
                timeout=10000
            )

        if not file_input:
            logger.error("TikTok: File input not found after clicking upload container")
            return False

        # 设置文件（Playwright 对隐藏的 input 也支持 set_input_files）
        await file_input.set_input_files(media_paths[0])
        logger.info(f"TikTok: Video uploaded for {account.name}")

        # 等待视频上传和处理完成
        logger.info("TikTok: Waiting for video processing...")

        # 等待上传完成：上传容器消失或发布按钮变为可用
        try:
            # 等待上传容器消失（上传成功后会替换）
            await page.wait_for_selector(
                'div[data-e2e="select_video_container"]',
                state="detached",
                timeout=120000
            )
            logger.info("TikTok: Upload container disappeared, video processed")
        except Exception:
            # 超时也不一定失败，继续
            logger.info("TikTok: Upload container still present after 120s, continuing anyway")

        await asyncio.sleep(5)

        # ===== 3. 填写描述 =====
        # TikTok 使用 Draft.js 编辑器，需要先聚焦再通过剪贴板粘贴写入
        if description:
            try:
                logger.info("TikTok: Filling description...")
                # Draft.js 的编辑区域（public-DraftEditor-content）
                desc_editor = await page.wait_for_selector(
                    'div[class*="public-DraftEditor-content"], div[class*="public-DraftStyleDefault-block"]',
                    timeout=15000
                )
                if desc_editor:
                    await desc_editor.scroll_into_view_if_needed()
                    await asyncio.sleep(0.5)

                    # ① 先清空现有内容（Draft.js 默认有一个空 <br>）
                    await desc_editor.click()
                    await asyncio.sleep(0.3)
                    await page.keyboard.press("Control+a")
                    await asyncio.sleep(0.2)
                    await page.keyboard.press("Delete")
                    await asyncio.sleep(0.3)

                    # ② 通过剪贴板粘贴（Draft.js 对 keyboard.type 不生效）
                    await page.evaluate(
                        "text => navigator.clipboard.writeText(text)",
                        description
                    )
                    await asyncio.sleep(0.3)
                    await desc_editor.click()
                    await asyncio.sleep(0.3)
                    await page.keyboard.press("Control+v")
                    await asyncio.sleep(1)

                    # ③ 验证内容是否成功写入
                    editor_text = await desc_editor.inner_text()
                    if editor_text.strip():
                        logger.info(f"TikTok: Description pasted successfully: {editor_text[:80]}...")
                    else:
                        # 降级：尝试直接用 JS 注入 Draft.js state（最后手段）
                        logger.warning("TikTok: Paste may have failed, trying JS injection...")
                        await page.evaluate(
                            """desc => {
                                const editor = document.querySelector('div[class*="public-DraftEditor-content"]');
                                if (editor && editor.__reactFiber$) {
                                    // Draft.js 的编辑内容通常保存在 React fiber 中
                                    // 尝试通过 data-transfer 模拟粘贴事件
                                    const dt = new DataTransfer();
                                    dt.setData('text/plain', desc);
                                    editor.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true }));
                                }
                            }""",
                            description
                        )
                else:
                    logger.warning("TikTok: Description editor not found")
            except Exception as e:
                logger.warning(f"TikTok: Failed to fill description (non-critical): {e}")

        await asyncio.sleep(3)

        await before_submit()
        # ===== 4. 点击发布 =====
        logger.info("TikTok: Clicking publish button...")
        try:
            publish_btn = await page.wait_for_selector(
                'button[data-e2e="post_video_button"]',
                timeout=30000
            )
            if publish_btn:
                # 检查按钮是否可用（无 disabled 属性）
                is_disabled = await publish_btn.get_attribute("data-disabled")
                if is_disabled == "true":
                    logger.warning("TikTok: Publish button is disabled, waiting...")
                    # 等待按钮变为可用（最多等 30s）
                    await page.wait_for_selector(
                        'button[data-e2e="post_video_button"][data-disabled="false"]',
                        timeout=30000
                    )
                await publish_btn.click()
                logger.info(f"TikTok: Publish button clicked for {account.name}")
            else:
                logger.error("TikTok: Publish button not found")
                return False
        except Exception as e:
            logger.error(f"TikTok: Failed to click publish button: {e}")
            return False

        # 等待发布完成
        await asyncio.sleep(5)

        # ===== 5. 检查是否有验证码 =====
        try:
            sms_input = await page.wait_for_selector(
                'input[placeholder*="code"], input[placeholder*="Code"], input[placeholder*="验证"]',
                timeout=5000
            )
            if sms_input:
                logger.info("TikTok: Verification code required")
                if not get_sms_code:
                    logger.warning("TikTok: No SMS callback, cannot verify")
                    return False

                code = None
                for _ in range(60):
                    code = get_sms_code(account.id)
                    if code:
                        break
                    await asyncio.sleep(2)

                if code:
                    await sms_input.fill(code)
                    confirm_btn = await page.query_selector(
                        'button:has-text("Confirm"), button:has-text("确认"), button:has-text("Verify")'
                    )
                    if confirm_btn:
                        await confirm_btn.click()
                        logger.info("TikTok: Verification code submitted")
                else:
                    logger.warning("TikTok: Verification code timeout")
                    return False
        except Exception:
            # 超时说明不需要验证码，正常
            pass

        await asyncio.sleep(5)
        logger.info(f"TikTok: Publish completed for {account.name}")
        return True

    except Exception as e:
        error_str = str(e)
        if "Target page, context or browser has been closed" in error_str or "TargetClosedError" in error_str:
            logger.error(f"TikTok: Page/context closed during publish for {account.name}")
            raise
        logger.error(f"TikTok: Publish error for {account.name}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

"""网易号发布器 —— 发布图文文章到 mp.163.com"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
from typing import Optional

from playwright.async_api import Page

logger = logging.getLogger("video_publisher")

WANGYI_PUBLISH_URL = "https://mp.163.com/#/article-publish"


def _parse_blocks(text: str) -> list[tuple[str, str]]:
    """把 Markdown 正文解析成内容块列表 [(kind, value)]。

    kind 为 'text'（纯文本段落）或 'image'（图片，value 为图片在 media_paths 中的序号）。
    网易号编辑器不支持 Markdown，这里同时完成 Markdown 清理与图片位置保留。
    """
    blocks: list[tuple[str, str]] = []
    image_index = 0

    def _replace_image(m) -> str:
        nonlocal image_index
        placeholder = f"[[IMAGE_{image_index}]]"
        image_index += 1
        return placeholder

    # 1. 图片标记 ![](url) → 占位符 [[IMAGE_n]]（保留位置）
    text = re.sub(r'!\[[^\]]*\]\([^\)]*\)', _replace_image, text)
    # 2. 清理其余 Markdown
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)           # 加粗
    text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'\1', text)  # 斜体
    text = re.sub(r'`([^`]+)`', r'\1', text)                 # 行内代码
    text = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'\1', text)    # 链接
    text = re.sub(r'^\s*[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)  # 分隔线
    text = re.sub(r'\n{3,}', '\n\n', text)                   # 折叠多余空行

    # 3. 逐行解析，识别图片占位符
    for raw_line in text.split('\n'):
        line = re.sub(r'^#{1,6}\s*', '', raw_line.strip())
        if not line:
            continue
        for part in re.split(r'(\[\[IMAGE_\d+\]\])', line):
            part = part.strip()
            if not part:
                continue
            m = re.match(r'^\[\[IMAGE_(\d+)\]\]$', part)
            if m:
                blocks.append(('image', m.group(1)))
            else:
                blocks.append(('text', part))
    return blocks


async def _paste_image(page: Page, image_path: str) -> bool:
    """把本地图片写入真实剪贴板，再 Ctrl+V 粘贴到网易号编辑器（模拟手动粘贴图片）。

    粘贴后需等待一段时间，图片才会被网易号上传到服务器。
    """
    ext = os.path.splitext(image_path)[1].lower()
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    mime = mime_map.get(ext, "image/png")
    filename = os.path.basename(image_path)
    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
    except Exception as e:
        logger.error(f"Wangyi: 读取图片失败 {filename}: {e}")
        return False

    try:
        # 1. 确保页面在前台（navigator.clipboard 需要 document 有焦点）
        await page.bring_to_front()
        # 2. 授予剪贴板读写权限
        try:
            await page.context.grant_permissions(
                ["clipboard-read", "clipboard-write"],
                origin="https://mp.163.com",
            )
        except Exception as e:
            logger.warning(f"Wangyi: 授予剪贴板权限失败: {e}")

        # 3. 页面内把图片 Blob 写入真实剪贴板
        await page.evaluate('''async ({b64, mime}) => {
            const byteChars = atob(b64);
            const byteNumbers = new Uint8Array(byteChars.length);
            for (let i = 0; i < byteChars.length; i++) {
                byteNumbers[i] = byteChars.charCodeAt(i);
            }
            const blob = new Blob([byteNumbers], { type: mime });
            await navigator.clipboard.write([new ClipboardItem({ [mime]: blob })]);
        }''', {"b64": b64, "mime": mime})
        await asyncio.sleep(0.3)

        # 4. 聚焦编辑器并 Ctrl+V 粘贴
        await page.evaluate('''() => {
            const editor = document.querySelector('div[contenteditable="true"], div.public-DraftEditor-content');
            if (editor) editor.focus();
        }''')
        await asyncio.sleep(0.5)
        await page.keyboard.press('Control+v')

        # 5. 等待图片上传完成（网易号粘贴后需要时间上传到服务器）
        await asyncio.sleep(5)
        logger.info(f"Wangyi: 图片已粘贴并等待上传: {filename}")
        return True
    except Exception as e:
        logger.error(f"Wangyi: 图片粘贴失败 {filename}: {e}")
        return False


async def _click_publish(page: Page) -> bool:
    """点击网易号的「发布」按钮（含发布/确认发布等 primary 按钮）。"""
    return await page.evaluate('''() => {
        const buttons = document.querySelectorAll('button.primary_button');
        for (const btn of buttons) {
            if (btn.textContent.includes('发布')) {
                btn.click();
                return true;
            }
        }
        return false;
    }''')


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
        logger.info(f"Wangyi: Starting article publish for {account.name}")
        logger.info(f"Wangyi: Title={title}, Description length={len(description) if description else 0}")

        if not description:
            logger.error("Wangyi: No article content provided")
            return False

        await page.goto(WANGYI_PUBLISH_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        # 检查是否跳转到登录页
        if "login" in page.url.lower():
            logger.error(f"Wangyi: Account {account.name} session expired")
            return False

        # 1. 填写标题
        if title:
            try:
                title_input = await page.wait_for_selector(
                    'textarea.netease-textarea',
                    timeout=10000
                )
                if title_input:
                    await title_input.click()
                    await asyncio.sleep(0.3)
                    await title_input.fill(title)
                    logger.info(f"Wangyi: Title filled: {title}")
                else:
                    logger.warning("Wangyi: Title textarea not found")
            except Exception as e:
                logger.error(f"Wangyi: Failed to fill title: {e}")

        # 2. 填写正文（Draft.js 编辑器）
        if description:
            try:
                # Draft.js 编辑器的 contenteditable 区域
                content_editor = await page.wait_for_selector(
                    'div[contenteditable="true"], div.public-DraftEditor-content',
                    timeout=10000
                )
                if content_editor:
                    await content_editor.click()
                    await asyncio.sleep(0.5)

                    # 网易号编辑器不支持 Markdown，解析成文字块 + 图片块，逐块插入
                    blocks = _parse_blocks(description)
                    # AI 首行是「## 标题」，与标题字段重复，跳过
                    if blocks and blocks[0][0] == 'text' and title and blocks[0][1] == title.strip():
                        blocks = blocks[1:]

                    for i, (kind, value) in enumerate(blocks):
                        if i > 0:
                            await page.keyboard.press('Enter')
                            await asyncio.sleep(0.1)
                        if kind == 'text':
                            await page.keyboard.insert_text(value)
                        else:
                            img_idx = int(value)
                            if img_idx < len(media_paths):
                                await _paste_image(page, media_paths[img_idx])
                            else:
                                logger.warning(f"Wangyi: 图片序号 {img_idx} 超出 media_paths 范围 ({len(media_paths)})")
                    logger.info(f"Wangyi: 正文已插入 ({len(blocks)} 块)")
                else:
                    logger.warning("Wangyi: Content editor not found")
            except Exception as e:
                logger.error(f"Wangyi: Failed to fill content: {e}")

        # 3. 选择自动封面
        try:
            await asyncio.sleep(1)
            cover_clicked = await page.evaluate('''() => {
                const radios = document.querySelectorAll('input.ne-switch-base-input[type="radio"][value="auto"]');
                for (const radio of radios) {
                    radio.click();
                    return true;
                }
                return false;
            }''')
            if cover_clicked:
                logger.info("Wangyi: Auto cover selected")
                await asyncio.sleep(0.5)
            else:
                logger.warning("Wangyi: Auto cover radio not found")
        except Exception as e:
            logger.warning(f"Wangyi: Failed to set auto cover: {e}")

        await before_submit()
        # 4. 点击发布（第一次：触发发文前检测/诊断）
        await asyncio.sleep(1)
        first_clicked = await _click_publish(page)
        if not first_clicked:
            logger.error("Wangyi: Publish button not found")
            return False
        logger.info("Wangyi: 已点击发布，等待发文前检测（诊断）完成...")
        await asyncio.sleep(15)

        # 5. 诊断通过后，再次点击发布
        second_clicked = await _click_publish(page)
        if second_clicked:
            logger.info(f"Wangyi: 二次确认发布 for {account.name}")
            await asyncio.sleep(5)
        else:
            logger.warning("Wangyi: 第二次点击发布未找到按钮（可能已自动提交）")

        logger.info(f"Wangyi: Publish completed for {account.name}")
        return True

    except Exception as e:
        logger.error(f"Wangyi: Publish error for {account.name}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

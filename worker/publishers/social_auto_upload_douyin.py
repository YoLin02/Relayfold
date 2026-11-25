"""Douyin video preparation adapted from dreammis/social-auto-upload (MIT)."""

# Upstream: 409d4fdd33f3eb0d946310af93633ddb5eebe1d5/uploader/douyin_uploader/main.py
# Copyright (c) 2023 dreammis. See licenses/social-auto-upload-MIT.txt.

import re

PUBLISH_URL = "https://creator.douyin.com/creator-micro/content/upload"
FORM_URL = re.compile(r"^https://creator\.douyin\.com/creator-micro/content/(?:publish|post/video)(?:[/?#]|$)")
MEDIA_INPUT = (
    "input.upload-btn-input, div[class^='container'] input[type='file'][accept*='video'], "
    "div[class^='container'] input[type='file'][accept*='.mp4'], "
    "input[type='file'][accept*='video'], input[type='file'][accept*='.mp4']"
)
UPLOADED = '[class^="long-card"] div:has-text("重新上传")'


async def prepare_video(page, file_path):
    await page.goto(PUBLISH_URL, wait_until="domcontentloaded", timeout=90000)
    upload_input = page.locator(MEDIA_INPUT).first
    await upload_input.wait_for(state="attached", timeout=60000)
    await upload_input.set_input_files(file_path)
    await page.wait_for_url(FORM_URL, timeout=120000)

    # Use the upstream's positive upload marker. An empty or disabled editor alone
    # cannot establish that Douyin has finished processing the uploaded file.
    marker = page.locator(UPLOADED).or_(page.get_by_text("重新上传", exact=True)).filter(visible=True)
    await marker.first.wait_for(timeout=180000)
    await page.wait_for_function("""() =>
        !/文件解析中|视频上传中|正在上传|取消上传/.test(document.body?.innerText || '')
    """, timeout=180000)

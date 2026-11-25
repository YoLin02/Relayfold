import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from playwright.async_api import async_playwright
from patchright.async_api import async_playwright as async_patchright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))

from adapters import publish_browser
from browser import Browser


XHS_TEST_NOTE_ID = "0123456789ab0123456789ab"

DY_UPLOAD = """
<button type="button" id="image">发布图文</button>
<div class="container-upload">
  <input type="file" accept="video/*" id="upload">
</div>
<script>
  document.querySelector('#image').onclick = () => {
    const input = document.querySelector('#upload');
    input.accept = 'image/*';
    input.multiple = true;
    input.onchange = () => {
      sessionStorage.media = JSON.stringify([...input.files].map(f => f.name));
      location.href = '/creator-micro/content/post/image?test=1';
    };
  };
</script>
"""

FORM = """
<div id="story">
  <input type="text" placeholder="填写作品标题">
  <div class="zone-container tiptap ProseMirror" contenteditable="true" style="min-height:30px"></div>
  <div class="publish-page-publish-btn"><button id="publish">发布</button></div>
</div>
<script>
  const pub = document.querySelector('#publish');
  pub.onclick = () => { window.published = (window.published || 0) + 1; };
</script>
"""

DY_COVER = """
<img alt="视频预览封面">
<button id="cover">选择封面</button>
<div role="dialog" class="dy-creator-content-modal" hidden>
  <span>设置竖封面</span>
  <div class="semi-upload"><input type="file" id="reference"></div>
  <div class="semi-upload">
    <span class="semi-upload-drag-area-main-text">点击上传文件</span>
    <input type="file" accept="image/*" id="cover-file">
  </div>
  <button class="semi-button-disabled" id="done" disabled>完成</button>
</div>
"""

XHS_COVER = """
<div class="upload-cover" role="button" id="cover">自定义封面</div>
<div role="dialog" class="d-modal" hidden>
  <button id="upload-tab" onclick="document.querySelector('#cover-file').hidden = false">上传封面</button>
  <input type="file" accept="image/*" id="cover-file" hidden>
  <div class="d-modal-footer"><button id="done" disabled>确定</button></div>
</div>
"""

XHS_VIDEO_FORM = FORM.replace("填写作品标题", "填写标题").replace(
    '<div class="publish-page-publish-btn"><button id="publish">发布</button></div>',
    '<xhs-publish-btn is-publish="true" submit-text="发布" submit-disabled="true">'
    '<button id="publish">发布</button><button type="button">暂存离开</button></xhs-publish-btn>',
)

XHS_DELAYED_VIDEO = """
<div class="cover-container"><div id="video-state"><div class="stage"></div></div></div>
<script>
  const input = document.querySelector('#upload');
  const originalChange = input.onchange;
  const publish = document.querySelector('#publish');
  publish.addEventListener('click', () => fetch('/web_api/sns/v2/note', {method:'POST'}));
  const host = document.querySelector('xhs-publish-btn');
  host.attachShadow({mode: 'closed'}).append(...host.children);
  publish.disabled = true;
  input.onchange = event => {
    originalChange(event);
    const state = document.querySelector('#video-state');
    const stage = state.querySelector('.stage');
    state.className = 'transcoding';
    stage.innerText = '转码中，不影响发布';
    if (document.documentElement.dataset.stalled) return;
    setTimeout(() => {
      state.className = 'preview-new';
      stage.innerText = '检测为高清视频。清晰的画面能极大提升观看体验，有利于提升观看时长';
      document.documentElement.dataset.videoProcessed = 'yes';
    }, 1400);
    setTimeout(() => {
      publish.disabled = false;
      host.setAttribute('submit-disabled', 'false');
    }, 4500);
  };
</script>
"""

COVER_BEHAVIOR = """
<script>
  document.querySelector('#cover').onclick = () => {document.querySelector('[role=dialog]').hidden = false;};
  document.querySelector('#cover-file').onchange = e => {
    window.coverName = e.target.files[0].name;
    const done = document.querySelector('#done');
    done.classList.remove('semi-button-disabled');
    done.disabled = false;
  };
  document.querySelector('#done').onclick = () => {
    window.coverApplied = window.coverName;
    document.querySelector('[role=dialog]').hidden = true;
  };
</script>
"""

XHS_TOPIC = """
<div id="creator-editor-topic-container"></div>
<script>
  const editor = document.querySelector('[contenteditable]');
  const topics = document.querySelector('#creator-editor-topic-container');
  editor.addEventListener('input', () => {
    topics.replaceChildren();
    if (!editor.innerText.endsWith('#精选')) return;
    for (const name of ['精选推荐', '精选']) {
      const entry = document.createElement('div');
      entry.className = 'item';
      const label = document.createElement('span');
      label.innerText = name;
      entry.append(label, ' 123');
      entry.onclick = () => {
        window.selectedTopic = name;
        topics.replaceChildren();
      };
      topics.append(entry);
    }
  });
</script>
"""

UPLOAD = """
<input type="file" accept="{accept}" id="upload" multiple>
<script>
  document.querySelector('#upload').onchange = e => {{
    sessionStorage.media = JSON.stringify([...e.target.files].map(f => f.name));
  }};
</script>
"""


class BrowserAdapterTest(unittest.IsolatedAsyncioTestCase):
    async def test_xiaohongshu_processing_timeout_never_submits(self):
        with tempfile.TemporaryDirectory() as folder, patch(
            "publishers.xiaohongshu.VIDEO_PROCESS_SECONDS", 0.5
        ):
            media = Path(folder) / "video.mp4"
            media.write_bytes(b"local fixture")
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(channel="chrome", headless=True)
                try:
                    context = await browser.new_context(service_workers="block")

                    async def intercept(route):
                        upload = UPLOAD.format(accept="video/*")
                        await route.fulfill(content_type="text/html; charset=utf-8",
                                            body="<html data-stalled=yes><meta charset=utf-8>" + upload + XHS_VIDEO_FORM + XHS_DELAYED_VIDEO)

                    await context.route("**/*", intercept)
                    page = await context.new_page()
                    await page.goto("https://creator.xiaohongshu.com/")
                    stages = []

                    async def before_submit():
                        self.fail("A video still being processed must never reach submission")

                    task = {"kind": "video", "title": "隔离验收", "description": "", "media_files": [str(media)], "options": {}}
                    binding = {"platform": "xiaohongshu", "label": "验收", "id": "test"}
                    with self.assertRaisesRegex(ValueError, "等待视频处理或编辑区超时"):
                        await publish_browser(page, binding, task, before_submit, progress=stages.append)
                    self.assertIn("仍在转码", stages[-1])
                    self.assertIsNone(await page.evaluate("window.published"))
                finally:
                    await browser.close()

    async def test_video_and_image_fields_reach_each_platform_form(self):
        with tempfile.TemporaryDirectory() as folder:
            media = {name: str(Path(folder) / name) for name in ("video.mp4", "first.jpg", "second.jpg", "dy.jpg", "xhs.jpg")}
            for path in media.values():
                Path(path).write_bytes(b"local fixture")
            async with async_playwright() as playwright, async_patchright() as patchright:
                browser = await playwright.chromium.launch(channel="chrome", headless=True)
                douyin_browser = await patchright.chromium.launch(channel="chrome", headless=True)
                try:
                    for platform, kind in (("douyin", "video"), ("xiaohongshu", "video"),
                                           ("douyin", "image"), ("xiaohongshu", "image")):
                        with self.subTest(platform=platform, kind=kind):
                            driver = douyin_browser if (platform, kind) == ("douyin", "video") else browser
                            await self.check_publish(driver, platform, kind, media, Path(folder))
                finally:
                    await douyin_browser.close()
                    await browser.close()

    async def check_publish(self, browser, platform, kind, media, folder):
        douyin, video = platform == "douyin", kind == "video"
        domain = "creator.douyin.com" if douyin else "creator.xiaohongshu.com"
        context = await browser.new_context()
        self.addAsyncCleanup(context.close)

        async def intercept(route):
            url = route.request.url
            if "/web/api/media/aweme/create_v2/" in url:
                await route.fulfill(json={"status_code": 0, "aweme_id": "1234567890123456789"})
                return
            if "/web_api/sns/v2/note" in url:
                await route.fulfill(json={"success": True, "data": {"id": XHS_TEST_NOTE_ID, "score": 0}})
                return
            if douyin and not video and "/content/upload" in url:
                html = DY_UPLOAD
            elif douyin and video and "/content/upload" in url:
                html = UPLOAD.format(accept="video/*").replace(
                    "map(f => f.name));",
                    "map(f => f.name)); location.href = '/creator-micro/content/post/video?test=1';"
                )
            else:
                html = FORM if douyin else FORM.replace("填写作品标题", "填写标题")
                if not douyin:
                    if video:
                        html = XHS_VIDEO_FORM
                    html = UPLOAD.format(accept="video/*" if video else "image/*") + html
                if video:
                    html += (DY_COVER if douyin else XHS_COVER) + COVER_BEHAVIOR
                    if douyin:
                        html += "<div class='long-card-fixture'><div>重新上传</div></div>"
                        html += """<script>
                          document.querySelector('#publish').addEventListener('click', () => {
                            fetch('/web/api/media/aweme/create_v2/', {method:'POST'});
                          });
                        </script>"""
                    else:
                        html += XHS_DELAYED_VIDEO
                if not douyin:
                    html += XHS_TOPIC
            await route.fulfill(content_type="text/html; charset=utf-8", body="<meta charset=utf-8>" + html)

        await context.route("**/*", intercept)
        page = await context.new_page()
        await page.goto(f"https://{domain}/")
        title = "抖音专用标题" if douyin else "小红书标题"
        description = ("视频正文" if video else "") if douyin else "第一行\n第二行"
        files = ["video.mp4"] if video else ["first.jpg", "second.jpg"]
        cover = ("dy.jpg" if douyin else "xhs.jpg") if video else "second.jpg"
        guarded = []
        stages = []

        async def fixture_value(expression):
            options = {"isolated_context": False} if douyin and video else {}
            return await page.evaluate(expression, **options)

        async def before_submit():
            self.assertIsNone(await fixture_value("window.published"))
            self.assertEqual(await page.locator("input[type=text]").input_value(), title)
            body = await page.locator("[contenteditable]").inner_text()
            self.assertIn("#精选", body)
            if not douyin:
                lines = await page.locator("[contenteditable] p").all_text_contents()
                self.assertEqual(lines[0], "第一行")
                self.assertTrue(lines[1].startswith("第二行"))
                self.assertEqual(await fixture_value("window.selectedTopic"), "精选")
                if video:
                    self.assertEqual(await fixture_value("document.documentElement.dataset.videoProcessed"), "yes")
                    self.assertEqual(await page.locator("xhs-publish-btn").get_attribute("submit-disabled"), "false")
            if video:
                self.assertEqual(await fixture_value("window.coverApplied"), cover)
            self.assertEqual(await fixture_value("JSON.parse(sessionStorage.media)"), files if video else files[::-1])
            guarded.append(True)

        task = {"kind": kind, "title": title, "description": description, "tags": ["精选"],
                "cover": media[cover], "media_files": [media[name] for name in files], "options": {},
                "declaration": "无需添加自主声明"}
        binding = {"platform": platform, "label": "验收", "id": "test"}
        if douyin and video:
            self.assertEqual(await Browser(folder).publish(page, binding, task, before_submit), "1234567890123456789")
        elif video:
            receipt = await Browser(folder).publish(page, binding, task, before_submit, progress=stages.append)
            self.assertEqual(receipt, XHS_TEST_NOTE_ID)
        else:
            self.assertTrue(await publish_browser(page, binding, task, before_submit, progress=stages.append))
        if platform == "xiaohongshu" and video:
            self.assertTrue(any("等待上传和处理" in step for step in stages))
            self.assertTrue(any("仍在转码" in step for step in stages))
            self.assertTrue(any("视频已处理完成" in step for step in stages))
            self.assertTrue(any("等待启用" in step for step in stages))
        self.assertEqual(guarded, [True])
        self.assertEqual(await fixture_value("window.published"), 1)

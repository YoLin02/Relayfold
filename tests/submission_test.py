import asyncio
import tempfile
import unittest
from pathlib import Path
import sys
from time import time
from unittest.mock import patch

from patchright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))

from browser import Browser
from main import Worker


class DouyinSubmissionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.media = self.root / "fixture.mp4"
        self.media.write_bytes(b"fake media for isolated test")
        self.worker = Worker(self.root)
        self.addCleanup(self.worker.store.db.close)
        self.worker.changed = lambda: None
        browser = self.worker.browser
        playwright = await async_playwright().start()
        self.addAsyncCleanup(playwright.stop)
        chromium = await playwright.chromium.launch(channel="chrome", headless=True)
        self.addAsyncCleanup(chromium.close)
        self.addAsyncCleanup(browser.shutdown)
        self.context = await chromium.new_context(service_workers="block")
        self.page = await self.context.new_page()
        self.release_response = asyncio.Event()
        self.http_status = 200
        self.reply = {
            "status_code": 0, "aweme_id": "1234567890123456789", "unpersisted_body": "sensitive fixture"
        }

        async def route_request(route):
            if route.request.method == "POST" and "/aweme/create_v2/" in route.request.url:
                await self.release_response.wait()
                await route.fulfill(status=self.http_status, json=self.reply)
            else:
                await route.fulfill(content_type="text/html", body="""<button id="send">test only</button>
                    <script>document.querySelector('#send').onclick = () =>
                        fetch('/web/api/media/aweme/create_v2/?secret=do-not-store', {method:'POST'});</script>""")

        await self.context.route("**/*", route_request)
        await self.page.goto("https://creator.douyin.com/creator-micro/content/post/video")
        state = self.worker.store.state()
        self.group = state["groups"][0]
        binding = next(row for row in state["bindings"]
                       if row["platform"] == "douyin" and row["group_id"] == self.group["id"])
        self.binding = binding["id"]
        self.worker.store.bind(self.binding, "隔离验收", "isolated-proof")

        async def open_page(binding, **_):
            self.assertEqual(binding["id"], self.binding)
            browser.contexts[self.binding] = self.context
            return self.page

        async def identity(_page, _binding):
            return {"proof": "isolated-proof"}

        async def publish(page, binding, task, before_submit, **_):
            await before_submit()
            await page.locator("#send").click()
            return True

        browser.open = open_page
        browser.identity = identity
        publisher = patch("browser.publish_browser", publish)
        publisher.start()
        self.addCleanup(publisher.stop)

    def enqueue(self, batch):
        self.worker.store.enqueue(batch, self.group["id"], [self.binding], "隔离验收",
                                  "", "无需添加自主声明", self.media, self.media.name)
        return self.worker.store.next_task()

    def diagnostics(self, task):
        return " ".join(row["detail"] for row in self.worker.store.task_diagnostics(task["id"]))

    async def test_timeout_preserves_browser_then_late_receipt_closes_it(self):
        task = self.enqueue("late-confirmation")
        with patch("browser.DOUYIN_RECEIPT_SECONDS", 0.25):
            await self.worker.run_task(task)
        self.assertEqual(self.worker.store.task(task["id"])["status"], "needs_review")
        self.assertFalse(self.page.is_closed())
        with self.assertRaisesRegex(ValueError, "保留的发布窗口"):
            await self.worker.dispatch("tasks.delete", {"id": task["id"]})
        self.assertIn("POST /web/api/media/aweme/create_v2/", self.diagnostics(task))
        self.assertIn("等待明确回执超时", self.diagnostics(task))
        self.assertNotIn("do-not-store", self.diagnostics(task))
        other = self.enqueue("must-not-replace-browser")
        await self.worker.run_task(other)
        self.assertEqual(self.worker.store.task(other["id"])["status"], "action_required")
        self.assertFalse(self.page.is_closed())

        followups = tuple(self.worker.followups)
        self.release_response.set()
        await asyncio.wait_for(asyncio.gather(*followups), timeout=8)
        result = self.worker.store.task(task["id"])
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(result["receipt"], self.reply["aweme_id"])
        self.assertTrue(self.page.is_closed())
        self.assertIn("HTTP 200 · 业务码 0 · 作品回执", self.diagnostics(task))
        self.assertNotIn("sensitive fixture", self.diagnostics(task))

    async def test_explicit_platform_rejection_is_recorded_and_closes_browser(self):
        self.reply = {"status_code": 83}
        self.release_response.set()
        task = self.enqueue("platform-rejection")
        with patch("browser.DOUYIN_RECEIPT_SECONDS", 8):
            await self.worker.run_task(task)
        self.assertEqual(self.worker.store.task(task["id"])["status"], "failed")
        self.assertTrue(self.page.is_closed())
        self.assertIn("HTTP 200 · 业务码 83", self.diagnostics(task))

    async def test_zero_without_id_refreshes_manager_and_picks_only_new_exact_title(self):
        self.reply = {"status_code": 0}
        self.release_response.set()
        task = self.enqueue("manager-refresh")
        expected_id = "1234567890123456789"
        readbacks = 0
        verifying = asyncio.Event()

        async def manager(route):
            await route.fulfill(content_type="text/html", body="<script>fetch('/janus/douyin/creator/pc/work_list')</script>")

        async def work_list(route):
            nonlocal readbacks
            readbacks += 1
            self.assertEqual(route.request.method, "GET")
            self.assertEqual(self.worker.store.task(task["id"])["status"], "verifying")
            verifying.set()
            rows = [{"aweme_id": "2234567890123456789", "desc": "隔离验收", "create_time": int(time()) - 3600},
                    {"aweme_id": "3234567890123456789", "desc": "隔离验收续集", "create_time": int(time())}]
            if readbacks > 1:
                rows.append({"aweme_id": expected_id, "desc": "隔离验收\n本次作品", "create_time": int(time())})
            await route.fulfill(json={"status_code": 0, "aweme_list": rows})

        await self.context.route("**/creator-micro/content/manage", manager)
        await self.context.route("**/janus/douyin/creator/pc/work_list", work_list)
        with patch("browser.DOUYIN_RECEIPT_SECONDS", 8), patch("browser.DOUYIN_REFRESH_SECONDS", 0.2), \
             patch("browser.DOUYIN_LIST_WAIT_SECONDS", 0.15):
            running = asyncio.create_task(self.worker.run_task(task))
            await asyncio.wait_for(verifying.wait(), timeout=5)
            self.assertFalse(self.page.is_closed())
            await running
        saved = self.worker.store.task(task["id"])
        self.assertEqual(readbacks, 2)
        self.assertEqual((saved["status"], saved["receipt"]), ("submitted", expected_id))
        self.assertTrue(self.page.is_closed())
        self.assertIn("抖音作品管理已匹配本次投稿", self.diagnostics(task))

    async def test_http_error_does_not_resolve_a_submission(self):
        self.http_status = 502
        self.reply = {"message": "isolated gateway error"}
        self.release_response.set()
        task = self.enqueue("ambiguous-response")
        with patch("browser.DOUYIN_RECEIPT_SECONDS", 1):
            await self.worker.run_task(task)
        self.assertEqual(self.worker.store.task(task["id"])["status"], "needs_review")
        self.assertFalse(self.page.is_closed())
        self.assertIn("HTTP 502 · 没有有效作品回执", self.diagnostics(task))
        followups = tuple(self.worker.followups)
        await self.page.close()
        await asyncio.wait_for(asyncio.gather(*followups), timeout=8)
        self.assertEqual(self.worker.store.task(task["id"])["status"], "needs_review")
        self.assertIn("未得到明确回执", self.diagnostics(task))

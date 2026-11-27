import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from playwright.async_api import async_playwright

from adapters import publish_browser
from catalog import PLATFORMS
import session_backup

PAGE_ACCOUNT = """() => {
    const visible = (el) => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
    const login = [...document.querySelectorAll('input[placeholder*="手机号"], input[type="password"], main#login-form, .login-box-container, #dologin')].some(visible);
    const account = [...document.querySelectorAll('[class*=user-name], [class*=nickname], [class*=userName], [class*=nickName]')]
        .filter(visible).map(el => (el.textContent || '').trim()).find(name => name.length && name.length <= 40);
    return { login, name: account || '' };
}"""
XHS_PROOF_PREFIX = "xhs-user:"
XHS_WEB_HOME = "https://www.xiaohongshu.com/explore"
DOUYIN_RECEIPT_SECONDS = 120
DOUYIN_MANAGER = "https://creator.douyin.com/creator-micro/content/manage"
DOUYIN_WORK_LIST = "/janus/douyin/creator/pc/work_list"
DOUYIN_REFRESH_SECONDS = 6
DOUYIN_LIST_WAIT_SECONDS = 3


def xhs_user_proof(body, successful):
    if not successful or not isinstance(body, dict) or body.get("success") is not True or body.get("code") != 0:
        return None
    data = body.get("data")
    user_id = data.get("user_id") if isinstance(data, dict) and data.get("guest") is False else None
    if not isinstance(user_id, str) or not re.fullmatch(r"[a-fA-F0-9]{24}", user_id):
        return None
    return XHS_PROOF_PREFIX + hashlib.sha256(f"xiaohongshu\0{user_id}".encode()).hexdigest()


def cookie_proof(platform, value):
    return hashlib.sha256(f"{platform}\0{value}".encode()).hexdigest()


def submission_response(platform, method, url):
    parts = urlparse(url)
    if parts.scheme != "https" or method != "POST":
        return False
    path = parts.path.rstrip("/")
    if platform == "douyin":
        return parts.hostname == "creator.douyin.com" and path in {
            "/web/api/media/aweme/create", "/web/api/media/aweme/create_v2", "/aweme/v1/web/aweme/post",
        }
    if platform == "xiaohongshu":
        hosts = PLATFORMS[platform].hosts | {"edith.xiaohongshu.com", "edith.rednote.com"}
        return parts.hostname in hosts and path in {"/web_api/sns/v2/note", "/api/galaxy/creator/note/v2/note"}
    return platform == "bilibili" and parts.hostname == "member.bilibili.com" and path in {"/x/vu/web/add", "/x/vu/web/add/v3"}


def receipt_from_json(platform, body):
    if not isinstance(body, dict):
        return None
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    if platform == "douyin":
        value = body.get("aweme_id") or data.get("aweme_id")
        accepted = body.get("status_code") == 0
    elif platform == "xiaohongshu":
        value = data.get("note_id") or data.get("noteId") or body.get("note_id")
        if not value and isinstance(data.get("id"), str) and re.fullmatch(r"[a-fA-F0-9]{24}", data["id"]):
            value = data["id"]
        accepted = body.get("success") is True and body.get("code") in (0, None)
    elif platform == "bilibili":
        value = data.get("bvid") or data.get("aid")
        accepted = body.get("code") == 0
    else:
        return None
    value = str(value or "")
    return value if accepted and re.fullmatch(r"[A-Za-z0-9_-]{3,100}", value) else None


class DouyinRejected(ValueError):
    pass


@dataclass(frozen=True)
class DouyinListedWork:
    receipt: str


def douyin_matching_works(body, title, submitted_at):
    if not isinstance(body, dict) or body.get("status_code") != 0:
        return set()
    works = body.get("aweme_list")
    if not isinstance(works, list):
        return set()
    matches = set()
    for work in works:
        if not isinstance(work, dict):
            continue
        ident = work.get("aweme_id")
        created = work.get("create_time")
        if not isinstance(ident, str) or not re.fullmatch(r"\d{15,25}", ident):
            continue
        if type(created) is not int or not int(submitted_at) <= created <= time.time() + 5:
            continue
        titles = (work.get("item_title"), work.get("caption"), work.get("desc"))
        if any(isinstance(text, str) and text.partition("\n")[0].strip() == title for text in titles):
            matches.add(ident)
    return matches


@dataclass
class RetainedDouyin:
    task_id: str
    page: object
    result: asyncio.Future


class DouyinReceipt:
    """Track submission traffic on the publish page without storing secrets."""

    def __init__(self, page, record):
        self.page = page
        self.record = record
        self.armed = False
        self.submitted_at = None
        self.check_list = asyncio.Event()
        self.requests = {}
        self.readings = set()
        self.result = asyncio.get_running_loop().create_future()
        self.listeners = {
            "request": self.request,
            "requestfailed": self.request_failed,
            "response": self.response,
            "framenavigated": self.navigated,
            "close": self.closed,
        }
        for event, listener in self.listeners.items():
            page.on(event, listener)

    def request(self, request):
        if not self.armed or not submission_response("douyin", request.method, request.url):
            return None
        if request not in self.requests:
            if self.submitted_at is None:
                self.submitted_at = time.time()
            self.requests[request] = len(self.requests) + 1
            self.record(f"抖音请求 #{self.requests[request]} · POST {urlparse(request.url).path}")
        return self.requests[request]

    def request_failed(self, request):
        number = self.request(request)
        if number is not None:
            failure = re.search(r"net::ERR_[A-Z0-9_]+", request.failure or "")
            detail = f"（{failure[0]}）" if failure else ""
            self.record(f"抖音请求 #{number} 传输失败{detail}。")

    def response(self, response):
        number = self.request(response.request)
        if number is not None:
            self.record(f"抖音请求 #{number} 收到 HTTP {response.status}，正在读取回执。")
            reading = asyncio.create_task(self.parse(response, number))
            self.readings.add(reading)
            reading.add_done_callback(self.readings.discard)

    def navigated(self, frame):
        if self.submitted_at is not None and frame == self.page.main_frame:
            url = urlparse(frame.url)
            if url.scheme == "https" and url.hostname == "creator.douyin.com" and url.path.rstrip("/") == urlparse(DOUYIN_MANAGER).path:
                self.check_list.set()

    async def parse(self, response, number):
        try:
            body = await response.json()
        except Exception:
            body = None
        code = body.get("status_code") if isinstance(body, dict) else None
        code = code if type(code) is int and abs(code) < 10**12 else None
        receipt = receipt_from_json("douyin", body) if response.ok and code == 0 else None
        fields = [f"抖音响应 #{number}", f"HTTP {response.status}"]
        if code is not None:
            fields.append(f"业务码 {code}")
        fields.append(f"作品回执 {receipt}" if receipt else "没有有效作品回执")
        self.record(" · ".join(fields))
        if self.result.done():
            return
        if receipt:
            self.result.set_result(receipt)
        elif response.ok and code == 0:
            self.check_list.set()
        elif response.ok and code not in (None, 0) and len(self.requests) == 1:
            self.result.set_result(DouyinRejected(f"抖音拒绝了本次提交（业务码 {code}）。"))

    def closed(self, _page):
        if not self.result.done():
            self.result.set_result(None)
        self.detach()

    def detach(self):
        for event, listener in self.listeners.items():
            self.page.remove_listener(event, listener)
        for reading in tuple(self.readings):
            reading.cancel()


def home_url(binding):
    spec = PLATFORMS[binding["platform"]]
    if spec.mode == "custom_browser":
        return binding.get("settings", {}).get("website_url", "")
    return spec.home


def allowed_hosts(binding):
    spec = PLATFORMS[binding["platform"]]
    if spec.mode == "custom_browser":
        return {urlparse(home_url(binding)).hostname} - {None}
    return spec.hosts


class Browser:
    def __init__(self, profiles, *, headless=False):
        self.profiles = profiles
        self.headless = headless
        self.playwright = None
        self.patchright = None
        self.contexts = {}
        self.xhs_accounts = {}
        self.retained = {}
        self.start_lock = asyncio.Lock()

    async def scoped_cookies(self, context, binding):
        spec = PLATFORMS[binding["platform"]]
        hosts = allowed_hosts(binding) | set(spec.cookie_scopes)
        return await context.cookies([home_url(binding), *[f"https://{host}/" for host in sorted(hosts)]])

    async def save_session(self, binding, page):
        cookies = await self.scoped_cookies(page.context, binding)
        await asyncio.to_thread(session_backup.save, self.profiles / binding["id"], binding["id"], cookies)

    async def observe_xhs_account(self, context, response):
        url = urlparse(response.url)
        if (url.scheme != "https" or url.hostname not in {"edith.xiaohongshu.com", "edith.rednote.com"}
                or url.path.rstrip("/") != "/api/sns/web/v2/user/me" or response.request.method != "GET"):
            return
        try:
            header = await response.request.header_value("cookie") or ""
            token = re.search(r"(?:^|;\s*)web_session=([^;]+)", header)
            proof = xhs_user_proof(await response.json(), response.ok)
            if token and proof and context in self.contexts.values():
                self.xhs_accounts[context] = (cookie_proof("xiaohongshu", token[1]), proof)
        except Exception:
            return

    async def launch(self, binding, *, douyin_video=False, headless=None, service_workers="allow"):
        async with self.start_lock:
            if douyin_video:
                if self.patchright is None:
                    from patchright.async_api import async_playwright as async_patchright
                    self.patchright = await async_patchright().start()
                driver = self.patchright
            else:
                if self.playwright is None:
                    self.playwright = await async_playwright().start()
                driver = self.playwright
        profile = self.profiles / binding["id"]
        profile.mkdir(parents=True, exist_ok=True)
        # Use installed Chrome and an app-owned directory with normal browser settings.
        context = await driver.chromium.launch_persistent_context(str(profile), channel="chrome",
                                                                  headless=self.headless if headless is None else headless,
                                                                  service_workers=service_workers, timeout=25000)
        self.contexts[binding["id"]] = context
        context.on("close", lambda _: self.contexts.pop(binding["id"], None)
                   if self.contexts.get(binding["id"]) is context else None)
        if binding["platform"] == "xiaohongshu":
            async def observe(response):
                await self.observe_xhs_account(context, response)
            context.on("response", observe)
            context.on("close", lambda _: self.xhs_accounts.pop(context, None))
        if binding["session_proof"]:
            try:
                auth = PLATFORMS[binding["platform"]].auth
                current = await self.scoped_cookies(context, binding)
                if not any(cookie["name"] in auth and cookie["value"] for cookie in current):
                    saved = await asyncio.to_thread(session_backup.load, profile, binding["id"])
                    fresh = [cookie for cookie in saved if cookie["expires"] == -1 or cookie["expires"] > time.time()]
                    if fresh:
                        await context.add_cookies(fresh)
            except Exception as exc:
                logging.warning("Could not restore local session backup (%s)", type(exc).__name__)
        page = context.pages[0] if context.pages else await context.new_page()
        return context, page

    async def open(self, binding, *, manage=False, douyin_video=False):
        context = self.contexts.get(binding["id"])
        if context and context.pages:
            page = context.pages[0]
        else:
            context, page = await self.launch(binding, douyin_video=douyin_video)
        spec = PLATFORMS[binding["platform"]]
        try:
            await page.goto(home_url(binding), wait_until="domcontentloaded", timeout=30000)
            if manage and spec.manage and urlparse(page.url).hostname in allowed_hosts(binding):
                current = urlparse(page.url)
                await page.goto(f"{current.scheme}://{current.netloc}{spec.manage}",
                                wait_until="domcontentloaded", timeout=30000)
            await page.bring_to_front()
            return page
        except Exception:
            await self.close(binding["id"])
            raise

    async def active_page(self, binding):
        context = self.contexts.get(binding["id"])
        if not context or not context.pages:
            raise ValueError("请先打开登录窗口，并在平台页面完成扫码。")
        candidates = [p for p in context.pages if urlparse(p.url).hostname in allowed_hosts(binding)]
        return candidates[-1] if candidates else context.pages[-1]

    async def identity(self, page, binding):
        platform = binding["platform"]
        settings = PLATFORMS[platform]
        parsed = urlparse(page.url)
        hosts = allowed_hosts(binding)
        if platform == "xiaohongshu":
            hosts = hosts | {"www.xiaohongshu.com"}
        if parsed.hostname not in hosts or parsed.scheme != "https" or re.search(r"/(?:log[-_]?in|sign[-_]?in|passport|checkpoint|authwall)", parsed.path):
            return None
        urls = [page.url, f"https://{parsed.netloc}/", *[f"https://{host}/" for host in settings.cookie_scopes]]
        cookies = await page.context.cookies(urls)
        values = {cookie["name"]: cookie["value"] for cookie in cookies if cookie["value"]}
        auth = next((values[key] for key in settings.auth if key in values), None)
        if not auth:
            return None
        view = await page.evaluate(PAGE_ACCOUNT)
        if platform == "xiaohongshu":
            legacy = cookie_proof(platform, auth)
            account = self.xhs_accounts.get(page.context)
            if account and account[0] == legacy:
                return {"proof": legacy, "account_proof": account[1], "name": view["name"]}
            if binding.get("account_proof"):
                return None
        if view["login"]:
            return None
        identity = next((values[key] for key in settings.identity if key in values), auth)
        if platform in ("youtube", "blogger"):
            pattern = r"/channel/(UC[A-Za-z0-9_-]+)" if platform == "youtube" else r"/blog/(?:posts|post/edit|settings)/(\d+)"
            profile = re.search(pattern, parsed.path)
            if not profile:
                return None
            identity = profile.group(1)
        proof = cookie_proof(platform, identity)
        return {"proof": proof, "name": view["name"]}

    async def reconcile_douyin(self, page, binding, title, watch, progress):
        await watch.check_list.wait()
        if watch.result.done():
            return
        progress("抖音已响应，正在刷新作品管理并核对本次投稿。")
        manager = None
        try:
            manager = await page.context.new_page()

            async def allow_reads(route):
                if route.request.method in {"GET", "HEAD", "OPTIONS"}:
                    await route.fallback()
                else:
                    await route.abort()

            await manager.route("**/*", allow_reads)
            responses = []

            def observe(response):
                url = urlparse(response.url)
                if (response.ok and response.request.method == "GET" and url.scheme == "https"
                        and url.hostname == "creator.douyin.com" and url.path.rstrip("/") == DOUYIN_WORK_LIST):
                    responses.append(response)

            manager.on("response", observe)
            while not watch.result.done():
                responses.clear()
                try:
                    options = {"wait_until": "domcontentloaded", "timeout": 12000}
                    if manager.url == DOUYIN_MANAGER:
                        await manager.reload(**options)
                    else:
                        await manager.goto(DOUYIN_MANAGER, **options)
                    await asyncio.sleep(DOUYIN_LIST_WAIT_SECONDS)
                    identity = await self.identity(manager, binding)
                    if not identity or identity["proof"] != binding["session_proof"]:
                        watch.record("抖音作品管理页未能核对原绑定账号，已停止自动核对。")
                        return
                    matched = set()
                    for response in list(responses):
                        try:
                            body = await response.json()
                        except Exception:
                            continue
                        matched.update(douyin_matching_works(body, title, watch.submitted_at))
                    if len(matched) > 1:
                        watch.record("抖音作品列表有多条符合提交时间的同名作品，需人工确认。")
                        return
                    if matched and not watch.result.done():
                        receipt = matched.pop()
                        watch.record(f"抖音作品管理已匹配本次投稿 · 作品回执 {receipt}")
                        watch.result.set_result(DouyinListedWork(receipt))
                        return
                except Exception:
                    if manager.is_closed():
                        return
                await asyncio.sleep(DOUYIN_REFRESH_SECONDS)
        except Exception:
            watch.record("抖音作品管理自动核对未能启动，继续等待提交回执。")
        finally:
            if manager and not manager.is_closed():
                try:
                    await manager.close()
                except Exception:
                    pass

    async def publish_douyin(self, page, binding, task, before_submit, record, progress):
        watch = DouyinReceipt(page, record)
        retained = False
        checking = None
        try:
            async def arm():
                await before_submit()
                watch.armed = True
                record("准备点击抖音发布，开始监听提交请求。")

            try:
                await publish_browser(page, binding, task, arm)
            except Exception:
                if not watch.armed:
                    raise
                record("抖音发布按钮操作未正常返回，继续核对是否已发出请求。")

            if not watch.armed:
                return None
            if title := task.get("title", "").strip():
                checking = asyncio.create_task(self.reconcile_douyin(page, binding, title, watch, progress))
            try:
                result = await asyncio.wait_for(asyncio.shield(watch.result), timeout=DOUYIN_RECEIPT_SECONDS)
            except TimeoutError:
                record(f"等待明确回执超时（{DOUYIN_RECEIPT_SECONDS:g} 秒，观察到 {len(watch.requests)} 条提交请求）。")
                if not page.is_closed():
                    held = RetainedDouyin(task.get("id", ""), page, watch.result)
                    self.retained[binding["id"]] = held
                    page.once("close", lambda _: self.retained.pop(binding["id"], None)
                              if self.retained.get(binding["id"]) is held else None)
                    retained = True
                    return held
                return None
            if isinstance(result, DouyinRejected):
                raise result
            return result
        finally:
            if checking is not None:
                checking.cancel()
                await asyncio.gather(checking, return_exceptions=True)
            if not retained:
                watch.detach()

    async def publish(self, page, binding, task, before_submit, *, progress=None, record=None):
        platform = binding["platform"]
        if platform == "douyin":
            return await self.publish_douyin(page, binding, task, before_submit,
                                             record or (lambda _detail: None), progress or (lambda _detail: None))
        receipt = None
        armed = False
        replies = set()
        loop = asyncio.get_running_loop()
        pending_receipt = loop.create_future()

        async def parse(response):
            if response.ok:
                try:
                    candidate = receipt_from_json(platform, await response.json())
                except Exception:
                    return
                if candidate and not pending_receipt.done():
                    pending_receipt.set_result(candidate)

        def observe(response):
            if armed and submission_response(platform, response.request.method, response.url):
                reading = asyncio.create_task(parse(response))
                replies.add(reading)
                reading.add_done_callback(replies.discard)

        async def arm():
            nonlocal armed
            await before_submit()
            armed = True

        page.on("response", observe)
        try:
            clicked = await publish_browser(page, binding, task, arm, progress=progress)
            if clicked == "draft":
                return "draft"
            if armed and platform in {"xiaohongshu", "bilibili"}:
                try:
                    receipt = await asyncio.wait_for(pending_receipt, timeout=10 if clicked else 4)
                except TimeoutError:
                    pass
            return receipt
        finally:
            page.remove_listener("response", observe)
            for reading in tuple(replies):
                reading.cancel()

    async def close(self, binding_id, *, review_task=None, force=False):
        held = self.retained.get(binding_id)
        if held and not force and review_task != held.task_id:
            return
        self.retained.pop(binding_id, None)
        context = self.contexts.pop(binding_id, None)
        if context:
            try:
                await context.close()
            except Exception:
                pass

    async def shutdown(self):
        await asyncio.gather(*(self.close(key, force=True) for key in tuple(self.contexts)))
        if self.playwright:
            await self.playwright.stop()
        if self.patchright:
            await self.patchright.stop()

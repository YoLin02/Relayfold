"""Read the official Xiaohongshu chat UI on explicit user actions."""

import re
from contextlib import asynccontextmanager
from time import time
from urllib.parse import urlsplit

from playwright.async_api import TimeoutError as BrowserTimeout

from browser import XHS_WEB_HOME
import session_backup

CHAT = "https://www.xiaohongshu.com/chat"
CACHE = "private-messages.dat"
CONVERSATION_ID = re.compile(r"[A-Za-z0-9_.:-]{1,120}")
ROWS = ".xhs-im-conv-item[data-conv-id]"
PERSONAL_ROWS = '.xhs-im-conv-item:is([data-conv-kind="c2c"], [data-conv-kind="stranger-folder"])'
EMPTY_LIST = ".xhs-im-conv-list__empty, .xhs-im-conv-list__empty-text"
MESSAGES = ".xhs-im-msg-list [data-message-id]"
MESSAGE_WINDOW = ".xhs-im-chat-window"

CONVERSATION_ROWS = r"""elements => elements.map(row => {
    const text = selector => row.querySelector(selector)?.textContent?.trim() ?? '';
    const badge = text('.xhs-im-conv-item__bottom-right [class*="unread"], .xhs-im-conv-item__bottom-right [class*="badge"]')
        || text('.xhs-im-conv-item__bottom-right');
    return {id: row.dataset.convId, kind: row.dataset.convKind,
        name: text('.xhs-im-conv-item__name').slice(0, 100),
        preview: text('.xhs-im-conv-item__summary-text').slice(0, 250),
        time: text('.xhs-im-conv-item__time').slice(0, 40),
        unread: /^\d+\+?$/.test(badge) ? Math.min(parseInt(badge), 999) : 0};
})"""

CHAT_ROWS = """elements => elements.map(row => {
    const text = selector => row.querySelector(selector)?.textContent?.trim() ?? '';
    const bubble = row.querySelector('.chat-item__bubble');
    const note = text('.xhs-im-bubble-card-note-title');
    const direction = row.querySelector('.chat-item__content--right') ? 'out'
        : row.querySelector('.chat-item__content--left') ? 'in' : 'system';
    let type = 'text';
    let body = text('.xhs-im-bubble__text');
    if (note) { type = 'note'; body = note; }
    else if (bubble?.classList.contains('chat-item__bubble--image')) { type = 'image'; body = '图片'; }
    else if (!body) { body = text('.xhs-im-hint__text') || bubble?.textContent?.trim() || '附件消息'; }
    let previous = row.previousElementSibling;
    while (previous && !previous.classList.contains('xhs-im-msg-list__time-divider')) previous = previous.previousElementSibling;
    return {id: row.dataset.messageId || row.dataset.storeId, direction, type,
        body: body.slice(0, 4000), time: (previous?.textContent?.trim() ?? '').slice(0, 60)};
})"""


class PrivateMessages:
    def __init__(self, browser, profiles, lock, identity):
        self.browser = browser
        self.profiles = profiles
        self.lock = lock
        self.identity = identity

    def load(self, binding_id):
        try:
            saved = session_backup.load(self.profiles / binding_id, binding_id, CACHE)
            return saved if isinstance(saved, dict) else {"conversations": [], "threads": {}, "drafts": {}, "synced_at": None}
        except (OSError, ValueError) as exc:
            raise ValueError("无法读取此账号的加密私信缓存。") from exc

    def save(self, binding_id, data):
        folder = self.profiles / binding_id
        try:
            folder.mkdir(parents=True, exist_ok=True)
            session_backup.save(folder, binding_id, data, CACHE)
        except OSError as exc:
            raise ValueError("无法保存此账号的加密私信缓存。") from exc

    @asynccontextmanager
    async def inbox(self, binding):
        binding_id = binding["id"]
        lock = self.lock(binding_id)
        if lock.locked() or binding_id in self.browser.contexts:
            raise ValueError("这个账号有其他任务或网页窗口打开，请稍后重试。")
        if binding["login_status"] not in {"ready", "saved"} or not binding["account_proof"]:
            raise ValueError("请先在「平台账号」验证这个小红书账号。")
        async with lock:
            try:
                _, page = await self.browser.launch(binding, headless=True)
                await page.goto(XHS_WEB_HOME, wait_until="domcontentloaded", timeout=18000)
                identity = await self.identity(binding, page)
                if not identity or identity.get("account_proof") != binding["account_proof"]:
                    raise ValueError("小红书网页身份与绑定账号不一致或暂未核对成功，请重新验证。")
                try:
                    await page.wait_for_function(
                        """url => [...document.querySelectorAll('a[href]')].some(a =>
                            a.getClientRects().length && [url, url + '/'].includes(a.origin + a.pathname))""",
                        arg=CHAT, timeout=4500)
                except BrowserTimeout:
                    raise ValueError("当前账号的网页未显示「消息」入口，暂时无法同步私信。") from None
                await page.goto(CHAT, wait_until="domcontentloaded", timeout=18000)
                url = urlsplit(page.url)
                if url.scheme != "https" or url.hostname != "www.xiaohongshu.com" or url.path.rstrip("/") != "/chat":
                    raise ValueError("小红书要求重新登录或验证，请在「平台账号」处理。")
                await page.locator(".xhs-im-conv-list__scroll").wait_for(timeout=10000)
                await page.locator(f"{ROWS}, {EMPTY_LIST}").first.wait_for(timeout=10000)
                yield page
            except BrowserTimeout:
                raise ValueError("小红书私信页面加载超时，请稍后手动重试。") from None
            finally:
                await self.browser.close(binding_id)

    async def sync(self, binding):
        async with self.inbox(binding) as page:
            try:
                # Group conversations can render before the private inbox has arrived.
                await page.locator(f"{PERSONAL_ROWS}, {EMPTY_LIST}").first.wait_for(timeout=7500)
                personal_pending = False
            except BrowserTimeout:
                personal_pending = True
            rows = await page.locator(ROWS).evaluate_all(CONVERSATION_ROWS)
        items = {row["id"]: row for row in rows
                 if CONVERSATION_ID.fullmatch(row["id"] or "") and row["name"] and row["kind"] in {"c2c", "group"}}
        binding_id = binding["id"]
        cached = self.load(binding_id)
        if personal_pending:
            for row in cached["conversations"]:
                if row["kind"] == "c2c":
                    items.setdefault(row["id"], row)
        cached.update(conversations=list(items.values())[:150], synced_at=int(time()), personal_pending=personal_pending)
        self.save(binding_id, cached)
        return self.summary(cached)

    @staticmethod
    def summary(cache):
        return {"conversations": cache["conversations"], "synced_at": cache["synced_at"],
                "personal_pending": cache.get("personal_pending", False)}

    @staticmethod
    def conversation(cache, identifier):
        if not isinstance(identifier, str) or not CONVERSATION_ID.fullmatch(identifier):
            raise ValueError("请选择有效的私信会话。")
        item = next((row for row in cache["conversations"] if row["id"] == identifier), None)
        if not item:
            raise ValueError("这个会话不在当前账号的收件箱，请先同步会话。")
        return item

    async def thread(self, binding, identifier, older):
        binding_id = binding["id"]
        cached = self.load(binding_id)
        self.conversation(cached, identifier)
        previous = cached["threads"].get(identifier)
        if older and not previous:
            raise ValueError("请先打开这个聊天，再加载更早消息。")
        async with self.inbox(binding) as page:
            row = page.locator(f'{ROWS}[data-conv-id="{identifier}"]')
            try:
                await row.first.wait_for(timeout=8000)
            except BrowserTimeout:
                raise ValueError("网页中找不到这个会话，请先同步会话并重新选择。")
            if await row.count() != 1:
                raise ValueError("网页中无法唯一定位这个会话，请先同步会话。")
            await row.click(timeout=6000)
            await row.and_(page.locator(".xhs-im-conv-item--active")).wait_for(timeout=6000)
            await page.locator(MESSAGE_WINDOW).wait_for(timeout=8000)
            await page.wait_for_function("""() => !!document.querySelector(
                '.xhs-im-msg-list [data-message-id], .xhs-im-msg-list__empty, .xhs-im-chat-window__empty')""", timeout=8500)
            list_view = page.locator(".xhs-im-msg-list")
            messages = page.locator(MESSAGES)
            eligible_for_older = await list_view.evaluate("el => el.scrollHeight > el.clientHeight + 1")
            reached_end = False
            if older:
                boundary = previous["messages"][0]["id"] if previous["messages"] else ""
                for _ in range(3):
                    first_id = await messages.first.get_attribute("data-message-id") if await messages.count() else ""
                    await list_view.evaluate("el => { el.scrollTop = 0; }")
                    try:
                        await page.wait_for_function(
                            """first => document.querySelector('.xhs-im-msg-list [data-message-id]')?.dataset.messageId !== first""",
                            arg=first_id, timeout=2200)
                    except BrowserTimeout:
                        reached_end = True
                        break
                    current = await messages.evaluate_all("items => items.map(el => el.dataset.messageId || el.dataset.storeId)")
                    if boundary in current and current.index(boundary) > 0:
                        break
                eligible_for_older = not reached_end
            reading = await messages.evaluate_all(CHAT_ROWS)
            if await row.and_(page.locator(".xhs-im-conv-item--active")).count() != 1:
                raise ValueError("网页当前会话已变化，请重新选择。")
            unread = (await row.evaluate_all(CONVERSATION_ROWS))[0]["unread"]
        recent = list({item["id"]: item for item in reading if item["id"]}.values())
        if older:
            old_ids = {item["id"] for item in previous["messages"]}
            first_known = next((index for index, item in enumerate(recent) if item["id"] in old_ids), None)
            recent = recent[:first_known] + previous["messages"] if first_known is not None else previous["messages"]
        thread = {"messages": recent[:160] if older else recent[-60:],
                  "has_older": eligible_for_older and len(recent) < 160,
                  "synced_at": int(time()), "unread": unread}
        # Re-read after the browser awaits so a draft saved during loading is retained.
        cached = self.load(binding_id)
        cached["threads"].pop(identifier, None)
        cached["threads"][identifier] = thread
        cached["threads"] = dict(list(cached["threads"].items())[-25:])
        self.conversation(cached, identifier)["unread"] = unread
        self.save(binding_id, cached)
        return thread

    async def command(self, method, binding, args):
        if method == "messages.sync":
            return await self.sync(binding)
        binding_id = binding["id"]
        cached = self.load(binding_id)
        if method == "messages.snapshot":
            return self.summary(cached)
        identifier = self.conversation(cached, args.get("conversation_id"))["id"]
        if method == "messages.cachedThread":
            return cached["threads"].get(identifier)
        if method == "messages.thread":
            return await self.thread(binding, identifier, args.get("older") is True)
        if method == "messages.draft":
            return cached["drafts"].get(identifier, "")
        body = args.get("body")
        if not isinstance(body, str) or len(body) > 4000:
            raise ValueError("请输入最多 4000 字的本地私信草稿。")
        if body.strip():
            cached["drafts"][identifier] = body
        else:
            cached["drafts"].pop(identifier, None)
        self.save(binding_id, cached)

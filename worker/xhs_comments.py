import asyncio
import logging
import re
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlencode, urlsplit

from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout

from browser import xhs_user_proof
from comment_cache import cover_address


HOST = "www.xiaohongshu.com"
ORIGIN = f"https://{HOST}"
API = "edith.xiaohongshu.com"
COMMENTS = "/api/sns/web/v2/comment/page"
SUB_COMMENTS = "/api/sns/web/v2/comment/sub/page"
MENTIONS = "/api/sns/web/v1/you/mentions"
REPLY = "/api/sns/web/v1/comment/post"
IDENTIFIER = re.compile(r"[a-fA-F0-9]{24}")
DELETED_NOTE_MESSAGE = re.compile(r"(?:该|这篇)?笔记(?:已(?:被)?删除|不存在)[。！!]?$")

NOTE_CARDS = r"""cards => cards.map(card => {
    const title = card.querySelector('a.title');
    const cover = card.querySelector('a.cover');
    const link = card.querySelector('a[href^="/explore/"], a[href^="/discovery/item/"]');
    const image = cover?.querySelector('img') || card.querySelector('img');
    const background = cover && getComputedStyle(cover).backgroundImage.match(/^url\(["']?(.*?)["']?\)$/)?.[1];
    const hrefs = [...new Set([title?.href, cover?.href, link?.href].filter(Boolean))];
    const covers = [image?.currentSrc, image?.getAttribute('data-src'), image?.getAttribute('data-original'),
      image?.src, background].filter(value => value && URL.canParse(value, location.href))
      .map(value => new URL(value, location.href).href);
    return { id: (link || title || cover)?.pathname.split('/').at(-1), hrefs,
      title: title?.textContent.trim(), covers };
})"""


def trusted_note(address, note_id, owner):
    url = urlsplit(address or "")
    return (url.scheme == "https" and url.netloc == HOST and url.path in {
        f"/user/profile/{owner}/{note_id}", f"/explore/{note_id}", f"/discovery/item/{note_id}",
    } and bool(parse_qs(url.query).get("xsec_token")))


def api_response(response, path):
    url = urlsplit(response.url)
    return url.scheme == "https" and url.netloc == API and url.path == path


def matching_comment_page(response, note_id):
    return (api_response(response, COMMENTS) and response.request.method == "GET"
            and parse_qs(urlsplit(response.url).query).get("note_id") == [note_id])


def matching_child_page(response, note_id, root_id):
    if not api_response(response, SUB_COMMENTS) or response.request.method != "GET":
        return False
    query = parse_qs(urlsplit(response.url).query)
    return query.get("note_id") == [note_id] and query.get("root_comment_id") == [root_id]


class NoteDeleted(ValueError):
    def __init__(self):
        super().__init__("小红书已确认这篇笔记不存在，本地列表已移除。")


def note_document_deleted(response, note_id, owner):
    return bool(response and response.status in {404, 410} and trusted_note(response.url, note_id, owner))


def text(value, limit):
    return value[:limit] if isinstance(value, str) else ""


def comment_author(item):
    info = item.get("user_info")
    return info if isinstance(info, dict) else {}


def has_owner_reply(item, owner):
    children = item.get("sub_comments")
    return isinstance(children, list) and any(
        isinstance(child, dict) and comment_author(child).get("user_id") == owner for child in children
    )


def comment_rows(items, owner):
    items = items if isinstance(items, list) else []
    comments = {}
    for item in items:
        if not isinstance(item, dict) or not IDENTIFIER.fullmatch(text(item.get("id"), 80)):
            continue
        author = comment_author(item)
        target = item.get("target_comment")
        comments[item["id"]] = {
            "id": item["id"], "author": text(author.get("nickname"), 80),
            "body": text(item.get("content"), 2000),
            "created_at": item.get("create_time") if isinstance(item.get("create_time"), int) else None,
            "by_owner": author.get("user_id") == owner,
            "reply_to": text(comment_author(target).get("nickname"), 80) if isinstance(target, dict) else "",
            "ip_location": text(item.get("ip_location"), 80),
        }
    return comments


def child_preview(item, owner):
    children = list(comment_rows(item.get("sub_comments"), owner).values())
    raw_count = str(item.get("sub_comment_count", ""))
    count = int(raw_count) if raw_count.isascii() and raw_count.isdecimal() and len(raw_count) < 10 else len(children)
    return {"children": children, "children_count": max(count, len(children)),
            "children_more": item.get("sub_comment_has_more") is True}


def incoming_comment(item, owner):
    if not isinstance(item, dict) or item.get("type") not in {"comment/item", "comment/comment"}:
        return None
    from_user, note, comment = (item.get(field) for field in ("user_info", "item_info", "comment_info"))
    if not all(isinstance(value, dict) for value in (from_user, note, comment)) or note.get("type") != "note_info":
        return None
    if from_user.get("userid") == owner:
        return None
    states = [record.get("illegal_info") for record in (note, comment)]
    if any(isinstance(state, dict) and state.get("illegal_status") not in (None, "", "NORMAL") for state in states):
        return None
    note_id, comment_id = text(note.get("id"), 80), text(comment.get("id"), 80)
    if not IDENTIFIER.fullmatch(note_id) or not IDENTIFIER.fullmatch(comment_id):
        return None
    target = comment.get("target_comment")
    target = target if isinstance(target, dict) else {}
    target_author = comment_author(target)
    follow_up = item["type"] == "comment/comment"
    recipient = target_author.get("userid") or target_author.get("user_id")
    if follow_up and recipient and recipient != owner:
        return None
    note_author = comment_author(note)
    author_id = note_author.get("userid") or note_author.get("user_id")
    note_is_mine = author_id == owner if author_id else (None if follow_up else True)
    token = text(note.get("xsec_token"), 1024)
    return {
        "kind": "follow_up" if follow_up else "comment",
        "note_id": note_id, "note_title": text(note.get("content"), 180) or "小红书笔记",
        "href": notification_note_link(note_id, token) if token else "", "note_is_mine": note_is_mine,
        "previous_id": text(target.get("id"), 80),
        "comment": {
            "id": comment_id, "author": text(from_user.get("nickname"), 80), "body": text(comment.get("content"), 2000),
            "created_at": item.get("time") if isinstance(item.get("time"), int) else None,
            "by_owner": False, "ip_location": text(comment.get("ip_location"), 80),
        },
    }


def notification_note_link(note_id, token=""):
    if not isinstance(note_id, str) or not IDENTIFIER.fullmatch(note_id):
        raise ValueError("原帖标识无效。")
    url = f"{ORIGIN}/explore/{note_id}"
    return f"{url}?{urlencode({'xsec_token': token, 'xsec_source': 'pc_notification'})}" if token else url


class XiaohongshuComments:
    def __init__(self, browser):
        self.browser = browser

    @asynccontextmanager
    async def open(self, binding, guard):
        if binding["id"] in self.browser.contexts:
            raise ValueError("这个账号还有一个平台窗口打开。关闭后再加载评论。")
        try:
            starting = asyncio.create_task(self.browser.launch(binding, headless=True, service_workers="block"))
            try:
                context, page = await asyncio.shield(starting)
            except asyncio.CancelledError:
                await asyncio.gather(starting, return_exceptions=True)
                raise
            await context.route("**/*", guard)
            async with page.expect_response(lambda r: api_response(r, "/api/sns/web/v2/user/me")
                                            and r.request.method == "GET", timeout=20000) as identity:
                await page.goto(f"{ORIGIN}/explore", wait_until="domcontentloaded", timeout=22000)
            response = await identity.value
            account = await response.json()
            if not binding.get("account_proof") or xhs_user_proof(account, response.ok) != binding["account_proof"]:
                raise ValueError("小红书网页会话无法匹配原账号。请检查这个账号的登录状态。")
            yield page, account["data"]["user_id"]
        finally:
            await self.browser.close(binding["id"])

    @staticmethod
    async def read_route(route):
        request = route.request
        url = urlsplit(request.url)
        host = url.hostname or ""
        if request.resource_type in {"image", "media", "font"}:
            await route.abort()
        elif (url.scheme == "https" and host.endswith((".xiaohongshu.com", ".xhscdn.com"))
                and request.method in {"GET", "HEAD", "OPTIONS"}):
            await route.fallback()
        else:
            await route.abort()

    @staticmethod
    def received_response(response, *, next_page=False):
        if not api_response(response, MENTIONS) or response.request.method != "GET":
            return False
        return not next_page or bool(parse_qs(urlsplit(response.url).query).get("cursor"))

    @staticmethod
    async def response_data(response, field, message):
        body = await response.json()
        data = body.get("data") if isinstance(body, dict) else None
        if not response.ok or not isinstance(data, dict) or body.get("code") != 0 or not isinstance(data.get(field), list):
            raise ValueError(message)
        return data

    async def open_received(self, page):
        async with page.expect_response(self.received_response, timeout=16000) as found:
            await page.goto(f"{ORIGIN}/notification", wait_until="domcontentloaded", timeout=18000)
        return await self.response_data(await found.value, "message_list", "小红书暂未返回收到的评论。")

    @staticmethod
    async def scroll_for_page(page, locator, matches):
        async with page.expect_response(matches, timeout=9000) as found:
            await locator.last.hover(timeout=6500)
            await page.mouse.wheel(0, 1600)
        return await found.value

    async def next_received(self, page):
        items = page.locator(".tabs-content-container .interaction-content")
        response = await self.scroll_for_page(page, items, lambda r: self.received_response(r, next_page=True))
        return await self.response_data(response, "message_list", "小红书暂未返回后续评论消息。")

    async def load_received(self, binding, known):
        entries = {}
        async with self.open(binding, self.read_route) as (page, owner):
            data = await self.open_received(page)
            for _ in range(5):
                page_rows = [row for item in data["message_list"] if (row := incoming_comment(item, owner))]
                keys = {(row["note_id"], row["comment"]["id"]) for row in page_rows}
                entries.update(((row["note_id"], row["comment"]["id"]), row) for row in page_rows)
                if not known or keys & known or not data.get("has_more"):
                    break
                try:
                    data = await self.next_received(page)
                except PlaywrightTimeout:
                    break
        return list(entries.values())

    async def received_row(self, page, owner, message):
        data = await self.open_received(page)
        for _ in range(8):
            for item in data["message_list"]:
                current = incoming_comment(item, owner)
                if (not current or current["note_id"] != message["note_id"]
                        or current["comment"]["id"] != message["comment"]["id"]):
                    continue
                comment = current["comment"]
                content = page.locator(".interaction-content").and_(page.get_by_text(comment["body"], exact=True))
                rows = page.locator(".tabs-content-container > .container").filter(has=content)
                if comment["author"]:
                    rows = rows.filter(has=page.get_by_text(comment["author"], exact=True))
                await rows.first.wait_for(state="visible", timeout=7500)
                if await rows.count() == 1:
                    return rows
                raise ValueError("无法唯一定位这条收到的评论，请打开原帖评论。")
            if not data.get("has_more"):
                break
            data = await self.next_received(page)
        raise ValueError("这条消息已不在当前的小红书通知列表，请打开原帖评论。")

    async def load_notes(self, page, owner):
        await page.goto(f"{ORIGIN}/user/profile/{owner}", wait_until="domcontentloaded", timeout=22000)
        cards = page.locator("section.note-item")
        await page.locator("section.note-item, .feeds-container, .no-notes, .empty-container").first.wait_for(timeout=10000)
        if not await cards.count():
            empty = page.locator(".no-notes").or_(page.get_by_text(re.compile(r"^(暂无|还没有)(发布的)?笔记$")))
            try:
                await cards.or_(empty).first.wait_for(timeout=4000)
            except PlaywrightTimeout:
                raise ValueError("小红书笔记列表还没加载完成，已保留上次同步结果。") from None
        notes = {}
        for card in await cards.evaluate_all(NOTE_CARDS):
            ident = card.get("id")
            if not isinstance(ident, str) or not IDENTIFIER.fullmatch(ident):
                continue
            href = next((href for href in card["hrefs"] if trusted_note(href, ident, owner)), None)
            if not href:
                continue
            cover = next((url for value in card["covers"]
                          if cover_address(url := ("https:" + value[5:] if value.startswith("http:") else value))), "")
            notes[ident] = {
                "id": ident, "title": text(card.get("title"), 180) or "未命名笔记", "href": href, "cover": cover,
            }
        if await cards.count() and not notes:
            raise ValueError("小红书笔记列表已打开，但没有读到有效的笔记链接。")
        return list(notes.values())

    async def verify_deleted_notes(self, page, owner, notes):
        deleted = set()
        slots = asyncio.Semaphore(4)
        user_agent = await page.evaluate("navigator.userAgent")
        headers = {"User-Agent": user_agent, "Referer": f"{ORIGIN}/user/profile/{owner}", "Cache-Control": "no-cache"}

        async def verify(note):
            ident, address = note["id"], note["href"]
            if not trusted_note(address, ident, owner):
                return
            async with slots:
                try:
                    for _ in range(2):
                        response = await page.request.get(address, max_redirects=0, timeout=3500, headers=headers)
                        try:
                            if not note_document_deleted(response, ident, owner):
                                return
                            if response.status == 410:
                                break
                        finally:
                            await response.dispose()
                    deleted.add(ident)
                except PlaywrightError:
                    return

        try:
            async with asyncio.timeout(8):
                await asyncio.gather(*(verify(note) for note in notes))
        except TimeoutError:
            pass
        return deleted

    async def open_note(self, page, owner, note, *, timeout=18000):
        if not trusted_note(note["href"], note["id"], owner):
            raise ValueError("笔记链接已失效，请重新同步笔记。")
        async with page.expect_response(lambda r: matching_comment_page(r, note["id"]), timeout=timeout) as found:
            document = await page.goto(note["href"], wait_until="domcontentloaded", timeout=timeout)
            if note_document_deleted(document, note["id"], owner):
                raise NoteDeleted()
        response = await found.value
        body = await response.json()
        message = text(body.get("msg") or body.get("message"), 100).strip()
        code = body.get("code")
        if (body.get("success") is False or isinstance(code, int) and code != 0) and DELETED_NOTE_MESSAGE.fullmatch(message):
            raise NoteDeleted()
        data = body.get("data")
        if not response.ok or body.get("code") != 0 or not isinstance(data, dict) or not isinstance(data.get("comments"), list):
            raise ValueError("小红书暂未返回这篇笔记的评论，请稍后重试。")
        return data

    @staticmethod
    def format_comments(data, owner):
        comments = comment_rows(data["comments"], owner)
        for item in data["comments"]:
            ident = item.get("id") if isinstance(item, dict) else None
            if isinstance(ident, str) and ident in comments:
                comments[ident].update(child_preview(item, owner), owner_replied=has_owner_reply(item, owner))
        return {"comments": list(comments.values()), "has_more": data.get("has_more") is True}

    async def load_comments(self, page, owner, note, *, timeout=18000):
        return self.format_comments(await self.open_note(page, owner, note, timeout=timeout), owner)

    async def next_top_page(self, page, note_id):
        comments = page.locator(".comments-container .parent-comment")
        response = await self.scroll_for_page(page, comments, lambda r: matching_comment_page(r, note_id)
                                              and bool(parse_qs(urlsplit(r.url).query).get("cursor")))
        return await self.response_data(response, "comments", "小红书暂未返回后续评论。")

    async def collect_top(self, page, owner, note_id, data, *, known):
        comments = {}
        cursors = set()
        async with asyncio.timeout(38):
            while True:
                batch = self.format_comments(data, owner)
                comments.update((row["id"], row) for row in batch["comments"])
                if not batch["has_more"] or comments.keys() - known:
                    break
                cursor = text(data.get("cursor"), 512)
                if cursor in cursors:
                    raise ValueError("小红书暂未提供后续评论，可稍后重试。")
                cursors.add(cursor)
                data = await self.next_top_page(page, note_id)
        return {**batch, "comments": list(comments.values())}

    async def load_more_comments(self, binding, note, known):
        try:
            async with self.open(binding, self.read_route) as (page, owner):
                data = await self.open_note(page, owner, note)
                return await self.collect_top(page, owner, note["id"], data, known=known)
        except (TimeoutError, PlaywrightTimeout) as exc:
            raise ValueError("加载更多评论超时，请稍后再试。") from exc

    async def locate_received(self, binding, note, message, on_open):
        target = message["comment"]["id"]
        previous = message["previous_id"]
        comments = {}
        result = {"comments": [], "has_more": False}
        tried = set()
        cursors = set()
        async with self.open(binding, self.read_route) as (page, owner):
            data = await self.open_note(page, owner, note)
            result = self.format_comments(data, owner)
            on_open(result)
            try:
                async with asyncio.timeout(12):
                    while True:
                        result = self.format_comments(data, owner)
                        comments.update((row["id"], row) for row in result["comments"])
                        if any(target == row["id"] or any(child["id"] == target for child in row["children"])
                               for row in result["comments"]):
                            break
                        if message["kind"] == "follow_up":
                            candidates = [row for row in data["comments"] if isinstance(row, dict)
                                          and row.get("id") in comments and row.get("sub_comment_has_more")]
                            candidates.sort(key=lambda row: (
                                row["id"] == previous,
                                any(child["id"] == previous for child in comments[row["id"]]["children"]),
                                has_owner_reply(row, owner),
                            ), reverse=True)
                            for parent in candidates:
                                ident = parent["id"]
                                if ident in tried or (ident != previous
                                    and not any(child["id"] == previous for child in comments[ident]["children"])
                                    and not has_owner_reply(parent, owner)):
                                    continue
                                tried.add(ident)
                                try:
                                    children = await self.collect_children(page, owner, note["id"], parent, target=target)
                                except ValueError:
                                    continue
                                if any(child["id"] == target for child in children["children"]):
                                    comments[ident].update(children)
                                    return {**result, "comments": list(comments.values())}
                        cursor = text(data.get("cursor"), 512)
                        if not result["has_more"] or cursor in cursors:
                            break
                        cursors.add(cursor)
                        data = await self.next_top_page(page, note["id"])
            except (TimeoutError, PlaywrightTimeout):
                pass
        return {**result, "comments": list(comments.values())}

    async def find_root(self, page, note_id, data, root_id):
        try:
            async with asyncio.timeout(32):
                while True:
                    item = next((row for row in data["comments"] if isinstance(row, dict) and row.get("id") == root_id), None)
                    if item is not None or not data.get("has_more"):
                        return self.original_comment(data, root_id)
                    data = await self.next_top_page(page, note_id)
        except (TimeoutError, PlaywrightTimeout) as exc:
            raise ValueError("暂时无法定位这条评论，请刷新评论后再试。") from exc

    @staticmethod
    def original_comment(data, ident):
        if not isinstance(ident, str) or not IDENTIFIER.fullmatch(ident):
            raise ValueError("评论标识无效。")
        item = next((item for item in data["comments"] if isinstance(item, dict) and item.get("id") == ident), None)
        if item is None:
            raise ValueError("原评论已不在当前可见列表，请重新加载评论。")
        return item

    async def next_child_page(self, page, note_id, root_id):
        thread = page.locator(f"#comment-{root_id}").locator("xpath=..")
        expand = thread.get_by_text(re.compile(r"^(?:展开|查看更多|查看)(?:\s*\d+\s*条|更多)?\s*(?:回复|评论)$"))
        async with page.expect_response(lambda r: matching_child_page(r, note_id, root_id), timeout=10000) as found:
            await expand.first.click(timeout=7500)
        response = await found.value
        body = await response.json()
        data = body.get("data")
        if not response.ok or body.get("code") != 0 or not isinstance(data, dict) or not isinstance(data.get("comments"), list):
            raise ValueError("小红书暂未返回子评论，请稍后重试。")
        return data

    async def collect_children(self, page, owner, note_id, root, *, known=(), target=None):
        result = child_preview(root, owner)
        children = {item["id"]: item for item in result["children"]}
        seen_cursors = set()
        try:
            async with asyncio.timeout(42):
                while result["children_more"] and (target is None or target not in children):
                    data = await self.next_child_page(page, note_id, root["id"])
                    page_rows = comment_rows(data["comments"], owner)
                    result["children_more"] = data.get("has_more") is True
                    cursor = text(data.get("cursor"), 512)
                    if result["children_more"] and (cursor in seen_cursors or not cursor and not (page_rows.keys() - children.keys())):
                        raise ValueError("小红书暂未提供后续子评论，可稍后重试。")
                    if cursor:
                        seen_cursors.add(cursor)
                    children.update(page_rows)
                    if target is None and page_rows.keys() - known:
                        break
        except (TimeoutError, PlaywrightTimeout) as exc:
            raise ValueError("子评论加载超时，请稍后重试。") from exc
        result["children"] = list(children.values())
        result["children_count"] = max(result["children_count"], len(children))
        return result

    async def load_children(self, binding, note, parent):
        previous = {item["id"]: item for item in parent.get("children", [])}
        async with self.open(binding, self.read_route) as (page, owner):
            data = await self.open_note(page, owner, note)
            root = await self.find_root(page, note["id"], data, parent["id"])
            result = await self.collect_children(page, owner, note["id"], root, known=previous.keys())
        if result["children_more"]:
            latest = {item["id"]: item for item in result["children"]}
            latest.update((ident, item) for ident, item in previous.items() if ident not in latest)
            result["children"] = list(latest.values())
            result["children_count"] = max(result["children_count"], len(latest))
        return result

    async def reply(self, binding, note, comment, body, *, root_id, received=None):
        submitted = False
        armed = False

        async def guard(route):
            nonlocal submitted
            request = route.request
            url = urlsplit(request.url)
            if url.scheme == "https" and url.netloc == API and url.path == REPLY and request.method == "POST":
                try:
                    data = request.post_data_json
                except (ValueError, TypeError):
                    data = None
                if (armed and not submitted and isinstance(data, dict) and data.get("note_id") == note["id"]
                        and data.get("target_comment_id") == comment["id"] and data.get("content") == body):
                    submitted = True
                    await route.fallback()
                else:
                    await route.abort()
                return
            await self.read_route(route)

        try:
            async with self.open(binding, guard) as (page, owner):
                if received:
                    async with asyncio.timeout(46):
                        row = await self.received_row(page, owner, received)
                    await row.get_by_text("回复", exact=True).click(timeout=9000)
                    send = row.locator("button.submit:visible").and_(page.get_by_role("button", name="发送", exact=True))
                else:
                    data = await self.open_note(page, owner, note)
                    root = await self.find_root(page, note["id"], data, root_id)
                    target = page.locator(f"#comment-{root_id}")
                    ident = comment["id"]
                    if ident != root_id:
                        if not isinstance(ident, str) or not IDENTIFIER.fullmatch(ident):
                            raise ValueError("评论标识无效。")
                        children = await self.collect_children(page, owner, note["id"], root, target=ident)
                        if not any(child["id"] == ident for child in children["children"]):
                            raise ValueError("这条子评论已不在原评论下，请刷新后再试。")
                        target = target.locator("xpath=..").locator(f"#comment-{ident}")
                    await target.locator(".reply").first.click(timeout=9000)
                    send = page.locator("div.bottom button.submit:visible")
                editor = page.locator("[contenteditable=true]:focus, textarea:focus")
                await editor.fill(body, timeout=5000)
                async with page.expect_response(lambda r: submitted and api_response(r, REPLY)
                                                and r.request.method == "POST", timeout=14000) as found:
                    armed = True
                    await send.click(timeout=5000)
                response = await found.value
                result = await response.json()
                if response.ok and result.get("code") == 0 and result.get("success") is not False:
                    return "sent", "小红书已确认收到回复。"
                if response.ok and isinstance(result.get("code"), int) and result["code"] != 0:
                    return "failed", "小红书明确拒绝了这次回复。"
        except ValueError as exc:
            if not submitted:
                return "failed", str(exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logging.warning("Xiaohongshu reply could not be confirmed (%s)", type(exc).__name__)
        if submitted:
            return "needs_review", "已发出请求，平台结果待核对。请先在原笔记查看。"
        return "failed", "未能向所选评论发送回复。请重新加载评论后再试。"

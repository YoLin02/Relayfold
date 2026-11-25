import asyncio
import logging
import re
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import TimeoutError as PlaywrightTimeout

from browser import xhs_user_proof


HOST = "www.xiaohongshu.com"
ORIGIN = f"https://{HOST}"
API = "edith.xiaohongshu.com"
COMMENTS = "/api/sns/web/v2/comment/page"
REPLY = "/api/sns/web/v1/comment/post"
IDENTIFIER = re.compile(r"[a-fA-F0-9]{24}")

NOTE_CARDS = """cards => cards.map(card => {
    const hiddenLink = card.querySelector('a[href^="/explore/"], a[href^="/discovery/item/"]');
    const title = card.querySelector('a.title');
    const cover = card.querySelector('a.cover');
    const image = cover?.querySelector('img');
    return { id: hiddenLink?.pathname.split('/').at(-1), href: title?.href || cover?.href,
      title: title?.textContent.trim(), cover: image?.currentSrc || image?.src };
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


def text(value, limit):
    return value[:limit] if isinstance(value, str) else ""


class XiaohongshuComments:
    def __init__(self, browser):
        self.browser = browser

    @asynccontextmanager
    async def open(self, binding, guard):
        if binding["id"] in self.browser.contexts:
            raise ValueError("这个账号还有一个平台窗口打开。关闭后再加载评论。")
        try:
            context, page = await self.browser.launch(binding, headless=True, service_workers="block")
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
        if (url.scheme == "https" and host.endswith((".xiaohongshu.com", ".xhscdn.com"))
                and request.method in {"GET", "HEAD", "OPTIONS"}):
            await route.fallback()
        else:
            await route.abort()

    async def notes(self, binding):
        async with self.open(binding, self.read_route) as (page, owner):
            await page.goto(f"{ORIGIN}/user/profile/{owner}", wait_until="domcontentloaded", timeout=22000)
            cards = page.locator("section.note-item")
            await page.locator("section.note-item, .feeds-container, .no-notes, .empty-container").first.wait_for(timeout=10000)
            if not await cards.count():
                try:
                    await cards.first.wait_for(timeout=4000)
                except PlaywrightTimeout:
                    pass
            notes = {}
            for card in await cards.evaluate_all(NOTE_CARDS):
                ident = card.get("id")
                if not isinstance(ident, str) or not IDENTIFIER.fullmatch(ident) or not trusted_note(card.get("href"), ident, owner):
                    continue
                cover = urlsplit(card.get("cover") or "")
                notes[ident] = {
                    "id": ident, "title": text(card.get("title"), 180) or "未命名笔记", "href": card["href"],
                    "cover": card["cover"] if cover.scheme == "https" and (cover.hostname or "").endswith(".xhscdn.com") else "",
                }
            if await cards.count() and not notes:
                raise ValueError("小红书笔记列表已打开，但没有读到有效的笔记链接。")
            return list(notes.values())

    async def open_note(self, page, owner, note):
        if not trusted_note(note["href"], note["id"], owner):
            raise ValueError("笔记链接已失效，请重新同步笔记。")
        async with page.expect_response(lambda r: matching_comment_page(r, note["id"]), timeout=18000) as found:
            await page.goto(note["href"], wait_until="domcontentloaded", timeout=20000)
        response = await found.value
        body = await response.json()
        data = body.get("data")
        if not response.ok or body.get("code") != 0 or not isinstance(data, dict) or not isinstance(data.get("comments"), list):
            raise ValueError("小红书暂未返回这篇笔记的评论，请稍后重试。")
        return data

    async def comments(self, binding, note):
        async with self.open(binding, self.read_route) as (page, owner):
            data = await self.open_note(page, owner, note)
            comments = []
            for item in data["comments"]:
                if not isinstance(item, dict) or not IDENTIFIER.fullmatch(text(item.get("id"), 80)):
                    continue
                author = item.get("user_info")
                comments.append({
                    "id": item["id"], "author": text(author.get("nickname"), 80) if isinstance(author, dict) else "",
                    "body": text(item.get("content"), 2000),
                    "created_at": item.get("create_time") if isinstance(item.get("create_time"), int) else None,
                })
            return {"comments": comments, "has_more": data.get("has_more") is True}

    async def reply(self, binding, note, comment, body):
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
                data = await self.open_note(page, owner, note)
                if not any(item.get("id") == comment["id"] for item in data["comments"] if isinstance(item, dict)):
                    raise ValueError("原评论已不在当前可见列表，请重新加载评论。")
                target = page.locator(f'#comment-{comment["id"]}')
                await target.locator(".reply").first.click(timeout=9000)
                editor = page.locator("[contenteditable=true]:focus, textarea:focus")
                await editor.fill(body, timeout=5000)
                send = page.locator("div.bottom button.submit:visible")
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

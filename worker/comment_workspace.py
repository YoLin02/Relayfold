import asyncio
import json
import logging
import sqlite3
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import Error as PlaywrightError

from comment_cache import CACHE_NAME, CommentCache, fetch_cover
from store import new_id
from xhs_comments import NoteDeleted, XiaohongshuComments, notification_note_link


POLL_INTERVAL = 600


class CommentWorkspace:
    def __init__(self, store, browser, lock, root, emit, *, download_cover=None):
        self.store = store
        self.browser = browser
        self.platform = XiaohongshuComments(browser)
        self.lock = lock
        self.emit = emit
        self.default_directory = (root / "comments").resolve()
        self.cache_error = ""
        configured = self.setting("comment_cache_directory")
        owner = self.setting("comment_cache_owner")
        if not owner:
            owner = new_id()
            self.save_setting("comment_cache_owner", owner)
        try:
            self.cache = CommentCache(Path(configured) if configured else self.default_directory, owner)
        except (OSError, sqlite3.Error, ValueError):
            if not configured:
                raise
            self.cache = CommentCache(self.default_directory, owner)
            self.cache_error = "原评论缓存目录不可用，当前使用默认目录。"
        self.jobs = {}
        self.background_jobs = {}
        self.preempted = set()
        self.inbox_jobs = {}
        self.inbox_slots = asyncio.Semaphore(2)
        self.progress = {}
        self.cover_jobs = {}
        self.cover_slots = asyncio.Semaphore(3)
        self.download_cover = download_cover or fetch_cover
        self.poll_wakeup = asyncio.Event()
        self.prepared = {}
        with self.store.db:
            self.store.db.execute("""
                CREATE TABLE IF NOT EXISTS comment_replies (
                    binding_id TEXT NOT NULL REFERENCES bindings(id) ON DELETE CASCADE,
                    note_id TEXT NOT NULL, comment_id TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL,
                    PRIMARY KEY (binding_id, note_id, comment_id)
                )
            """)
            self.store.db.execute("""
                UPDATE comment_replies SET status='needs_review', detail='应用在处理回复时退出，请到原笔记核对。'
                WHERE status='sending'
            """)
            self.store.db.execute("""
                CREATE TABLE IF NOT EXISTS comment_replied_targets (
                    binding_id TEXT NOT NULL REFERENCES bindings(id) ON DELETE CASCADE,
                    note_id TEXT NOT NULL, comment_id TEXT NOT NULL,
                    PRIMARY KEY (binding_id, note_id, comment_id)
                )
            """)
            self.store.db.execute("""
                INSERT OR IGNORE INTO comment_replied_targets
                SELECT binding_id, note_id, comment_id FROM comment_replies WHERE status='sent'
            """)

    def setting(self, key):
        row = self.store.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def save_setting(self, key, value):
        with self.store.db:
            self.store.db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, value))

    def configure(self, args):
        notifications = args.get("notifications")
        if "notifications" in args and not isinstance(notifications, bool):
            raise ValueError("评论提醒设置无效。")
        if "directory" in args:
            directory = args["directory"]
            if directory is not None and (not isinstance(directory, str) or not Path(directory).is_absolute()):
                raise ValueError("请选择一个可写的缓存目录。")
            try:
                path = Path(directory).resolve() if directory else self.default_directory
                configured = self.setting("comment_cache_directory")
                recover_existing = bool(self.cache_error and configured and path == Path(configured)
                                        and (path / CACHE_NAME).is_file())
                previous, previous_directory = self.cache.change_directory(path, recover_existing=recover_existing)
                try:
                    self.save_setting("comment_cache_directory", str(path) if directory else "")
                except sqlite3.Error:
                    if previous is not self.cache.db:
                        self.cache.db.close()
                        self.cache.db, self.cache.directory = previous, previous_directory
                    raise
                if previous is not self.cache.db:
                    previous.close()
                    if not recover_existing:
                        try:
                            (previous_directory / CACHE_NAME).unlink(missing_ok=True)
                        except OSError:
                            logging.warning("Old comment cache could not be removed after migration")
                self.cache_error = ""
            except (OSError, sqlite3.Error) as exc:
                raise ValueError("无法写入或迁移评论缓存，请检查目录权限和磁盘空间。") from exc
        if "notifications" in args:
            self.save_setting("comment_notifications", "1" if notifications else "0")
            self.poll_wakeup.set()

    @staticmethod
    def scope(binding):
        return f"{binding['group_id']}:{binding['id']}:{binding['account_proof']}"

    def bindings(self, group=None):
        return [dict(row) for row in self.store.db.execute("""
            SELECT * FROM bindings WHERE active=1 AND platform='xiaohongshu' AND account_proof IS NOT NULL
            AND login_status IN ('ready', 'saved') AND (? IS NULL OR group_id=?)
            ORDER BY group_id, slot
        """, (group, group))]

    def summary(self):
        return {"directory": str(self.cache.directory), "default_directory": str(self.default_directory),
                "notifications": self.setting("comment_notifications") == "1", "error": self.cache_error,
                "unread": sum(len(self.cache.received_unread(self.scope(binding))) for binding in self.bindings())}

    def changed(self, binding):
        self.emit({"event": "comments", "group_id": binding["group_id"]})

    def forget_bindings(self, ids):
        prefixes = {f":{binding_id}:" for binding_id in ids}
        self.cache.forget([row[0] for row in self.cache.db.execute("SELECT scope FROM accounts")
                           if any(prefix in row[0] for prefix in prefixes)])

    def account(self, group, binding_id):
        binding = self.store.binding(binding_id)
        if binding["group_id"] != group or binding["platform"] != "xiaohongshu":
            raise ValueError("请在原发布组选择这条笔记所属的小红书账号。")
        if binding["login_status"] not in {"ready", "saved"} or not binding["account_proof"]:
            raise ValueError("请先在平台账号页验证这个小红书账号的登录。")
        return binding

    def status(self, key):
        row = self.store.db.execute("""
            SELECT status, detail FROM comment_replies WHERE binding_id=? AND note_id=? AND comment_id=?
        """, key).fetchone()
        return dict(row) if row else None

    def save_status(self, key, status, detail):
        with self.store.db:
            self.store.db.execute("""
                INSERT INTO comment_replies VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(binding_id, note_id, comment_id) DO UPDATE SET status=excluded.status, detail=excluded.detail
            """, (*key, status, detail))
            if status == "sent":
                self.store.db.execute("INSERT OR IGNORE INTO comment_replied_targets VALUES (?, ?, ?)", key)
        return {"status": status, "detail": detail}

    def require_replyable(self, key):
        status = self.status(key)
        if status and status["status"] == "sending":
            raise ValueError("这条评论有一条回复正在发送，请等发送结束。")
        return status

    def public_comment(self, binding, note_id, comment, unread):
        key = (binding["id"], note_id, comment["id"])
        reply = self.status(key)
        sent = self.store.db.execute("""
            SELECT 1 FROM comment_replied_targets WHERE binding_id=? AND note_id=? AND comment_id=?
        """, key).fetchone()
        children = [self.public_comment(binding, note_id, child, unread) for child in comment.get("children", [])]
        replied = bool(sent or comment.get("owner_replied") or any(child["replied"] or child["by_owner"] for child in children))
        if replied and not reply:
            reply = {"status": "sent", "detail": "已在这条评论下回复。"}
        return {**comment, "children": children, "reply": reply, "replied": replied, "unread": comment["id"] in unread}

    def public_comments(self, binding, note):
        result = json.loads(note["comments"])
        unread = self.cache.received_unread(self.scope(binding), note["id"])
        comments = [self.public_comment(binding, note["id"], comment, unread) for comment in result["comments"]]
        return {**result, "comments": comments, "updated_at": note["comments_at"]}

    def public_note(self, scope, note):
        return {"id": note["id"], "title": note["title"], "has_cover": bool(note["has_cover"] or note["cover_url"]),
                "unread": len(self.cache.received_unread(scope, note["id"]))}

    def snapshot(self, binding, note_id=None):
        scope = self.scope(binding)
        cached = self.cache.account(scope)
        note = self.cache.note(scope, note_id) if note_id else None
        return {
            "notes": [self.public_note(scope, row) for row in self.cache.notes(scope)] if cached and cached["notes_at"] else None,
            "notes_at": cached["notes_at"] if cached else None,
            "note": self.public_note(scope, note) if note else None,
            "deleted": bool(note_id and self.cache.is_deleted(scope, note_id)),
            "thread": self.public_comments(binding, note) if note and note["comments"] else None,
            "notes_sync": self.progress.get((scope, "notes", None)),
            "thread_sync": self.progress.get((scope, "list", note_id)),
        }

    def inbox_snapshot(self, group):
        snapshots = {}
        for binding in self.bindings(group):
            scope = self.scope(binding)
            entries = []
            for message in self.cache.received(scope):
                note_id = message["note_id"]
                note = self.cache.note(scope, note_id)
                original = (message["comment"]["id"],) if message["unread"] else ()
                entries.append({"note_id": note_id, "note_title": note["title"] if note else message["note_title"],
                                "kind": message["kind"],
                                "open_target": self.inbox_note_destination(message, note),
                                "comment": self.public_comment(binding, note_id, message["comment"], original)})
            snapshots[binding["id"]] = {"entries": entries, "updated_at": self.cache.received_at(scope),
                                        "sync": self.progress.get((scope, "inbox", None))}
        return snapshots

    @staticmethod
    def inbox_note_destination(message, note):
        mine = message.get("note_is_mine")
        if mine is None:
            mine = message["kind"] == "comment" or bool(note and note["position"] is not None)
        return "full" if mine and note and note["href"] else "web"

    def inbox_source_link(self, scope, note_id, comment_id):
        message = self.cache.received_message(scope, note_id, comment_id)
        if not message:
            raise ValueError("找不到这条收到的评论，请重新同步收件箱。")
        try:
            token = parse_qs(urlsplit(message.get("href") or "").query).get("xsec_token", [""])[0]
        except ValueError:
            token = ""
        return notification_note_link(note_id, token)

    def publishing(self, binding_id):
        return self.store.db.execute("""
            SELECT 1 FROM tasks t JOIN batches b ON b.id=t.batch_id WHERE t.binding_id=? AND
            (t.status IN ('queued','running','submitting','verifying') OR (t.status='scheduled' AND b.scheduled_at<=?))
            LIMIT 1
        """, (binding_id, int(time.time()) + 120)).fetchone() is not None

    def save_comments(self, binding, note_id, result):
        self.cache.save_comments(self.scope(binding), note_id, result)
        self.changed(binding)

    def remove_deleted_notes(self, binding, note_ids):
        self.cache.mark_deleted(self.scope(binding), note_ids)
        self.changed(binding)

    async def sync(self, group, binding_id, kind, note_id=None, *, background=False):
        binding = self.account(group, binding_id)
        scope = self.scope(binding)
        key = (scope, kind, note_id)
        if key in self.jobs:
            if not background:
                await asyncio.gather(asyncio.shield(self.jobs[key]), return_exceptions=True)
            return
        lock = self.lock(binding_id)
        if background and (lock.locked() or binding_id in self.browser.contexts or self.publishing(binding_id)):
            return
        start = time.time()
        task = asyncio.create_task(self.run_sync(binding, key, start, background))
        self.jobs[key] = task
        if background:
            self.background_jobs[binding_id] = task
        try:
            await task
        except asyncio.CancelledError:
            if task not in self.preempted or asyncio.current_task().cancelling():
                raise
        finally:
            self.preempted.discard(task)
            self.jobs.pop(key, None)
            if background:
                self.background_jobs.pop(binding_id, None)

    async def yield_to_foreground(self, binding_id):
        task = self.background_jobs.get(binding_id)
        if task and not task.done():
            self.preempted.add(task)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def sync_inbox_account(self, binding):
        async with self.inbox_slots:
            try:
                await self.sync(binding["group_id"], binding["id"], "inbox")
            except ValueError:
                return

    async def sync_inbox_group(self, group, bindings):
        try:
            await asyncio.gather(*(self.sync_inbox_account(binding) for binding in bindings))
        finally:
            self.inbox_jobs.pop(group, None)
            self.emit({"event": "comments", "group_id": group})

    async def shutdown(self):
        pending = set(self.jobs.values()) | set(self.inbox_jobs.values()) | set(self.cover_jobs.values())
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        self.cache.db.close()

    async def run_sync(self, binding, key, start, background):
        scope, kind, note_id = key
        binding_id, group = binding["id"], binding["group_id"]
        arrivals = []
        progress = {"running": True, "done": 0, "total": 0, "error": ""}
        self.progress[key] = progress
        self.changed(binding)
        stage = "等待账号会话"
        phase_start = time.monotonic()

        def next_stage(label):
            nonlocal stage, phase_start
            logging.getLogger(__name__).info("Comment sync %s: %s %.2fs", kind, stage, time.monotonic() - phase_start)
            stage, phase_start = label, time.monotonic()

        try:
            async with self.lock(binding_id):
                self.account(group, binding_id)
                if self.publishing(binding_id):
                    if not background:
                        progress["error"] = "这个账号有发布任务在处理，已保留上次同步结果。"
                    return
                if kind == "inbox":
                    next_stage("读取收到的评论消息")
                    messages = await self.platform.load_received(binding, self.cache.received_keys(scope))
                    arrivals = [{"group_id": group, "binding_id": binding_id, **entry}
                                for entry in self.cache.save_received(scope, messages)]
                    return
                cached = self.cache.account(scope)
                if kind == "notes" and cached and (cached["notes_at"] or 0) >= start:
                    return
                if kind == "list" and self.cache.is_deleted(scope, note_id):
                    raise NoteDeleted()
                note = self.cache.note(scope, note_id) if kind == "list" else None
                if note and (note["comments_at"] or 0) >= start:
                    return
                next_stage("启动浏览器和核验身份")
                async with self.platform.open(binding, self.platform.read_route) as (page, owner):
                    if kind != "list" or note is None:
                        next_stage("加载笔记列表")
                        notes = self.cache.save_notes(scope, await self.platform.load_notes(page, owner))
                        self.changed(binding)
                    if kind == "notes":
                        if notes and not self.publishing(binding_id):
                            next_stage("核对笔记是否仍存在")
                            deleted = await self.platform.verify_deleted_notes(page, owner, notes)
                            if deleted:
                                self.remove_deleted_notes(binding, deleted)
                                notes = [item for item in notes if item["id"] not in deleted]
                        if notes and not self.publishing(binding_id):
                            first = notes[0]
                            cached_first = self.cache.note(scope, first["id"])
                            if not cached_first["comments_at"]:
                                next_stage("预读首篇笔记评论")
                                try:
                                    result = await self.platform.load_comments(page, owner, first, timeout=6000)
                                except NoteDeleted:
                                    self.remove_deleted_notes(binding, [first["id"]])
                                except (PlaywrightError, ValueError):
                                    pass
                                else:
                                    self.save_comments(binding, first["id"], result)
                        return
                    if kind == "list":
                        next_stage("读取所选笔记评论")
                        note = note or self.cache.note(scope, note_id)
                        if not note:
                            raise ValueError("没有找到这篇笔记，请重新选择。")
                        try:
                            result = await self.platform.load_comments(page, owner, note)
                        except (PlaywrightError, ValueError) as exc:
                            if self.publishing(binding_id):
                                if isinstance(exc, NoteDeleted):
                                    raise ValueError("笔记暂时无法打开，发布任务结束后可重新同步。") from exc
                                raise
                            notes = self.cache.save_notes(scope, await self.platform.load_notes(page, owner))
                            updated = next((item for item in notes if item["id"] == note_id), None)
                            if not updated or updated["href"] == note["href"]:
                                raise
                            result = await self.platform.load_comments(page, owner, updated)
                        self.save_comments(binding, note_id, result)
                        return
        except NoteDeleted as exc:
            self.remove_deleted_notes(binding, [note_id])
            progress["error"] = str(exc)
        except (PlaywrightError, ValueError) as exc:
            progress["error"] = str(exc) if isinstance(exc, ValueError) else f"{stage}超时或页面不可用，已保留上次同步结果。"
        except (OSError, sqlite3.Error):
            progress["error"] = "无法写入评论缓存，请检查设置中的缓存目录。"
        finally:
            next_stage("完成")
            if progress["error"]:
                self.progress[key] = {**progress, "running": False}
            else:
                self.progress.pop(key, None)
            self.changed(binding)
            if arrivals and kind == "inbox" and self.setting("comment_notifications") == "1":
                group_info = self.store.require_group(group)
                label = binding["label"]
                if group_info["mode"] == "custom":
                    label = f"{label} · 小红书 {binding['slot']}"
                self.emit({"event": "comment-alert", "destination": arrivals[0], "count": len(arrivals),
                           "account": f"{group_info['name']} · {label}"})

    async def poll(self):
        while True:
            try:
                await asyncio.wait_for(self.poll_wakeup.wait(), POLL_INTERVAL)
            except asyncio.TimeoutError:
                pass
            self.poll_wakeup.clear()
            if not self.cache_error and self.setting("comment_notifications") == "1":
                for binding in self.bindings():
                    if self.setting("comment_notifications") != "1":
                        break
                    try:
                        async with self.inbox_slots:
                            if self.setting("comment_notifications") == "1":
                                await self.sync(binding["group_id"], binding["id"], "inbox", background=True)
                    except ValueError:
                        continue

    async def cover(self, binding, note_id):
        scope = self.scope(binding)
        row = self.cache.cover(scope, note_id)
        if not row or not row["cover_url"] or row["cover_source"] == row["cover_url"]:
            return self.cache.cover_data(row)
        if row["cover"] and urlsplit(row["cover_source"]).path == urlsplit(row["cover_url"]).path:
            return self.cache.cover_data(row)
        key = (scope, note_id, row["cover_url"])
        if key not in self.cover_jobs:
            self.cover_jobs[key] = asyncio.create_task(self.load_cover(*key))
        task = self.cover_jobs[key]
        try:
            await asyncio.shield(task)
        finally:
            if task.done() and self.cover_jobs.get(key) is task:
                self.cover_jobs.pop(key, None)
        return self.cache.cover_data(self.cache.cover(scope, note_id))

    async def load_cover(self, scope, note_id, url):
        async with self.cover_slots:
            try:
                image = await asyncio.to_thread(self.download_cover, url)
                if image:
                    self.cache.save_cover(scope, note_id, url, image)
            except (OSError, ValueError, sqlite3.Error):
                return

    async def command(self, method, args):
        if method == "comments.send":
            return await self.send(args.get("confirmation"))
        group, binding_id = args.get("group_id"), args.get("binding_id")
        note_id = args.get("note_id")
        if method == "comments.inboxSnapshot":
            self.store.require_group(group)
            return self.inbox_snapshot(group)
        if method == "comments.summary":
            return self.summary()
        if method == "comments.inbox" and binding_id is None:
            self.store.require_group(group)
            if group not in self.inbox_jobs:
                self.inbox_jobs[group] = asyncio.create_task(self.sync_inbox_group(group, self.bindings(group)))
            return
        binding = self.account(group, binding_id)
        scope = self.scope(binding)
        if method == "comments.snapshot":
            return self.snapshot(binding, note_id)
        if method == "comments.cover":
            return await self.cover(binding, note_id)
        if method in {"comments.notes", "comments.list", "comments.inbox"}:
            return await self.sync(group, binding_id, method.partition(".")[2], note_id)
        comment_id = args.get("comment_id")
        if method == "comments.sourceLink":
            return self.inbox_source_link(scope, note_id, comment_id)
        if method == "comments.read":
            received_read = self.cache.mark_received_read(scope, note_id, comment_id)
            if self.cache.mark_read(scope, note_id, comment_id) or received_read:
                self.changed(binding)
            return
        note = self.cache.note(scope, note_id)
        received = self.cache.received_message(scope, note_id, comment_id) if args.get("received") is True else None
        if args.get("received") is True and not received:
            raise ValueError("这条收到的评论已不可用，请重新同步收件箱。")
        if not note and not received:
            raise ValueError("请先同步这个账号的笔记。")
        if method in {"comments.more", "comments.locate"}:
            return await self.extend_thread(binding, note_id, comment_id if method == "comments.locate" else None)
        comments = json.loads(note["comments"])["comments"] if note and note["comments"] else []
        if method == "comments.children":
            return await self.expand_comments(binding, note_id, comment_id)
        root_id = args.get("root_comment_id") or comment_id
        parent = next((item for item in comments if item["id"] == root_id), None)
        comment = parent if root_id == comment_id else next(
            (item for item in (parent or {}).get("children", []) if item["id"] == comment_id), None)
        if received:
            comment = received["comment"]
        body = args.get("body")
        if not comment or not isinstance(body, str) or not 1 <= len(body.strip()) <= 500:
            raise ValueError("请选择已加载的评论，填写 1–500 字的回复。")
        key = (binding_id, note_id, comment_id)
        previous = self.require_replyable(key)
        now = time.monotonic()
        self.prepared = {token: draft for token, draft in self.prepared.items() if draft["expires"] > now}
        token = new_id()
        note = dict(note) if note else {"id": note_id, "title": received["note_title"], "href": received["href"]}
        self.prepared[token] = {
            "group": group, "key": key, "account_proof": binding["account_proof"], "note": note,
            "comment": comment, "root_id": root_id, "received": received, "body": body.strip(), "expires": now + 300,
        }
        group_info = self.store.require_group(group)
        label = binding["label"]
        if group_info["mode"] == "custom":
            label = f"{label} · 小红书 {binding['slot']}"
        return {"confirmation": token, "account": label, "group": group_info["name"], "note": note["title"],
                "author": comment["author"], "comment": comment["body"], "body": body.strip(),
                "previous_attempt_unknown": bool(previous and previous["status"] == "needs_review")}

    async def expand_comments(self, binding, note_id, root_id):
        binding_id = binding["id"]
        scope = self.scope(binding)
        await self.yield_to_foreground(binding_id)
        async with self.lock(binding_id):
            self.account(binding["group_id"], binding_id)
            note = self.cache.note(scope, note_id)
            comments = json.loads(note["comments"])["comments"] if note and note["comments"] else []
            parent = next((item for item in comments if item["id"] == root_id), None)
            if not parent:
                raise ValueError("找不到所选评论，请先刷新笔记评论。")
            try:
                children = await self.platform.load_children(binding, note, parent)
            except NoteDeleted:
                self.remove_deleted_notes(binding, [note_id])
                raise
            self.cache.save_children(scope, note_id, root_id, children)
        self.changed(binding)

    async def extend_thread(self, binding, note_id, target):
        binding_id = binding["id"]
        scope = self.scope(binding)
        await self.yield_to_foreground(binding_id)
        async with self.lock(binding_id):
            self.account(binding["group_id"], binding_id)
            note = self.cache.note(scope, note_id)
            if not note:
                raise ValueError("这篇笔记的原帖链接已不可用。")
            stored = json.loads(note["comments"]) if note["comments"] else {}
            try:
                if target:
                    message = self.cache.received_message(scope, note_id, target)
                    if not message:
                        raise ValueError("找不到这条收到的评论，请重新同步收件箱。")
                    if self.inbox_note_destination(message, note) != "full":
                        raise ValueError("请从「收到评论」在小红书网页打开这篇原帖。")
                    result = await self.platform.locate_received(
                        binding, note, message,
                        lambda first_page: self.publish_original_page(binding, note_id, first_page))
                    result["has_more"] = result["has_more"] or bool(stored.get("has_more"))
                else:
                    known = {row["id"] for row in stored.get("comments", [])}
                    result = await self.platform.load_more_comments(binding, note, known)
            except NoteDeleted:
                self.remove_deleted_notes(binding, [note_id])
                raise
            except PlaywrightError as exc:
                raise ValueError("小红书暂未加载这篇原帖的评论，可刷新重试。") from exc
            self.cache.save_comments(scope, note_id, result, merge=bool(target))
            self.changed(binding)
            if target and not any(target == row["id"] or any(child["id"] == target for child in row.get("children", []))
                                  for row in result["comments"]):
                raise ValueError("已打开选中的原帖。可加载更多评论，继续查找这条回复。")

    def publish_original_page(self, binding, note_id, first_page):
        result = {**first_page, "comments": [dict(comment) for comment in first_page["comments"]]}
        self.cache.save_comments(self.scope(binding), note_id, result, merge=True)
        self.changed(binding)

    async def send(self, token):
        draft = self.prepared.pop(token, None) if isinstance(token, str) else None
        if not draft or draft["expires"] <= time.monotonic():
            raise ValueError("回复确认已失效，请重新核对。")
        key = draft["key"]
        binding_id = key[0]
        await self.yield_to_foreground(binding_id)
        async with self.lock(binding_id):
            binding = self.account(draft["group"], binding_id)
            if binding["account_proof"] != draft["account_proof"]:
                raise ValueError("原回复账号已变更，请重新核对。")
            self.require_replyable(key)
            self.save_status(key, "sending", "正在向原评论提交。")
            status, detail = await self.platform.reply(binding, draft["note"], draft["comment"], draft["body"],
                                                       root_id=draft["root_id"], received=draft["received"])
            result = self.save_status(key, status, detail)
            self.changed(binding)
            return result

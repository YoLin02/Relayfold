import time

from store import new_id
from xhs_comments import XiaohongshuComments


class CommentWorkspace:
    def __init__(self, store, browser, lock):
        self.store = store
        self.platform = XiaohongshuComments(browser)
        self.lock = lock
        self.notes = {}
        self.comments = {}
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
        return {"status": status, "detail": detail}

    def require_replyable(self, key):
        status = self.status(key)
        if status and status["status"] in {"sent", "sending", "needs_review"}:
            raise ValueError("这条评论已有回复记录，请先在原笔记核对。")

    async def command(self, method, args):
        if method == "comments.send":
            return await self.send(args.get("confirmation"))
        group, binding_id = args.get("group_id"), args.get("binding_id")
        note_id = args.get("note_id")
        async with self.lock(binding_id):
            binding = self.account(group, binding_id)
            if method == "comments.notes":
                notes = await self.platform.notes(binding)
                self.notes[binding_id] = {note["id"]: note for note in notes}
                for key in list(self.comments):
                    if key[0] == binding_id and key[1] not in self.notes[binding_id]:
                        del self.comments[key]
                return [{k: v for k, v in note.items() if k != "href"} for note in notes]

            note = self.notes.get(binding_id, {}).get(note_id)
            if not note:
                raise ValueError("请先同步这个账号的笔记。")
            if method == "comments.list":
                result = await self.platform.comments(binding, note)
                self.comments[(binding_id, note_id)] = {row["id"]: row for row in result["comments"]}
                return {**result, "comments": [
                    {**comment, "reply": self.status((binding_id, note_id, comment["id"]))}
                    for comment in result["comments"]
                ]}

            comment_id = args.get("comment_id")
            comment = self.comments.get((binding_id, note_id), {}).get(comment_id)
            body = args.get("body")
            if not comment or not isinstance(body, str) or not 1 <= len(body.strip()) <= 500:
                raise ValueError("请选择已加载的评论，填写 1–500 字的回复。")
            key = (binding_id, note_id, comment_id)
            self.require_replyable(key)
            now = time.monotonic()
            self.prepared = {token: draft for token, draft in self.prepared.items() if draft["expires"] > now}
            token = new_id()
            self.prepared[token] = {
                "group": group, "key": key, "account_proof": binding["account_proof"], "note": note,
                "comment": comment, "body": body.strip(), "expires": now + 300,
            }
            return {"confirmation": token, "account": binding["label"], "note": note["title"],
                    "author": comment["author"], "comment": comment["body"], "body": body.strip()}

    async def send(self, token):
        draft = self.prepared.pop(token, None) if isinstance(token, str) else None
        if not draft or draft["expires"] <= time.monotonic():
            raise ValueError("回复确认已失效，请重新核对。")
        key = draft["key"]
        binding_id = key[0]
        async with self.lock(binding_id):
            binding = self.account(draft["group"], binding_id)
            if binding["account_proof"] != draft["account_proof"]:
                raise ValueError("原回复账号已变更，请重新核对。")
            self.require_replyable(key)
            self.save_status(key, "sending", "正在向原评论提交。")
            status, detail = await self.platform.reply(binding, draft["note"], draft["comment"], draft["body"])
            return self.save_status(key, status, detail)

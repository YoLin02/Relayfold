import base64
import json
import sqlite3
from time import monotonic, time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


CACHE_NAME = "relayfold-comment-cache.sqlite3"
CACHE_ID = 0x52464343
COVER_LIMIT = 2 * 1024 * 1024


def cover_address(value):
    if not isinstance(value, str):
        return False
    try:
        url = urlsplit(value)
        return (url.scheme == "https" and (url.hostname or "").endswith(".xhscdn.com")
                and not url.username and not url.password and url.port in {None, 443})
    except ValueError:
        return False


class CoverRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if cover_address(newurl):
            return super().redirect_request(req, fp, code, msg, headers, newurl)
        return None


def fetch_cover(url):
    if not cover_address(url):
        return None
    request = Request(url, headers={"Referer": "https://www.xiaohongshu.com/",
                                   "User-Agent": "Mozilla/5.0", "Accept": "image/webp,image/png,image/jpeg,image/*"})
    with build_opener(CoverRedirect()).open(request, timeout=5) as response:
        body = response.read(COVER_LIMIT + 1)
    if len(body) > COVER_LIMIT:
        return None
    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", body
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", body
    if body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        return "image/webp", body
    if body.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif", body
    if body[4:12] in {b"ftypavif", b"ftypavis"}:
        return "image/avif", body
    return None


class CommentCache:
    def __init__(self, directory, owner):
        self.directory = directory
        self.owner = owner
        self.db = self.open(directory)

    def open(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / CACHE_NAME
        db = sqlite3.connect(path)
        try:
            app_id = db.execute("PRAGMA application_id").fetchone()[0]
            if app_id != CACHE_ID and (app_id or db.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()):
                raise ValueError("该目录下已有其他数据库，请选择另一个目录。")
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cache_metadata'").fetchone():
                owner = db.execute("SELECT owner FROM cache_metadata").fetchone()
                if owner and owner[0] != self.owner:
                    raise ValueError("该目录已用于另一份 Relayfold 工作区，请选择其他目录。")
            db.row_factory = sqlite3.Row
            db.executescript(f"""
                PRAGMA application_id={CACHE_ID};
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS cache_metadata (owner TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS accounts (
                    scope TEXT PRIMARY KEY, notes_at REAL, inbox_at REAL, failed TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS notes (
                    scope TEXT NOT NULL REFERENCES accounts(scope) ON DELETE CASCADE,
                    id TEXT NOT NULL, position INTEGER, title TEXT NOT NULL, href TEXT NOT NULL, cover_url TEXT NOT NULL,
                    comments TEXT, comments_at REAL, cover BLOB, cover_mime TEXT, cover_source TEXT,
                    PRIMARY KEY (scope, id)
                );
                CREATE TABLE IF NOT EXISTS observed (
                    scope TEXT NOT NULL, note_id TEXT NOT NULL, comment_id TEXT NOT NULL, unread INTEGER NOT NULL,
                    PRIMARY KEY (scope, note_id, comment_id),
                    FOREIGN KEY (scope, note_id) REFERENCES notes(scope, id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS deleted_notes (
                    scope TEXT NOT NULL REFERENCES accounts(scope) ON DELETE CASCADE,
                    id TEXT NOT NULL,
                    PRIMARY KEY (scope, id)
                );
                CREATE TABLE IF NOT EXISTS received_sync (
                    scope TEXT PRIMARY KEY REFERENCES accounts(scope) ON DELETE CASCADE, updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS received_comments (
                    scope TEXT NOT NULL REFERENCES accounts(scope) ON DELETE CASCADE,
                    note_id TEXT NOT NULL, comment_id TEXT NOT NULL, occurred_at INTEGER NOT NULL,
                    unread INTEGER NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY (scope, note_id, comment_id)
                );
                CREATE INDEX IF NOT EXISTS received_unread ON received_comments(scope) WHERE unread=1;
                CREATE INDEX IF NOT EXISTS unread_comments ON observed(scope) WHERE unread=1;
            """)
            with db:
                db.execute("INSERT OR IGNORE INTO cache_metadata VALUES (?)", (self.owner,))
            return db
        except Exception:
            db.close()
            raise

    def change_directory(self, directory, *, recover_existing=False):
        if directory == self.directory:
            return self.db, self.directory
        target = self.open(directory)
        try:
            deadline = monotonic() + 8

            def check_time(_status, remaining, _total):
                if remaining and monotonic() >= deadline:
                    raise sqlite3.OperationalError("Comment cache migration timed out")

            if not recover_existing:
                self.db.backup(target, pages=256, progress=check_time, sleep=0.05)
        except Exception:
            target.close()
            raise
        previous = (self.db, self.directory)
        self.db, self.directory = target, directory
        return previous

    def forget(self, scopes):
        with self.db:
            self.db.executemany("DELETE FROM accounts WHERE scope=?", ((scope,) for scope in scopes))

    def account(self, scope):
        return self.db.execute("SELECT * FROM accounts WHERE scope=?", (scope,)).fetchone()

    def notes(self, scope):
        return self.db.execute("""
            SELECT id, title, href, cover_url, cover IS NOT NULL AS has_cover FROM notes
            WHERE scope=? AND position IS NOT NULL ORDER BY position
        """, (scope,)).fetchall()

    def note(self, scope, note_id):
        return self.db.execute("""
            SELECT id, title, href, position, cover_url, cover IS NOT NULL AS has_cover, comments, comments_at
            FROM notes WHERE scope=? AND id=?
        """, (scope, note_id)).fetchone()

    def save_notes(self, scope, notes):
        with self.db:
            self.db.execute("""
                INSERT INTO accounts(scope, notes_at) VALUES(?, ?)
                ON CONFLICT(scope) DO UPDATE SET notes_at=excluded.notes_at
            """, (scope, time()))
            deleted = {row[0] for row in self.db.execute("SELECT id FROM deleted_notes WHERE scope=?", (scope,))}
            notes = [note for note in notes if note["id"] not in deleted]
            self.db.execute("UPDATE notes SET position=NULL WHERE scope=? AND position IS NOT NULL", (scope,))
            self.db.executemany("""
                INSERT INTO notes(scope,id,position,title,href,cover_url) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope,id) DO UPDATE SET position=excluded.position,title=excluded.title,href=excluded.href,
                cover_url=CASE WHEN excluded.cover_url='' THEN notes.cover_url ELSE excluded.cover_url END
            """, ((scope, note["id"], idx, note["title"], note["href"], note["cover"]) for idx, note in enumerate(notes)))
        return notes

    def is_deleted(self, scope, note_id):
        return self.db.execute("SELECT 1 FROM deleted_notes WHERE scope=? AND id=?", (scope, note_id)).fetchone() is not None

    def mark_deleted(self, scope, note_ids):
        note_ids = tuple(note_ids)
        if not note_ids:
            return
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO accounts(scope) VALUES (?)", (scope,))
            self.db.executemany("INSERT OR IGNORE INTO deleted_notes VALUES (?, ?)", ((scope, ident) for ident in note_ids))
            self.db.executemany("DELETE FROM notes WHERE scope=? AND id=?", ((scope, ident) for ident in note_ids))
            self.db.executemany("DELETE FROM received_comments WHERE scope=? AND note_id=?", ((scope, ident) for ident in note_ids))

    def received_at(self, scope):
        row = self.db.execute("SELECT updated_at FROM received_sync WHERE scope=?", (scope,)).fetchone()
        return row[0] if row else None

    def received(self, scope):
        return [{**json.loads(row["payload"]), "unread": bool(row["unread"])} for row in self.db.execute("""
            SELECT payload, unread FROM received_comments WHERE scope=? ORDER BY occurred_at DESC, rowid DESC
        """, (scope,))]

    def received_message(self, scope, note_id, comment_id):
        row = self.db.execute("""
            SELECT payload FROM received_comments WHERE scope=? AND note_id=? AND comment_id=?
        """, (scope, note_id, comment_id)).fetchone()
        return json.loads(row["payload"]) if row else None

    def received_keys(self, scope):
        return {(row[0], row[1]) for row in self.db.execute(
            "SELECT note_id, comment_id FROM received_comments WHERE scope=?", (scope,))}

    def save_received(self, scope, messages, *, updated=True):
        baseline = self.received_at(scope) is None
        arrivals = []
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO accounts(scope) VALUES (?)", (scope,))
            for message in messages:
                note_id, comment_id = message["note_id"], message["comment"]["id"]
                if self.is_deleted(scope, note_id):
                    continue
                unread = not baseline
                if baseline:
                    old = self.db.execute("SELECT unread FROM observed WHERE scope=? AND note_id=? AND comment_id=?",
                                          (scope, note_id, comment_id)).fetchone()
                    unread = bool(old and old[0])
                payload = json.dumps(message, ensure_ascii=False)
                inserted = self.db.execute("""
                    INSERT OR IGNORE INTO received_comments VALUES (?, ?, ?, ?, ?, ?)
                """, (scope, note_id, comment_id, message["comment"]["created_at"] or 0, unread, payload)).rowcount
                if not inserted:
                    self.db.execute("UPDATE received_comments SET payload=? WHERE scope=? AND note_id=? AND comment_id=?",
                                    (payload, scope, note_id, comment_id))
                elif unread and not baseline:
                    arrivals.append({"note_id": note_id, "comment_id": comment_id})
                if message.get("href"):
                    self.db.execute("""
                        INSERT OR IGNORE INTO notes(scope,id,title,href,cover_url) VALUES (?, ?, ?, ?, '')
                    """, (scope, note_id, message["note_title"], message["href"]))
            if updated:
                self.db.execute("""
                    INSERT INTO received_sync VALUES (?, ?) ON CONFLICT(scope) DO UPDATE SET updated_at=excluded.updated_at
                """, (scope, time()))
        return arrivals

    def received_unread(self, scope, note_id=None):
        return {row[0] for row in self.db.execute("""
            SELECT comment_id FROM received_comments WHERE scope=? AND unread=1 AND (? IS NULL OR note_id=?)
        """, (scope, note_id, note_id))}

    def mark_received_read(self, scope, note_id, comment_id):
        with self.db:
            return self.db.execute("""
                UPDATE received_comments SET unread=0 WHERE scope=? AND note_id=? AND comment_id=? AND unread=1
            """, (scope, note_id, comment_id)).rowcount > 0

    def save_comments(self, scope, note_id, result, *, merge=False):
        row = self.note(scope, note_id)
        baseline = row["comments_at"] is None
        previous_inbox = self.account(scope)["inbox_at"]
        arrived = []
        previous = {item["id"]: item for item in json.loads(row["comments"])["comments"]} if row["comments"] else {}
        for parent in result["comments"]:
            earlier = previous.get(parent["id"], {})
            if parent.get("children_more") and earlier.get("children"):
                # A top-level refresh includes only the server's preview of an expanded thread.
                children = {item["id"]: item for item in parent["children"]}
                children.update((item["id"], item) for item in earlier["children"] if item["id"] not in children)
                parent["children"] = list(children.values())
                if not earlier["children_more"] and len(children) >= parent["children_count"]:
                    parent["children_more"] = False
        if merge or result.get("has_more"):
            present = {comment["id"] for comment in result["comments"]}
            result["comments"].extend(comment for ident, comment in previous.items() if ident not in present)
        with self.db:
            self.db.execute("UPDATE notes SET comments=?,comments_at=? WHERE scope=? AND id=?",
                            (json.dumps(result, ensure_ascii=False), time(), scope, note_id))
            for comment in result["comments"]:
                if comment["by_owner"]:
                    continue
                created = comment["created_at"] or 0
                if created > 100_000_000_000:
                    created /= 1000
                unread = not baseline or bool(previous_inbox and created > previous_inbox)
                inserted = self.db.execute("""
                    INSERT OR IGNORE INTO observed VALUES (?, ?, ?, ?)
                """, (scope, note_id, comment["id"], unread)).rowcount
                if inserted and unread:
                    arrived.append(comment["id"])
        return arrived

    def save_children(self, scope, note_id, root_id, children):
        stored = json.loads(self.note(scope, note_id)["comments"])
        parent = next(comment for comment in stored["comments"] if comment["id"] == root_id)
        parent.update(children)
        with self.db:
            self.db.execute("UPDATE notes SET comments=? WHERE scope=? AND id=?",
                            (json.dumps(stored, ensure_ascii=False), scope, note_id))

    def finish_inbox(self, scope, failed, *, successful):
        with self.db:
            self.db.execute("UPDATE accounts SET inbox_at=COALESCE(?, inbox_at), failed=? WHERE scope=?",
                            (time() if successful else None, json.dumps(failed), scope))

    def unread_for(self, scope, note_id):
        return {row[0] for row in self.db.execute("""
            SELECT o.comment_id FROM observed o JOIN notes n ON n.scope=o.scope AND n.id=o.note_id
            WHERE o.scope=? AND o.note_id=? AND o.unread=1
              AND EXISTS (SELECT 1 FROM json_each(n.comments, '$.comments') c WHERE c.value->>'id'=o.comment_id)
        """, (scope, note_id))}

    def unread_count(self, scope):
        return self.db.execute("""
            SELECT count(*) FROM observed o JOIN notes n ON n.scope=o.scope AND n.id=o.note_id
            WHERE o.scope=? AND o.unread=1 AND n.position IS NOT NULL
              AND EXISTS (SELECT 1 FROM json_each(n.comments, '$.comments') c WHERE c.value->>'id'=o.comment_id)
        """, (scope,)).fetchone()[0]

    def mark_read(self, scope, note_id, comment_id):
        with self.db:
            return self.db.execute("""
                UPDATE observed SET unread=0 WHERE scope=? AND note_id=? AND comment_id=? AND unread=1
            """, (scope, note_id, comment_id)).rowcount > 0

    def cover(self, scope, note_id):
        return self.db.execute("SELECT cover_url, cover_mime, cover_source, cover FROM notes WHERE scope=? AND id=?",
                               (scope, note_id)).fetchone()

    def save_cover(self, scope, note_id, url, image):
        mime, body = image
        with self.db:
            self.db.execute("""
                UPDATE notes SET cover_mime=?, cover=?, cover_source=? WHERE scope=? AND id=? AND cover_url=?
            """, (mime, body, url, scope, note_id, url))

    @staticmethod
    def cover_data(row):
        return f"data:{row['cover_mime']};base64,{base64.b64encode(row['cover']).decode('ascii')}" if row and row["cover"] else None

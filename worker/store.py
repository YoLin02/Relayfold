import json
import sqlite3
from time import time
from datetime import datetime, timezone
from uuid import uuid4


from catalog import PLATFORMS, public_catalog


def new_id():
    return uuid4().hex


def now():
    return datetime.now(timezone.utc).isoformat()


def group_name(name):
    name = name.strip()
    if not 1 <= len(name) <= 30:
        raise ValueError("发布组名称须为 1–30 字。")
    return name


ACCENT_THEMES = ("neutral", "sky", "cyan", "violet")
SCHEDULE_GRACE_SECONDS = 60
HISTORY_PAGE_SIZE = 50
GROUP_MODES = {"regular", "custom"}
MAX_ACCOUNTS_PER_ADD = 100
HISTORY_FIELDS = """
    t.id, t.batch_id, t.binding_id, t.target_label, t.status, t.detail, t.receipt, t.updated_at,
    b.group_id, COALESCE(json_extract(t.content, '$.title'), b.title) AS title,
    b.media_name, b.created_at, b.kind, b.scheduled_at, a.platform, a.slot, a.active
"""
HISTORY_FROM = "FROM tasks t JOIN batches b ON b.id=t.batch_id JOIN bindings a ON a.id=t.binding_id"


def validate_schedule(timestamp):
    if type(timestamp) is not int or timestamp <= int(time()) or timestamp > 253402300799:
        raise ValueError("请选择将来的发布时间。")


def history_boundary(value):
    if value is None:
        return None
    try:
        if not isinstance(value, str):
            raise ValueError
        timestamp = datetime.fromisoformat(value)
        if timestamp.utcoffset() is None:
            raise ValueError
        return timestamp.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError) as exc:
        raise ValueError("记录筛选日期无效。") from exc


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS groups (
                id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'regular'
            );
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS bindings (
                id TEXT PRIMARY KEY, group_id TEXT NOT NULL REFERENCES groups(id),
                platform TEXT NOT NULL, label TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
                session_proof TEXT, account_proof TEXT, login_status TEXT NOT NULL DEFAULT 'unbound', checked_at TEXT,
                slot INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS batches (
                id TEXT PRIMARY KEY, group_id TEXT NOT NULL REFERENCES groups(id),
                title TEXT NOT NULL, description TEXT NOT NULL, declaration TEXT,
                media_path TEXT NOT NULL, media_name TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches(id),
                binding_id TEXT NOT NULL REFERENCES bindings(id), target_label TEXT NOT NULL,
                status TEXT NOT NULL, detail TEXT NOT NULL, receipt TEXT, updated_at TEXT NOT NULL,
                UNIQUE(batch_id, binding_id)
            );
            CREATE INDEX IF NOT EXISTS tasks_by_status ON tasks(status, updated_at);
            CREATE INDEX IF NOT EXISTS batches_by_group_created ON batches(group_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS task_events (
                id INTEGER PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                at TEXT NOT NULL, detail TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS task_events_by_task ON task_events(task_id, id);
        """)
        columns = {row["name"] for row in self.db.execute("PRAGMA table_info(batches)")}
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            binding_columns = {row["name"] for row in self.db.execute("PRAGMA table_info(bindings)")}
            if "account_proof" not in binding_columns:
                self.db.execute("ALTER TABLE bindings ADD COLUMN account_proof TEXT")
            if "slot" not in binding_columns:
                self.db.execute("ALTER TABLE bindings ADD COLUMN slot INTEGER NOT NULL DEFAULT 1")
            if not any(row["name"] == "mode" for row in self.db.execute("PRAGMA table_info(groups)")):
                self.db.execute("ALTER TABLE groups ADD COLUMN mode TEXT NOT NULL DEFAULT 'regular'")
            self.db.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS current_binding_slot
                ON bindings(group_id, platform, slot) WHERE active = 1
            """)
            self.db.execute("DROP INDEX IF EXISTS current_binding")
            for name, default in (("kind", "video"), ("media_files", "[]"), ("options", "{}")):
                if name not in columns:
                    self.db.execute(f"ALTER TABLE batches ADD COLUMN {name} TEXT NOT NULL DEFAULT '{default}'")
            if not any(row["name"] == "content" for row in self.db.execute("PRAGMA table_info(tasks)")):
                self.db.execute("ALTER TABLE tasks ADD COLUMN content TEXT")
            if "scheduled_at" not in columns:
                self.db.execute("ALTER TABLE batches ADD COLUMN scheduled_at INTEGER")
            self.db.execute("CREATE INDEX IF NOT EXISTS batches_by_schedule ON batches(scheduled_at) WHERE scheduled_at IS NOT NULL")
        if not self.db.execute("SELECT 1 FROM groups").fetchone():
            a = self.create_group("账号 A")
            self.create_group("账号 B")
            self.select_group(a)
        with self.db:
            for group in self.db.execute("SELECT id FROM groups WHERE mode='regular'").fetchall():
                for platform in PLATFORMS:
                    self.db.execute("INSERT OR IGNORE INTO bindings(id, group_id, platform) VALUES (?, ?, ?)",
                                    (new_id(), group["id"], platform))
            self.db.execute("UPDATE bindings SET login_status='saved' WHERE login_status='ready'")
            self.db.execute("""
                UPDATE tasks SET status='failed', detail='上传准备被中断，可重试。', updated_at=?
                WHERE status='running'
            """, (now(),))
            self.db.execute("""
                UPDATE tasks SET status='needs_review', detail='提交期间程序退出，请先到平台后台核对。', updated_at=?
                WHERE status IN ('submitting','verifying')
            """, (now(),))
            self.db.execute("""
                UPDATE tasks SET status='missed', detail='重启后已超过预约时间，可重新改期。', updated_at=?
                WHERE status='queued' AND batch_id IN (SELECT id FROM batches WHERE scheduled_at < ?)
            """, (now(), int(time()) - SCHEDULE_GRACE_SECONDS))

    def require_group(self, group_id):
        row = self.db.execute("SELECT mode FROM groups WHERE id=?", (group_id,)).fetchone()
        if not row:
            raise ValueError("发布组不存在。")
        return row

    def create_group(self, name, mode="regular"):
        name = group_name(name)
        if not isinstance(mode, str) or mode not in GROUP_MODES:
            raise ValueError("请选择常规组或自定义组。")
        group_id = new_id()
        try:
            with self.db:
                self.db.execute("INSERT INTO groups(id,name,created_at,mode) VALUES (?, ?, ?, ?)", (group_id, name, now(), mode))
                if mode == "regular":
                    self.db.executemany("INSERT INTO bindings(id, group_id, platform) VALUES (?, ?, ?)",
                                        [(new_id(), group_id, platform) for platform in PLATFORMS])
        except sqlite3.IntegrityError as exc:
            raise ValueError("已存在同名发布组。") from exc
        return group_id

    def add_accounts(self, group_id, platform, count):
        if not isinstance(platform, str) or platform not in PLATFORMS:
            raise ValueError("请选择要添加的平台。")
        if type(count) is not int or not 1 <= count <= MAX_ACCOUNTS_PER_ADD:
            raise ValueError(f"请输入 1–{MAX_ACCOUNTS_PER_ADD} 的账号数量。")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if self.require_group(group_id)["mode"] != "custom":
                raise ValueError("请在自定义组中添加平台账号。")
            last = self.db.execute("""
                SELECT COALESCE(MAX(slot), 0) FROM bindings WHERE group_id=? AND platform=?
            """, (group_id, platform)).fetchone()[0]
            self.db.executemany("INSERT INTO bindings(id,group_id,platform,slot) VALUES (?, ?, ?, ?)",
                                [(new_id(), group_id, platform, slot) for slot in range(last + 1, last + count + 1)])

    def rename_group(self, group_id, name):
        self.require_group(group_id)
        try:
            with self.db:
                self.db.execute("UPDATE groups SET name=? WHERE id=?", (group_name(name), group_id))
        except sqlite3.IntegrityError as exc:
            raise ValueError("已存在同名发布组。") from exc

    def group_binding_ids(self, group_id):
        return [row["id"] for row in self.db.execute("SELECT id FROM bindings WHERE group_id=?", (group_id,))]

    def delete_group(self, group_id):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            self.require_group(group_id)
            fallback = self.db.execute(
                "SELECT id FROM groups WHERE id<>? ORDER BY created_at, id LIMIT 1", (group_id,)
            ).fetchone()
            if not fallback:
                raise ValueError("至少保留一个发布组。")
            if self.db.execute("""
                SELECT 1 FROM tasks JOIN batches ON tasks.batch_id=batches.id
                WHERE batches.group_id=? AND tasks.status IN ('scheduled','queued','running','submitting','verifying') LIMIT 1
            """, (group_id,)).fetchone():
                raise ValueError("此发布组还有排队或运行中的任务，或尚未取消的定时任务。")
            batch_ids = [row["id"] for row in self.db.execute("SELECT id FROM batches WHERE group_id=?", (group_id,))]
            self.db.execute("DELETE FROM tasks WHERE batch_id IN (SELECT id FROM batches WHERE group_id=?)", (group_id,))
            self.db.execute("DELETE FROM batches WHERE group_id=?", (group_id,))
            self.db.execute("DELETE FROM bindings WHERE group_id=?", (group_id,))
            self.db.execute("DELETE FROM groups WHERE id=?", (group_id,))
            self.db.execute("UPDATE settings SET value=? WHERE key='active_group' AND value=?", (fallback["id"], group_id))
        return batch_ids

    def select_group(self, group_id):
        self.require_group(group_id)
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES ('active_group', ?)", (group_id,))

    def set_platform_region(self, region):
        if region not in ("domestic", "international"):
            raise ValueError("请选择国内平台或国外平台。")
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES ('platform_region', ?)", (region,))

    def set_accent_theme(self, theme):
        if theme not in ACCENT_THEMES:
            raise ValueError("请选择可用的主题。")
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES ('accent_theme', ?)", (theme,))

    def binding(self, binding_id):
        row = self.db.execute("SELECT * FROM bindings WHERE id=? AND active=1", (binding_id,)).fetchone()
        if not row:
            raise ValueError("这个账号绑定已失效，请刷新界面。")
        return dict(row)

    def bind(self, binding_id, label, proof, *, account_proof=None):
        label = label.strip()
        if not 1 <= len(label) <= 40:
            raise ValueError("请输入 1–40 字的账号昵称或备注。")
        current = self.binding(binding_id)
        if current["account_proof"]:
            matches = current["account_proof"] == account_proof
        else:
            matches = not current["session_proof"] or current["session_proof"] == proof
        if not matches:
            self.login_status(binding_id, "attention")
            raise ValueError("当前会话与已绑定账号不一致。请切回原账号，或新建会话。")
        other = self.db.execute("""
            SELECT 1 FROM bindings WHERE active=1 AND platform=? AND id<>?
              AND (session_proof=? OR account_proof=?)
        """, (current["platform"], binding_id, proof, account_proof)).fetchone()
        if other:
            raise ValueError("这个平台账号已绑定，请扫码登录另一个账号。")
        with self.db:
            self.db.execute("""
                UPDATE bindings SET label=?, session_proof=?, account_proof=COALESCE(?, account_proof),
                  login_status='ready', checked_at=? WHERE id=?
            """, (label, proof, account_proof, now(), binding_id))

    def login_status(self, binding_id, status):
        with self.db:
            self.db.execute("UPDATE bindings SET login_status=?, checked_at=? WHERE id=?",
                            (status, now(), binding_id))

    def replace_binding(self, binding_id):
        binding = self.binding(binding_id)
        with self.db:
            self.db.execute("UPDATE bindings SET active=0 WHERE id=?", (binding_id,))
            self.db.execute("INSERT INTO bindings(id, group_id, platform, slot) VALUES (?, ?, ?, ?)",
                            (new_id(), binding["group_id"], binding["platform"], binding["slot"]))
            self.db.execute("""
                UPDATE tasks SET status='failed', detail='原账号会话已被替换，请用新绑定创建任务。', updated_at=?
                WHERE binding_id=? AND status IN ('scheduled','missed','queued')
            """, (now(), binding_id))

    def delete_binding(self, binding_id):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            binding = self.binding(binding_id)
            if self.db.execute("""
                SELECT 1 FROM tasks WHERE binding_id=?
                AND status IN ('scheduled','missed','queued','running','submitting','verifying') LIMIT 1
            """, (binding_id,)).fetchone():
                raise ValueError("该账号还有发布任务或预约，请等任务结束或取消预约后再删除。")
            self.db.execute("""
                UPDATE bindings SET active=0, session_proof=NULL, account_proof=NULL,
                    login_status='unbound', checked_at=NULL WHERE id=?
            """, (binding_id,))
            if self.require_group(binding["group_id"])["mode"] == "regular":
                self.db.execute("INSERT INTO bindings(id,group_id,platform,slot) VALUES (?, ?, ?, ?)",
                                (new_id(), binding["group_id"], binding["platform"], binding["slot"]))

    def enqueue(self, batch_id, group_id, binding_ids, title, description, declaration, path, media_name,
                *, kind="video", files=None, options=None, contents=None, scheduled_at=None):
        if scheduled_at is not None:
            validate_schedule(scheduled_at)
        status, detail = ("scheduled", "等待预约时间。") if scheduled_at is not None else ("queued", "已加入本地队列。")
        bindings = [self.binding(binding_id) for binding_id in binding_ids]
        if any(b["group_id"] != group_id or b["login_status"] not in ("ready", "saved") for b in bindings):
            raise ValueError("发布目标必须属于此发布组，并且已绑定登录。")
        specs = [PLATFORMS[b["platform"]] for b in bindings]
        if any(kind not in spec.kinds for spec in specs):
            raise ValueError("所选账号的平台不支持此内容类型。")
        if any(b["platform"] == "douyin" for b in bindings) and declaration is None:
            raise ValueError("请选择抖音作品声明。")
        if any(len((contents or {}).get(b["id"], {}).get("title", title)) > PLATFORMS[b["platform"]].title_limit
               for b in bindings):
            raise ValueError("标题超出所选平台限制。")
        timestamp = now()
        with self.db:
            self.db.execute("""
                INSERT INTO batches(id,group_id,title,description,declaration,media_path,media_name,created_at,kind,media_files,options,scheduled_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (batch_id, group_id, title, description, declaration, str(path), media_name, timestamp, kind,
                  json.dumps(files or [], ensure_ascii=False), json.dumps(options or {}, ensure_ascii=False), scheduled_at))
            self.db.executemany("""
                INSERT INTO tasks(id, batch_id, binding_id, target_label, status, detail, updated_at, content)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [(new_id(), batch_id, b["id"], b["label"], status, detail, timestamp,
                   json.dumps(contents[b["id"]], ensure_ascii=False) if contents else None) for b in bindings])

    def release_scheduled(self, current):
        if not self.db.execute("""
            SELECT 1 FROM batches JOIN tasks ON tasks.batch_id=batches.id
            WHERE batches.scheduled_at <= ? AND tasks.status='scheduled' LIMIT 1
        """, (current,)).fetchone():
            return False
        with self.db:
            self.db.execute("""
                UPDATE tasks SET status='missed', detail='已超过预约时间，可重新改期。', updated_at=?
                WHERE status='scheduled' AND batch_id IN (SELECT id FROM batches WHERE scheduled_at < ?)
            """, (now(), current - SCHEDULE_GRACE_SECONDS))
            self.db.execute("""
                UPDATE tasks SET status='queued', detail='预约时间已到，已加入发布队列。', updated_at=?
                WHERE status='scheduled' AND batch_id IN (SELECT id FROM batches WHERE scheduled_at <= ?)
            """, (now(), current))
        return True

    def change_schedule(self, batch_id, scheduled_at=None):
        if scheduled_at is not None:
            validate_schedule(scheduled_at)
        status, detail = ("canceled", "已取消定时发布。") if scheduled_at is None else ("scheduled", "已改期，等待预约时间。")
        with self.db:
            if self.db.execute("""
                SELECT 1 FROM tasks WHERE batch_id=? AND status IN ('queued','running','submitting','verifying',
                    'submitted','draft_ready','needs_review','action_required') LIMIT 1
            """, (batch_id,)).fetchone():
                raise ValueError("这批预约已进入执行流程，无法再改期或取消。")
            updated = self.db.execute("""
                UPDATE tasks SET status=?, detail=?, updated_at=?
                WHERE batch_id=? AND status IN ('scheduled','missed')
            """, (status, detail, now(), batch_id))
            if not updated.rowcount:
                raise ValueError("这批预约已取消或不可用，请刷新记录。")
            if scheduled_at is not None:
                self.db.execute("UPDATE batches SET scheduled_at=? WHERE id=?", (scheduled_at, batch_id))

    def task(self, task_id):
        row = self.db.execute("""
            SELECT t.*, b.group_id, b.title, b.description, b.declaration, b.media_path, b.kind, b.media_files, b.options,
                   a.platform, a.active
            FROM tasks t JOIN batches b ON b.id=t.batch_id JOIN bindings a ON a.id=t.binding_id
            WHERE t.id=?
        """, (task_id,)).fetchone()
        if not row:
            raise ValueError("任务不存在。")
        task = dict(row)
        task["media_files"] = json.loads(row["media_files"]) or ([row["media_path"]] if row["media_path"] else [])
        task["options"] = json.loads(row["options"])
        snapshot = task.pop("content")
        task.update(json.loads(snapshot) if snapshot is not None else {"tags": [], "cover": ""})
        return task

    def next_task(self):
        row = self.db.execute("""
            SELECT id FROM tasks WHERE status='queued' ORDER BY updated_at, rowid LIMIT 1
        """).fetchone()
        return self.task(row["id"]) if row else None

    def task_status(self, task_id):
        row = self.db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
        return row["status"] if row else None

    def delete_task(self, task_id):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT status,batch_id FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise ValueError("这条发布记录已删除。")
            if row["status"] in {"scheduled", "queued", "running", "submitting", "verifying"}:
                raise ValueError("请等任务结束或先取消预约，再删除这条记录。")
            self.db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
            batch_id = row["batch_id"]
            removed = self.db.execute("""
                DELETE FROM batches WHERE id=? AND NOT EXISTS (SELECT 1 FROM tasks WHERE batch_id=batches.id)
            """, (batch_id,))
            return batch_id if removed.rowcount else None

    def history(self, group_id, start=None, end=None, page=0):
        self.require_group(group_id)
        if type(page) is not int or not 0 <= page <= 1_000_000:
            raise ValueError("发布记录页码无效。")
        start, end = history_boundary(start), history_boundary(end)
        if start and end and start >= end:
            raise ValueError("开始日期不能晚于结束日期。")
        where = ["b.group_id=?"]
        params = [group_id]
        if start:
            where.append("b.created_at>=?")
            params.append(start)
        if end:
            where.append("b.created_at<?")
            params.append(end)
        rows = self.db.execute(f"""
            SELECT {HISTORY_FIELDS} {HISTORY_FROM}
            WHERE {' AND '.join(where)}
            ORDER BY b.created_at DESC, t.rowid LIMIT ? OFFSET ?
        """, (*params, HISTORY_PAGE_SIZE + 1, page * HISTORY_PAGE_SIZE)).fetchall()
        return {"tasks": [dict(row) for row in rows[:HISTORY_PAGE_SIZE]],
                "has_more": len(rows) > HISTORY_PAGE_SIZE}

    def transition(self, task_id, previous, status, detail, receipt=None):
        with self.db:
            cursor = self.db.execute("""
                UPDATE tasks SET status=?, detail=?, receipt=?, updated_at=? WHERE id=? AND status=?
            """, (status, detail, receipt, now(), task_id, previous))
            if cursor.rowcount != 1:
                raise ValueError("任务状态已变化，请刷新后再操作。")

    def record_task_event(self, task_id, detail, *, progress=False):
        timestamp = now()
        with self.db:
            self.db.execute("INSERT INTO task_events(task_id, at, detail) VALUES (?, ?, ?)",
                            (task_id, timestamp, detail))
            if progress:
                self.db.execute("UPDATE tasks SET detail=?, updated_at=? WHERE id=? AND status='running'",
                                (detail, timestamp, task_id))

    def task_diagnostics(self, task_id):
        rows = self.db.execute("""
            SELECT at,detail FROM (SELECT id,at,detail FROM task_events WHERE task_id=?
                ORDER BY id DESC LIMIT 200) ORDER BY id
        """, (task_id,))
        return [dict(row) for row in rows]

    def retry(self, task_id):
        task = self.task(task_id)
        binding = self.binding(task["binding_id"])
        if task["status"] not in ("failed", "action_required") or binding["login_status"] not in ("ready", "saved"):
            raise ValueError("请先恢复原账号登录，只有确认未提交的任务可以重试。")
        self.transition(task_id, task["status"], "queued", "已重新排队。")

    def state(self):
        groups = [dict(row) for row in self.db.execute("SELECT id, name, mode FROM groups ORDER BY created_at")]
        active = self.db.execute("SELECT value FROM settings WHERE key='active_group'").fetchone()
        region = self.db.execute("SELECT value FROM settings WHERE key='platform_region'").fetchone()
        theme = self.db.execute("SELECT value FROM settings WHERE key='accent_theme'").fetchone()
        bindings = [dict(row) for row in self.db.execute("""
            SELECT id, group_id, platform, slot, label, login_status, checked_at FROM bindings WHERE active=1
            ORDER BY platform, slot
        """)]
        tasks = [dict(row) for row in self.db.execute(f"""
            WITH history AS (
                SELECT {HISTORY_FIELDS},
                       row_number() OVER (PARTITION BY b.group_id ORDER BY b.created_at DESC, t.rowid) AS position
                {HISTORY_FROM}
            ) SELECT * FROM history WHERE position<=100 OR status IN ('scheduled','missed','queued','running','submitting','verifying')
              ORDER BY created_at DESC, position
        """)]
        return {"groups": groups, "active_group_id": active["value"] if active else groups[0]["id"],
                "platform_region": region["value"] if region else "domestic",
                "accent_theme": theme["value"] if theme and theme["value"] in ACCENT_THEMES else "neutral",
                "bindings": bindings, "tasks": tasks, "platforms": public_catalog()}

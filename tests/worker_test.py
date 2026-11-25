import sys
import tempfile
import unittest
from importlib import import_module
from inspect import signature
from pathlib import Path
from time import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))

from adapters import normalize_options
from browser import receipt_from_json, submission_response
from catalog import PLATFORMS
import session_backup
from store import SCHEDULE_GRACE_SECONDS, Store


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db_path = Path(self.folder.name) / "store.sqlite3"
        self.store = Store(self.db_path)
        self.addCleanup(lambda: self.store.db.close())
        state = self.store.state()
        self.group, self.other = state["groups"]
        self.target = next(row for row in state["bindings"] if row["group_id"] == self.group["id"] and row["platform"] == "douyin")
        self.store.bind(self.target["id"], "原账号", "creator-proof")

    def enqueue(self):
        self.store.enqueue("batch", self.group["id"], [self.target["id"]], "视频", "", "无需添加自主声明", "demo.mp4", "demo.mp4")
        return self.store.next_task()

    def test_interrupted_submission_requires_review_after_reopen(self):
        task = self.enqueue()
        self.store.transition(task["id"], "queued", "running", "Upload")
        self.store.transition(task["id"], "running", "submitting", "Submit")
        self.store.select_group(self.other["id"])
        self.store.db.close()
        self.store = Store(self.db_path)
        self.assertEqual(self.store.state()["active_group_id"], self.other["id"])
        interrupted = self.store.task(task["id"])
        self.assertEqual(interrupted["status"], "needs_review")
        self.assertEqual(interrupted["binding_id"], self.target["id"])
        self.assertIsNone(self.store.next_task())
        with self.assertRaises(ValueError):
            self.store.retry(task["id"])

    def test_history_filters_older_batches_with_local_boundaries(self):
        for index in range(103):
            self.store.enqueue(f"batch-{index}", self.group["id"], [self.target["id"]],
                               str(index), "", "无需添加自主声明", "", "")
        with self.store.db:
            self.store.db.execute("UPDATE tasks SET status='submitted'")
            self.store.db.execute("UPDATE batches SET created_at='2026-11-25T02:00:00+00:00'")
            self.store.db.execute("UPDATE batches SET created_at='2026-11-24T16:00:00+00:00' WHERE id='batch-0'")
            self.store.db.execute("UPDATE batches SET created_at='2026-11-25T16:00:00+00:00' WHERE id='batch-1'")
        self.assertNotIn("batch-0", [task["batch_id"] for task in self.store.state()["tasks"]])
        selection = {"start": "2026-11-25T00:00:00+08:00", "end": "2026-11-26T00:00:00+08:00"}
        first = self.store.history(self.group["id"], **selection)
        last = self.store.history(self.group["id"], **selection, page=2)
        self.assertEqual(len(first["tasks"]), 50)
        self.assertTrue(first["has_more"])
        self.assertEqual([task["batch_id"] for task in last["tasks"]], ["batch-102", "batch-0"])
        self.assertFalse(last["has_more"])
        self.assertEqual(self.store.history(self.other["id"], **selection)["tasks"], [])

    def test_delete_task_preserves_active_siblings_and_removes_diagnostics(self):
        group_id = self.group["id"]
        second = next(row["id"] for row in self.store.state()["bindings"]
                      if row["group_id"] == group_id and row["platform"] == "xiaohongshu")
        self.store.bind(second, "小红书测试", "xiaohongshu-fixture-proof")
        self.store.enqueue("shared", group_id, [self.target["id"], second],
                           "视频", "", "无需添加自主声明", "demo.mp4", "demo.mp4")
        first, later = self.store.history(group_id)["tasks"]
        self.store.record_task_event(first["id"], "mock event")
        with self.assertRaisesRegex(ValueError, "任务结束"):
            self.store.delete_task(first["id"])
        self.store.transition(first["id"], "queued", "submitted", "Done", "fake-receipt")
        self.assertIsNone(self.store.delete_task(first["id"]))
        self.assertEqual(self.store.task_diagnostics(first["id"]), [])
        sibling = self.store.task(later["id"])
        self.assertEqual(sibling["status"], "queued")
        self.assertEqual(sibling["media_files"], ["demo.mp4"])
        self.store.transition(later["id"], "queued", "failed", "Done")
        self.assertEqual(self.store.delete_task(later["id"]), "shared")
        self.assertEqual(self.store.history(group_id)["tasks"], [])

    def test_rebinding_preserves_original_task_target(self):
        task = self.enqueue()
        with self.assertRaises(ValueError):
            self.store.bind(self.target["id"], "其他人", "other-creator-proof")
        self.store.replace_binding(self.target["id"])
        target = next(row for row in self.store.state()["bindings"] if row["group_id"] == self.group["id"] and row["platform"] == self.target["platform"])
        self.assertNotEqual(target["id"], task["binding_id"])
        self.assertEqual(self.store.task(task["id"])["target_label"], "原账号")
        self.assertEqual(self.store.task(task["id"])["status"], "failed")

    def test_verified_xiaohongshu_identity_survives_session_rotation(self):
        bindings = self.store.state()["bindings"]
        a = next(b for b in bindings if b["group_id"] == self.group["id"] and b["platform"] == "xiaohongshu")
        b = next(b for b in bindings if b["group_id"] == self.other["id"] and b["platform"] == "xiaohongshu")
        self.store.bind(a["id"], "原账号", "original-session")
        with self.assertRaises(ValueError):
            self.store.bind(a["id"], "原账号", "unknown-session", account_proof="verified-account")
        self.store.bind(a["id"], "原账号", "original-session", account_proof="verified-account")
        self.store.bind(a["id"], "原账号", "rotated-session", account_proof="verified-account")
        self.assertEqual(self.store.binding(a["id"])["session_proof"], "rotated-session")
        self.assertEqual(self.store.binding(a["id"])["account_proof"], "verified-account")
        with self.assertRaises(ValueError):
            self.store.bind(b["id"], "重复账号", "another-session", account_proof="verified-account")

    def test_rename_keeps_bindings_and_rejects_duplicates(self):
        group_id = self.group["id"]
        with self.assertRaisesRegex(ValueError, "同名"):
            self.store.rename_group(group_id, self.other["name"])
        self.store.rename_group(group_id, " 品牌组 ")
        self.assertIn({"id": group_id, "name": "品牌组", "mode": "regular"}, self.store.state()["groups"])
        self.assertEqual(self.store.binding(self.target["id"])["session_proof"], "creator-proof")

    def test_delete_checks_active_tasks_and_removes_only_target_group(self):
        group_id = self.group["id"]
        task = self.enqueue()
        with self.assertRaisesRegex(ValueError, "排队或运行"):
            self.store.delete_group(group_id)
        self.store.transition(task["id"], "queued", "failed", "Stopped")
        self.assertEqual(self.store.delete_group(group_id), ["batch"])
        state = self.store.state()
        self.assertEqual(state["groups"], [self.other])
        self.assertEqual(state["active_group_id"], self.other["id"])
        self.assertEqual(state["tasks"], [])
        self.assertTrue(all(binding["group_id"] == self.other["id"] for binding in state["bindings"]))
        with self.assertRaisesRegex(ValueError, "至少保留"):
            self.store.delete_group(self.other["id"])

    def test_upgrade_reuses_v1_binding_and_video_job(self):
        task = self.enqueue()
        with self.store.db:
            self.store.db.execute("DELETE FROM bindings WHERE platform NOT IN ('douyin','xiaohongshu')")
            for column in ("kind", "media_files", "options"):
                self.store.db.execute(f"ALTER TABLE batches DROP COLUMN {column}")
            self.store.db.execute("ALTER TABLE tasks DROP COLUMN content")
            self.store.db.execute("DROP INDEX current_binding_slot")
            self.store.db.execute("ALTER TABLE bindings DROP COLUMN slot")
            self.store.db.execute("ALTER TABLE groups DROP COLUMN mode")
            self.store.db.execute("CREATE UNIQUE INDEX current_binding ON bindings(group_id, platform) WHERE active=1")
        self.store.db.close()
        self.store = Store(self.db_path)
        state = self.store.state()
        self.assertEqual(len(state["bindings"]), len(PLATFORMS) * 2)
        self.assertEqual(self.store.binding(self.target["id"])["session_proof"], "creator-proof")
        self.assertEqual(self.store.task(task["id"])["kind"], "video")
        self.assertEqual(self.store.task(task["id"])["media_files"], ["demo.mp4"])
        self.assertEqual(self.store.task(task["id"])["title"], "视频")
        self.assertEqual(self.store.task(task["id"])["tags"], [])
        self.assertTrue(all(group["mode"] == "regular" for group in state["groups"]))
        self.assertEqual(self.store.binding(self.target["id"])["slot"], 1)
        self.assertTrue(self.store.history(self.group["id"])["tasks"])

    def test_custom_group_keeps_account_slots_and_replaces_only_one(self):
        custom = self.store.create_group("矩阵", "custom")
        self.assertEqual(self.store.group_binding_ids(custom), [])
        with self.assertRaisesRegex(ValueError, "自定义组"):
            self.store.add_accounts(self.group["id"], "douyin", 4)
        for platform in ("douyin", "xiaohongshu"):
            self.store.add_accounts(custom, platform, 4)
        bindings = [row for row in self.store.state()["bindings"] if row["group_id"] == custom]
        self.assertEqual(len(bindings), 8)
        self.assertEqual([row["slot"] for row in bindings], [1, 2, 3, 4] * 2)
        self.store.bind(bindings[0]["id"], "相同备注", "独立会话-0")
        with self.assertRaisesRegex(ValueError, "已绑定"):
            self.store.bind(bindings[1]["id"], "重复会话", "独立会话-0")
        for index, row in enumerate(bindings[1:], 1):
            self.store.bind(row["id"], "相同备注", f"独立会话-{index}")
        batch = "custom-batch"
        targets = [row["id"] for row in bindings]
        self.store.enqueue(batch, custom, targets, "八账号群发", "", "无需添加自主声明", "demo.mp4", "demo.mp4")
        self.store.replace_binding(targets[0])
        self.store.db.close()
        self.store = Store(self.db_path)
        restored = [row for row in self.store.state()["bindings"] if row["group_id"] == custom]
        self.assertEqual(len(restored), 8)
        self.assertEqual([row["slot"] for row in restored], [1, 2, 3, 4] * 2)
        self.assertNotEqual(restored[0]["id"], targets[0])
        self.assertEqual([row["id"] for row in restored[1:]], targets[1:])
        self.assertTrue(all(row["login_status"] == "saved" for row in restored[1:]))
        self.assertEqual([row["status"] for row in self.store.history(custom)["tasks"]].count("queued"), 7)
        self.assertEqual([row["binding_id"] for row in self.store.history(custom)["tasks"]], targets)

    def test_deleting_accounts_preserves_history_and_protects_queued_tasks(self):
        task = self.enqueue()
        with self.assertRaisesRegex(ValueError, "还有发布任务"):
            self.store.delete_binding(self.target["id"])
        self.store.transition(task["id"], "queued", "submitted", "Done", "fixture")
        self.store.delete_binding(self.target["id"])
        replacement = next(row for row in self.store.state()["bindings"]
                           if row["group_id"] == self.group["id"] and row["platform"] == "douyin")
        self.assertNotEqual(replacement["id"], self.target["id"])
        self.assertEqual((replacement["slot"], replacement["login_status"]), (1, "unbound"))
        self.assertEqual(self.store.task(task["id"])["receipt"], "fixture")
        self.assertIsNone(self.store.db.execute(
            "SELECT session_proof FROM bindings WHERE id=?", (self.target["id"],)
        ).fetchone()[0])

        custom = self.store.create_group("自定义测试", "custom")
        self.store.add_accounts(custom, "douyin", 2)
        first, second = self.store.group_binding_ids(custom)
        self.store.delete_binding(first)
        self.store.add_accounts(custom, "douyin", 1)
        active = [row for row in self.store.state()["bindings"] if row["group_id"] == custom]
        self.assertEqual([row["slot"] for row in active], [2, 3])
        self.assertEqual(active[0]["id"], second)

    def test_article_cannot_route_to_video_only_binding(self):
        with self.assertRaisesRegex(ValueError, "不支持"):
            self.store.enqueue("article", self.group["id"], [self.target["id"]], "文章", "正文", None,
                               "", "", kind="article")

    def test_platform_region_persists_without_changing_group_or_bindings(self):
        self.assertEqual(self.store.state()["platform_region"], "domestic")
        with self.assertRaisesRegex(ValueError, "请选择"):
            self.store.set_platform_region("invalid")
        self.store.set_platform_region("international")
        self.store.db.close()
        self.store = Store(self.db_path)
        state = self.store.state()
        self.assertEqual(state["platform_region"], "international")
        self.assertEqual(state["active_group_id"], self.group["id"])
        self.assertEqual(self.store.binding(self.target["id"])["session_proof"], "creator-proof")

    def test_accent_theme_defaults_and_persists(self):
        self.assertEqual(self.store.state()["accent_theme"], "neutral")
        with self.assertRaisesRegex(ValueError, "可用的主题"):
            self.store.set_accent_theme("unknown")
        self.store.set_accent_theme("sky")
        self.store.db.close()
        self.store = Store(self.db_path)
        self.assertEqual(self.store.state()["accent_theme"], "sky")
        self.assertEqual(self.store.state()["platform_region"], "domestic")
        self.store.set_accent_theme("neutral")
        self.assertEqual(self.store.state()["accent_theme"], "neutral")

    def test_schedule_can_be_moved_canceled_or_released_once(self):
        group_id = self.group["id"]
        due = int(time()) + 120
        for batch in ("move", "cancel"):
            self.store.enqueue(batch, group_id, [self.target["id"]], "视频", "", "无需添加自主声明",
                               "demo.mp4", "demo.mp4", scheduled_at=due)
        self.assertIsNone(self.store.next_task())
        self.assertFalse(self.store.release_scheduled(due - 1))
        with self.assertRaises(ValueError):
            self.store.delete_group(group_id)
        self.store.change_schedule("move", due + 30)
        self.store.change_schedule("cancel")
        self.assertFalse(self.store.release_scheduled(due))
        self.assertTrue(self.store.release_scheduled(due + 30))
        self.assertFalse(self.store.release_scheduled(due + 30))
        self.assertEqual(self.store.next_task()["batch_id"], "move")
        self.assertEqual({task["batch_id"]: task["status"] for task in self.store.state()["tasks"]},
                         {"move": "queued", "cancel": "canceled"})
        with self.assertRaisesRegex(ValueError, "执行流程"):
            self.store.change_schedule("move")

    def test_overdue_schedule_is_marked_missed(self):
        due = int(time()) + 120
        self.store.enqueue("missed", self.group["id"], [self.target["id"]], "视频", "", "无需添加自主声明",
                           "demo.mp4", "demo.mp4", scheduled_at=due)
        self.assertTrue(self.store.release_scheduled(due + SCHEDULE_GRACE_SECONDS + 1))
        self.assertIsNone(self.store.next_task())
        self.assertEqual(self.store.state()["tasks"][0]["status"], "missed")
        self.store.change_schedule("missed", due + 600)
        self.assertEqual(self.store.state()["tasks"][0]["status"], "scheduled")


class CatalogTest(unittest.TestCase):
    def test_provider_entries_resolve_to_guarded_publisher_functions(self):
        self.assertEqual(len(PLATFORMS), 26)
        for name, spec in PLATFORMS.items():
            with self.subTest(platform=name):
                provider = import_module(f"publishers.{name}")
                if name == "company_website_v2":
                    self.assertTrue(callable(provider._create_article))
                elif name == "xiaohongshu":
                    for method in (provider.publish_video, provider.publish_image):
                        self.assertIn("before_submit", signature(method).parameters)
                else:
                    self.assertIn("before_submit", signature(provider.publish).parameters)
                self.assertTrue(spec.kinds)

    def test_publish_options_require_explicit_community_and_youtube_choices(self):
        self.assertEqual(normalize_options({"reddit"}, {"reddit_target": "r/example"})["reddit_target"], "/r/example")
        with self.assertRaises(ValueError):
            normalize_options({"reddit"}, {"reddit_target": "https://invalid.example/r/example"})
        with self.assertRaises(ValueError):
            normalize_options({"youtube"}, {"youtube_visibility": "PRIVATE"})
        self.assertFalse(normalize_options({"youtube"}, {"youtube_visibility": "PRIVATE", "youtube_kids": False})["youtube_kids"])


class ReceiptTest(unittest.TestCase):
    def test_only_success_with_a_work_id_counts(self):
        self.assertTrue(submission_response("douyin", "POST", "https://creator.douyin.com/web/api/media/aweme/create_v2/"))
        self.assertFalse(submission_response("douyin", "POST", "https://creator.douyin.com/web/api/media/aweme/create_v2/other"))
        self.assertFalse(submission_response("xiaohongshu", "GET", "https://edith.xiaohongshu.com/web_api/sns/v2/note"))
        self.assertEqual(receipt_from_json("douyin", {"status_code": 0, "aweme_id": "1234"}), "1234")
        self.assertIsNone(receipt_from_json("douyin", {"status_code": 0}))
        self.assertIsNone(receipt_from_json("xiaohongshu", {"success": True, "code": 19, "data": {"note_id": "1234"}}))
        self.assertEqual(receipt_from_json("xiaohongshu", {"success": True, "code": 0, "data": {"note_id": "1234"}}), "1234")
        captured_shape = {"success": True, "data": {"id": "0123456789ab0123456789ab", "score": 0}}
        self.assertEqual(receipt_from_json("xiaohongshu", captured_shape), "0123456789ab0123456789ab")
        self.assertIsNone(receipt_from_json("xiaohongshu", {**captured_shape, "success": False}))


class SessionBackupTest(unittest.TestCase):
    def test_encrypted_backup_cannot_be_opened_as_a_different_binding(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder)
            fixture = [{"name": "demo", "value": "test-secret"}]
            session_backup.save(profile, "account-a", fixture)
            self.assertNotIn(b"test-secret", (profile / "session.dat").read_bytes())
            self.assertEqual(session_backup.load(profile, "account-a"), fixture)
            with self.assertRaises(OSError):
                session_backup.load(profile, "account-b")

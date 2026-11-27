import asyncio
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))

from comment_cache import CACHE_NAME, CommentCache
from comment_workspace import CommentWorkspace
from store import Store
from xhs_comments import XiaohongshuComments


class CommentCacheTest(unittest.IsolatedAsyncioTestCase):
    async def test_deletion_check_distinguishes_missing_notes_from_temporary_errors(self):
        owner = "a" * 24
        statuses = {
            "b" * 24: iter((410,)),
            "c" * 24: iter((404, 404)),
            "d" * 24: iter((404, 200)),
            "e" * 24: iter((503,)),
            "f" * 24: iter((302,)),
        }
        notes = [{"id": ident, "href": f"https://www.xiaohongshu.com/user/profile/{owner}/{ident}?xsec_token=demo"}
                 for ident in statuses]
        notes.append({"id": "1" * 24, "href": "https://example.com/"})
        disposed = []

        async def evaluate(_):
            return "Fixture UA"

        async def get(address, **options):
            self.assertEqual(options["max_redirects"], 0)
            ident = address.split("/")[-1].partition("?")[0]
            status = next(statuses[ident])

            async def dispose():
                disposed.append(status)

            return SimpleNamespace(status=status, url=address, dispose=dispose)

        page = SimpleNamespace(evaluate=evaluate, request=SimpleNamespace(get=get))
        found = await XiaohongshuComments(None).verify_deleted_notes(page, owner, notes)
        self.assertEqual(found, {"b" * 24, "c" * 24})
        self.assertCountEqual(disposed, [410, 404, 404, 404, 200, 503, 302])

    async def test_background_scan_releases_the_original_account_when_foreground_work_arrives(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Store(root / "publisher.sqlite3")
            locks = {}
            service = CommentWorkspace(store, SimpleNamespace(contexts={}),
                                       lambda key: locks.setdefault(key, asyncio.Lock()), root, lambda _: None)
            binding = next(item for item in store.state()["bindings"] if item["platform"] == "xiaohongshu")
            store.bind(binding["id"], "测试账号", "test-session", account_proof="test-user")
            opened = asyncio.Event()
            released = asyncio.Event()

            @asynccontextmanager
            async def open_page(*_):
                opened.set()
                try:
                    yield None, None
                finally:
                    released.set()

            async def load_received(*_):
                async with open_page():
                    await asyncio.Event().wait()

            service.platform = SimpleNamespace(load_received=load_received)
            try:
                changing = asyncio.create_task(service.sync(binding["group_id"], binding["id"], "inbox", background=True))
                await asyncio.wait_for(opened.wait(), 1)
                await asyncio.wait_for(service.yield_to_foreground(binding["id"]), 1)
                await asyncio.wait_for(changing, 1)
                self.assertTrue(released.is_set())
                self.assertFalse(locks[binding["id"]].locked())
                self.assertEqual(service.jobs, {})
            finally:
                await service.shutdown()
                store.db.close()

    def test_cache_directory_cannot_overwrite_another_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = CommentCache(root / "source", "workspace-one")
            target = CommentCache(root / "target", "workspace-two")
            try:
                source.save_notes("account-one", [])
                target.save_notes("account-two", [])
                with self.assertRaisesRegex(ValueError, "另一份 Relayfold 工作区"):
                    source.change_directory(root / "target")
                self.assertIsNotNone(target.account("account-two"))
                self.assertFalse(target.account("account-one"))
                self.assertTrue((source.directory / CACHE_NAME).is_file())
            finally:
                target.db.close()
                source.db.close()

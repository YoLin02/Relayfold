import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))

from browser import Browser, PLATFORMS
from main import main


class FixtureBrowser(Browser):
    """A local page hosted by Playwright routing, with real Chrome profiles."""

    def __init__(self, profiles):
        super().__init__(profiles, headless=True)
        self.deliveries = profiles.parent / "fixture-deliveries.jsonl"

    async def launch(self, binding, *, douyin_video=False):
        context, page = await super().launch(binding, douyin_video=douyin_video)

        async def intercept(route):
            await route.fulfill(status=200, content_type="text/html", body="<title>Local creator fixture</title><main>Studio</main>")

        await context.route("**/*", intercept)
        if not binding["session_proof"]:
            # Simulate first scan with a session-only cookie. The real restore path is used afterwards.
            config = PLATFORMS[binding["platform"]]
            await context.add_cookies([{"name": config.auth[0], "value": binding["id"],
                                        "url": config.home}])
        return context, page

    async def publish(self, page, binding, task, before_submit, *, record=None, **_):
        await asyncio.sleep(1.1)
        await before_submit()
        if record and binding["platform"] == "douyin":
            record("隔离验收：已观测到模拟提交。")
        await asyncio.sleep(1.1)
        config = PLATFORMS[binding["platform"]]
        cookies = {cookie["name"]: cookie["value"] for cookie in await page.context.cookies([config.home])}
        target = cookies[config.auth[0]]
        with self.deliveries.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"group": task["group_id"], "expected": task["binding_id"], "actual": target,
                                     "kind": task["kind"], "files": len(task["media_files"]),
                                     "paths": task["media_files"], "title": task["title"], "body": task["description"],
                                     "tags": task["tags"], "cover": task["cover"]}) + "\n")
        return "fixture-" + target


if __name__ == "__main__":
    main(FixtureBrowser)

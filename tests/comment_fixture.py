import html
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))

from browser import Browser, xhs_user_proof
from main import main
from store import Store
from xhs_comments import API, COMMENTS, ORIGIN, REPLY

NOTE = "e" * 24
COMMENT = "f" * 24


def profile(binding):
    suffix = binding["label"][-1]
    return {"success": True, "code": 0, "data": {"guest": False, "user_id": ("a" if suffix == "A" else "b") * 24}}


class FixtureBrowser(Browser):
    async def launch(self, binding, **options):
        context, page = await super().launch(binding, **options)
        owner = profile(binding)["data"]["user_id"]
        label = binding["label"]
        note_path = f"/user/profile/{owner}/{NOTE}"
        extra_rows = 30 if os.environ.get("ZT_COMMENT_SCROLL_FIXTURE") == "1" else 0

        async def respond(route):
            req = route.request
            url = urlsplit(req.url)
            headers = {"access-control-allow-origin": ORIGIN, "access-control-allow-methods": "GET, POST, OPTIONS",
                       "access-control-allow-headers": "content-type"}
            if url.hostname == API:
                if req.method == "OPTIONS":
                    return await route.fulfill(status=204, headers=headers)
                if url.path == "/api/sns/web/v2/user/me":
                    return await route.fulfill(json=profile(binding), headers=headers)
                if url.path == COMMENTS:
                    item = {"id": COMMENT, "content": f"{label}的原评论", "user_info": {"nickname": "演示读者"}}
                    extra = [
                        {"id": f"{index:024x}", "content": f"用于滚动验收的评论 {index}", "user_info": {"nickname": "演示读者"}}
                        for index in range(1, extra_rows + 1)
                    ]
                    return await route.fulfill(json={"code": 0, "data": {"comments": [item, *extra]}}, headers=headers)
                if url.path == REPLY and req.method == "POST":
                    with (self.profiles.parent / "comment-deliveries.jsonl").open("a", encoding="utf-8") as log:
                        log.write(json.dumps({"binding": binding["id"], "request": req.post_data_json}) + "\n")
                    return await route.fulfill(json={"code": 0, "success": True}, headers=headers)
            if url.path == "/explore":
                content = f'<script>fetch("https://{API}/api/sns/web/v2/user/me")</script>'
            elif url.path == f"/user/profile/{owner}":
                content = f'''<section class="note-item"><a href="/explore/{NOTE}"></a>
                    <a class="title" href="{note_path}?xsec_token=fixture">{html.escape(label)}的站内笔记</a></section>'''
                for index in range(1, extra_rows + 1):
                    note = f"{index:024x}"
                    content += f'''<section class="note-item"><a href="/explore/{note}"></a>
                        <a class="title" href="/user/profile/{owner}/{note}?xsec_token=fixture">演示笔记 {index}</a></section>'''
            elif url.path == note_path:
                content = f'''<div id="comment-{COMMENT}"><button class="reply">回复</button></div>
                    <div class="input-box"><div class="content-edit"><p class="content-input" contenteditable="true"></p></div></div>
                    <div class="bottom"><button class="submit">发送</button></div>
                    <script>
                    fetch("https://{API}{COMMENTS}?note_id={NOTE}");
                    const editor = document.querySelector('.content-input');
                    document.querySelector('.reply').onclick = () => editor.focus();
                    document.querySelector('.submit').onclick = () => fetch("https://{API}{REPLY}", {{
                      method:"POST", headers:{{"Content-Type":"application/json"}},
                      body: JSON.stringify({{note_id:"{NOTE}", target_comment_id:"{COMMENT}", content:editor.textContent}})
                    }});
                    </script>'''
            else:
                return await route.abort()
            await route.fulfill(content_type="text/html; charset=utf-8", body=content)

        await context.route("**/*", respond)
        return context, page


def seed(root):
    root.mkdir(parents=True, exist_ok=True)
    store = Store(root / "publisher.sqlite3")
    for binding in store.db.execute("""
        SELECT b.id, g.name FROM bindings b JOIN groups g ON b.group_id=g.id WHERE b.platform='xiaohongshu'
    """).fetchall():
        label = f"演示账号 {binding['name'][-1]}"
        store.bind(binding["id"], label, "fixture-" + binding["id"], account_proof=xhs_user_proof(profile({"label": label}), True))
    store.db.close()


if __name__ == "__main__":
    seed(Path(sys.argv[sys.argv.index("--data-dir") + 1]))
    main(FixtureBrowser)

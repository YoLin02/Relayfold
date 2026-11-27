import asyncio
import base64
import hashlib
import html
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))

from browser import Browser, xhs_user_proof
import comment_workspace
from main import main
from store import Store
from xhs_comments import API, COMMENTS, MENTIONS, ORIGIN, REPLY, SUB_COMMENTS, XiaohongshuComments, note_document_deleted

NOTE = "e" * 24
COMMENT = "f" * 24
SECOND_NOTE = "a" * 24
FIRST_CHILD, SECOND_CHILD, THIRD_CHILD = ("1" * 24, "2" * 24, "3" * 24)
LATER_COMMENT, FOLLOW_UP = "b" * 24, "c" * 24
EXTERNAL_NOTE, EXTERNAL_COMMENT = "4" * 24, "5" * 24
FIXTURE_COVER = "https://sns-webpic.xhscdn.com/relayfold-fixture.png"
PIXEL = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jY1sAAAAASUVORK5CYII=")


def profile(binding):
    owner = hashlib.sha256(binding["id"].encode()).hexdigest()[:24]
    return {"success": True, "code": 0, "data": {"guest": False, "user_id": owner}}


class FixtureBrowser(Browser):
    async def launch(self, binding, **options):
        private_message_test = os.environ.get("ZT_PRIVATE_MESSAGE_FIXTURE") == "1"
        if private_message_test:
            options.setdefault("headless", True)
        context, page = await super().launch(binding, **options)
        owner = profile(binding)["data"]["user_id"]
        label = binding["label"]
        if label == "同名账号":
            label = f"{label} {binding['slot']}"
        multi = os.environ.get("ZT_COMMENT_MULTI_FIXTURE") == "1"
        cache_test = os.environ.get("ZT_COMMENT_CACHE_FIXTURE") == "1"
        thread_test = os.environ.get("ZT_COMMENT_THREAD_FIXTURE") == "1"
        received_test = os.environ.get("ZT_RECEIVED_COMMENT_FIXTURE") == "1"
        external_test = os.environ.get("ZT_RECEIVED_EXTERNAL_FIXTURE") == "1"
        if private_message_test:
            await context.add_cookies([{"name": "web_session", "value": "fixture-" + binding["id"],
                                        "domain": ".xiaohongshu.com", "path": "/", "secure": True}])
        note_path = f"/user/profile/{owner}/{NOTE}"
        extra_rows = 30 if os.environ.get("ZT_COMMENT_SCROLL_FIXTURE") == "1" else 0
        thread_children = [
            {"id": FIRST_CHILD, "content": "站内已有作者回复", "user_info": {"user_id": owner, "nickname": "演示作者"}},
            {"id": SECOND_CHILD, "content": "第一批额外子评论", "user_info": {"nickname": "演示读者甲"}},
            {"id": THIRD_CHILD, "content": "第二批额外子评论", "user_info": {"nickname": "演示读者乙"},
             "target_comment": {"user_info": {"nickname": "演示读者甲"}}},
        ]
        follow_up = {"id": FOLLOW_UP, "content": "读者发来的追回复", "user_info": {"nickname": "追回复读者"},
                     "target_comment": {"id": FIRST_CHILD, "content": "站内已有作者回复", "user_info": {"userid": owner}}}

        def incoming(comment, *, follow=False, external=False):
            return {
                "id": "message-" + comment["id"], "type": "comment/comment" if follow else "comment/item",
                "time": 1760000000000, "user_info": comment["user_info"], "comment_info": comment,
                "item_info": {
                    "id": EXTERNAL_NOTE if external else NOTE, "type": "note_info",
                    "content": "别人的外部原帖" if external else f"{label}的站内笔记",
                    "xsec_token": "fixture", "user_info": {"userid": "6" * 24 if external else owner},
                },
            }

        def messages():
            rows = [incoming({"id": COMMENT, "content": f"{label}的原评论", "user_info": {"nickname": "演示读者"}})]
            if multi:
                rows.append(incoming({"id": "d" * 24, "content": f"{label}已在站内回复的评论",
                                      "user_info": {"nickname": "演示读者"}}))
            if cache_test and label.endswith(" A") and (self.profiles.parent / "new-comment").exists():
                rows.insert(0, incoming({"id": LATER_COMMENT, "content": "后台收到的新评论", "user_info": {"nickname": "演示读者"}}))
            if received_test and label.endswith(" A") and (self.profiles.parent / "received-follow-up").exists():
                rows.insert(0, incoming(follow_up, follow=True))
            if external_test and label.endswith(" A"):
                external_reply = {**follow_up, "id": EXTERNAL_COMMENT, "content": "别人在自己原帖里回复了我"}
                rows.insert(0, incoming(external_reply, follow=True, external=True))
            return rows

        async def respond(route):
            req = route.request
            url = urlsplit(req.url)
            headers = {"access-control-allow-origin": ORIGIN, "access-control-allow-methods": "GET, POST, OPTIONS",
                       "access-control-allow-headers": "content-type", "access-control-allow-credentials": "true"}
            if url.hostname == API:
                if req.method == "OPTIONS":
                    return await route.fulfill(status=204, headers=headers)
                if url.path == "/api/sns/web/v2/user/me":
                    account = profile(binding)
                    if private_message_test and (self.profiles.parent / "different-private-account").exists():
                        account["data"]["user_id"] = "0" * 24
                    return await route.fulfill(json=account, headers=headers)
                if url.path == MENTIONS:
                    return await route.fulfill(json={"code": 0, "data": {"message_list": messages(), "has_more": False}}, headers=headers)
                if url.path == COMMENTS:
                    if cache_test and url.query == f"note_id={SECOND_NOTE}":
                        for _ in range(120):
                            if (self.profiles.parent / "finish-slow-note").exists():
                                break
                            await asyncio.sleep(0.05)
                        return await route.fulfill(json={"code": 0, "data": {"comments": []}}, headers=headers)
                    item = {"id": COMMENT, "content": f"{label}的原评论", "user_info": {"nickname": "演示读者"}}
                    if thread_test:
                        item.update(sub_comment_count="3", sub_comment_has_more=True, sub_comment_cursor="first",
                                    sub_comments=thread_children[:1])
                    if received_test:
                        if ((self.profiles.parent / "received-follow-up").exists()
                                and not (self.profiles.parent / "hold-follow-up-location").exists()):
                            item.update(sub_comment_count="2", sub_comment_has_more=False, sub_comments=[thread_children[0], follow_up])
                        else:
                            item.update(sub_comment_count="1", sub_comment_has_more=False, sub_comments=thread_children[:1])
                    extra = [
                        {"id": f"{index:024x}", "content": f"用于滚动验收的评论 {index}", "user_info": {"nickname": "演示读者"}}
                        for index in range(1, extra_rows + 1)
                    ]
                    if multi:
                        extra.append({"id": "d" * 24, "content": f"{label}已在站内回复的评论",
                                      "user_info": {"nickname": "演示读者"},
                                      "sub_comments": [{"user_info": {"user_id": owner}}]})
                    if cache_test and label.endswith(" A") and (self.profiles.parent / "new-comment").exists():
                        extra.append({"id": "b" * 24, "content": "后台收到的新评论", "user_info": {"nickname": "演示读者"}})
                    if received_test and "cursor=next" in url.query:
                        after = {"id": LATER_COMMENT, "content": "下一页一级评论", "ip_location": "广东",
                                 "user_info": {"nickname": "另一位读者"}, "create_time": 1735689600000}
                        if (self.profiles.parent / "hold-follow-up-location").exists():
                            for _ in range(100):
                                if (self.profiles.parent / "release-follow-up-location").exists():
                                    break
                                await asyncio.sleep(0.05)
                            after.update(sub_comment_count="1", sub_comment_has_more=False, sub_comments=[follow_up])
                        return await route.fulfill(json={"code": 0, "data": {"comments": [after], "has_more": False}}, headers=headers)
                    return await route.fulfill(json={"code": 0, "data": {"comments": [item, *extra],
                                               "has_more": received_test, "cursor": "next" if received_test else ""}}, headers=headers)
                if url.path == SUB_COMMENTS and thread_test:
                    first = "cursor=first" in url.query
                    return await route.fulfill(json={"code": 0, "data": {
                        "comments": thread_children[1:2] if first else thread_children[2:],
                        "cursor": "second" if first else "", "has_more": first,
                    }}, headers=headers)
                if url.path == REPLY and req.method == "POST":
                    with (self.profiles.parent / "comment-deliveries.jsonl").open("a", encoding="utf-8") as log:
                        log.write(json.dumps({"binding": binding["id"], "request": req.post_data_json}) + "\n")
                    return await route.fulfill(json={"code": 0, "success": True}, headers=headers)
            if url.path == "/explore":
                content = f'<script>fetch("https://{API}/api/sns/web/v2/user/me")</script>'
                if private_message_test:
                    content = f'<script>fetch("https://{API}/api/sns/web/v2/user/me", {{credentials:"include"}})</script>'
                    if not (self.profiles.parent / "no-private-message-entry").exists():
                        content += '<a href="https://www.xiaohongshu.com/chat">消息</a>'
            elif private_message_test and url.path == "/chat":
                with (self.profiles.parent / "private-message-opens.jsonl").open("a", encoding="utf-8") as log:
                    log.write(json.dumps({"binding_id": binding["id"], "group_id": binding["group_id"]}) + "\n")
                escaped_label = html.escape(label)
                load_direct = json.dumps(not (self.profiles.parent / "no-personal-chat-data").exists())
                content = f"""<div class="xhs-im-conv-list__scroll">
                  <div class="xhs-im-conv-item" data-conv-id="group-1" data-conv-kind="group">
                    <span class="xhs-im-conv-item__name">演示群聊</span>
                  </div>
                </div><div class="xhs-im-view__main"></div>
                <template id="direct-conversations">
                  <div class="xhs-im-conv-item" data-conv-id="conversation-1" data-conv-kind="c2c">
                    <span class="xhs-im-conv-item__name">同名联系人</span>
                    <span class="xhs-im-conv-item__summary-text">{escaped_label}的一号预览</span>
                    <span class="xhs-im-conv-item__time">昨天</span>
                    <span class="xhs-im-conv-item__bottom-right"><span class="unread-badge">2</span></span>
                  </div>
                  <div class="xhs-im-conv-item" data-conv-id="conversation-2" data-conv-kind="c2c">
                    <span class="xhs-im-conv-item__name">同名联系人</span>
                    <span class="xhs-im-conv-item__summary-text">{escaped_label}的二号预览</span>
                  </div>
                </template>
                <script>
                let list;
                const message = (id, side, text) => '<div data-message-id="' + id + '" style="min-height:85px"><div class="chat-item__content--'
                    + side + '"><span class="xhs-im-bubble__text">' + text + '</span></div></div>';
                if ({load_direct}) setTimeout(() => {{
                  document.querySelector('.xhs-im-conv-list__scroll').prepend(document.querySelector('#direct-conversations').content);
                  document.querySelectorAll('[data-conv-kind="c2c"]').forEach((item,index) => {{
                    item.onclick = () => {{
                        document.querySelector('.xhs-im-conv-item--active')?.classList.remove('xhs-im-conv-item--active');
                        item.classList.add('xhs-im-conv-item--active');
                        item.querySelector('.unread-badge')?.remove();
                        document.querySelector('.xhs-im-view__main').innerHTML = '<div class="xhs-im-chat-window">'
                            + '<div class="xhs-im-msg-list" style="height:100px;overflow-y:auto">'
                            + '<div class="xhs-im-msg-list__time-divider">昨天</div>'
                            + message('first','left','{escaped_label}的会话 ' + (index + 1))
                            + message('last','right','原账号发出的这条消息') + '</div></div>';
                        list = document.querySelector('.xhs-im-msg-list');
                        list.scrollTop = list.scrollHeight;
                        list.addEventListener('scroll', () => {{
                            if (list.scrollTop || list.querySelector('[data-message-id="older"]')) return;
                            list.insertAdjacentHTML('afterbegin', message('older','left','这是一条更早的聊天消息'));
                        }});
                    }};
                  }});
                }}, 800);
                </script>"""
            elif url.path == "/notification":
                content = f'''<div class="tabs-content-container"></div><script>
                    const host = document.querySelector('.tabs-content-container');
                    fetch("https://{API}{MENTIONS}?num=20&cursor=").then(r=>r.json()).then(({{data}})=>{{
                      for (const event of data.message_list) {{
                        const entry = document.createElement('div');
                        entry.className = 'container';
                        const username = document.createElement('div');
                        username.textContent = event.user_info.nickname;
                        entry.append(username);
                        const content = document.createElement('div');
                        content.className = 'interaction-content';
                        content.textContent = event.comment_info.content;
                        content.onclick = () => location.href = "{note_path}?xsec_token=fixture";
                        entry.append(content);
                        const actions = document.createElement('div');
                        actions.className = 'actions';
                        actions.innerHTML = '<button type="button">回复</button>';
                        actions.firstChild.onclick = () => {{
                          const textbox = document.createElement('textarea');
                          const submit = document.createElement('button');
                          submit.className = 'submit';
                          submit.textContent = '发送';
                          submit.onclick = () => fetch("https://{API}{REPLY}", {{
                            method:"POST", headers:{{"Content-Type":"application/json"}},
                            body:JSON.stringify({{note_id:event.item_info.id,target_comment_id:event.comment_info.id,content:textbox.value}})
                          }});
                          actions.append(textbox,submit);
                          textbox.focus();
                        }};
                        entry.append(actions);
                        host.append(entry);
                      }}
                    }});
                </script>'''
            elif url.path == f"/user/profile/{owner}":
                content = f'''<section class="note-item"><a href="/explore/{NOTE}"></a>
                    <a class="title" href="{note_path}?xsec_token=fixture">{html.escape(label)}的站内笔记</a></section>'''
                if cache_test:
                    content = content.replace('<a class="title"', f'<a class="cover"><img data-src="{FIXTURE_COVER}"></a><a class="title"', 1)
                    content += f'''<section class="note-item"><a href="/explore/{SECOND_NOTE}"></a>
                        <a class="title" href="/user/profile/{owner}/{SECOND_NOTE}?xsec_token=fixture">慢笔记</a></section>'''
                for index in range(1, extra_rows + 1):
                    note = f"{index:024x}"
                    content += f'''<section class="note-item"><a href="/explore/{note}"></a>
                        <a class="title" href="/user/profile/{owner}/{note}?xsec_token=fixture">演示笔记 {index}</a></section>'''
            elif url.path in {note_path, f"/explore/{NOTE}"}:
                if cache_test and label == "演示账号 A" and (self.profiles.parent / "delete-note").exists():
                    return await route.fulfill(status=410, body="笔记已删除", content_type="text/plain; charset=utf-8")
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
                if thread_test:
                    content = f'''<div class="parent-comment">
                      <div id="comment-{COMMENT}"><button class="reply">回复</button></div>
                      <div class="reply-container">
                        <div id="comment-{FIRST_CHILD}"><button class="reply">回复</button></div>
                        <button class="show-more">展开 2 条回复</button>
                      </div>
                    </div>
                    <div class="input-box"><div class="content-edit"><p class="content-input" contenteditable="true"></p></div></div>
                    <div class="bottom"><button class="submit">发送</button></div>
                    <script>
                    fetch("https://{API}{COMMENTS}?note_id={NOTE}");
                    let target = null;
                    let cursor = "first";
                    const editor = document.querySelector('.content-input');
                    const more = document.querySelector('.show-more');
                    document.querySelector('.parent-comment').addEventListener('click', event => {{
                      if (!event.target.matches('.reply')) return;
                      target = event.target.parentElement.id.slice('comment-'.length);
                      editor.focus();
                    }});
                    more.onclick = async () => {{
                      const url = "https://{API}{SUB_COMMENTS}?note_id={NOTE}&root_comment_id={COMMENT}&cursor=" + cursor;
                      const {{data}} = await (await fetch(url)).json();
                      for (const row of data.comments) {{
                        const node = document.createElement("div");
                        node.id = "comment-" + row.id;
                        node.innerHTML = '<button class="reply">回复</button>';
                        more.before(node);
                      }}
                      cursor = data.cursor;
                      if (!data.has_more) more.remove();
                      else more.textContent = "展开 1 条回复";
                    }};
                    document.querySelector('.submit').onclick = () => fetch("https://{API}{REPLY}", {{
                      method:"POST", headers:{{"Content-Type":"application/json"}},
                      body:JSON.stringify({{note_id:"{NOTE}",target_comment_id:target,content:editor.textContent}})
                    }});
                    </script>'''
                if received_test:
                    content = content.replace(f'<div id="comment-{COMMENT}"><button class="reply">回复</button></div>',
                                               f'<div class="comments-container"><div class="parent-comment"><div id="comment-{COMMENT}"><button class="reply">回复</button></div></div></div>')
                    content += f'''<script>
                    let loaded = false;
                    document.querySelector('.comments-container').addEventListener('wheel', () => {{
                      if (loaded) return;
                      loaded = true;
                      fetch("https://{API}{COMMENTS}?note_id={NOTE}&cursor=next");
                    }});
                    </script>'''
            elif cache_test and url.path == f"/user/profile/{owner}/{SECOND_NOTE}":
                content = f'<script>fetch("https://{API}{COMMENTS}?note_id={SECOND_NOTE}")</script>'
            else:
                return await route.abort()
            await route.fulfill(content_type="text/html; charset=utf-8", body=content)

        await context.route("**/*", respond)
        return context, page


async def verify_fixture_notes(self, page, owner, notes):
    # Use routed pages here so fixture checks never contact the real platform.
    checker = await page.context.new_page()
    try:
        deleted = set()
        for note in notes:
            response = await checker.goto(note["href"], wait_until="domcontentloaded")
            if note_document_deleted(response, note["id"], owner):
                deleted.add(note["id"])
        return deleted
    finally:
        await checker.close()


def seed(root):
    root.mkdir(parents=True, exist_ok=True)
    store = Store(root / "publisher.sqlite3")
    if os.environ.get("ZT_COMMENT_MULTI_FIXTURE") == "1":
        if not store.db.execute("SELECT 1 FROM groups WHERE name='演示自定义组'").fetchone():
            group = store.create_group("演示自定义组", "custom")
            store.add_accounts(group, "xiaohongshu", 2)
    for binding in store.db.execute("""
        SELECT b.id, g.name, g.mode FROM bindings b JOIN groups g ON b.group_id=g.id WHERE b.platform='xiaohongshu'
    """).fetchall():
        label = "同名账号" if binding["mode"] == "custom" else f"演示账号 {binding['name'][-1]}"
        store.bind(binding["id"], label, "fixture-" + binding["id"], account_proof=xhs_user_proof(profile(binding), True))
    if os.environ.get("ZT_DOUYIN_MESSAGE_FIXTURE") == "1":
        for binding in store.db.execute("""
            SELECT b.id, g.name FROM bindings b JOIN groups g ON g.id=b.group_id WHERE b.platform='douyin'
        """).fetchall():
            store.bind(binding["id"], f"演示抖音 {binding['name'][-1]}", "fixture-" + binding["id"])
    store.db.close()


if __name__ == "__main__":
    XiaohongshuComments.verify_deleted_notes = verify_fixture_notes
    if os.environ.get("ZT_COMMENT_CACHE_FIXTURE") == "1":
        comment_workspace.POLL_INTERVAL = 1
        comment_workspace.fetch_cover = lambda url: ("image/png", PIXEL) if url == FIXTURE_COVER else None
    seed(Path(sys.argv[sys.argv.index("--data-dir") + 1]))
    main(FixtureBrowser)

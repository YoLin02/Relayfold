"""
百家号发布器 — 浏览器自动化（Playwright）

流程：直接打开编辑页 → 填标题 → 填正文 → 选择正文图片作封面 → 勾选协议 → 发布
百家号使用百度统一通行证（passport.baidu.com）登录。
编辑器：Lexical 富文本（title）+ contenteditable body（正文）。
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from playwright.async_api import Page

logger = logging.getLogger("video_publisher")

BAIJIAHAO_EDIT_URL = "https://baijiahao.baidu.com/builder/rc/edit?type=news&is_from_cms=1"


def _markdown_to_html(text: str) -> str:
    """将 Markdown 转为简单 HTML，适配 contenteditable 编辑器"""
    # 先处理 ## 标题
    text = re.sub(r'^##\s+(.+)$', r'<h2>\1</h2>', text, flags=re.MULTILINE)
    # 处理 **加粗**
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # 处理 ![alt](url) 图片
    text = re.sub(r'!\[([^\]]*)\]\(([^\)]+)\)', r'<br><img src="\2" alt="\1"><br>', text)
    # 处理 [text](url) 链接
    text = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'<a href="\2">\1</a>', text)
    # 按空行分段，每段包 <p>
    paragraphs = text.split('\n\n')
    html_parts = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if p.startswith('<h2>'):
            html_parts.append(p)
        elif p.startswith('<br>'):
            html_parts.append(p)
        else:
            # 段内换行 → <br>
            inner = p.replace('\n', '<br>')
            html_parts.append(f'<p>{inner}</p>')
    return '\n'.join(html_parts)


async def _focus_and_select_content(page: Page, editor_type: str) -> bool:
    """模拟人工：把光标放进正文编辑区 → Ctrl+A 全选，让编辑器框架识别已填充的正文。

    纯 JS `execCommand('insertHTML')` 只是程序化写入，不触发编辑器（Lexical 等）对
    "用户输入"的内部登记，AI 封面（基于全文智能生成）因此读不到正文。
    这里用真实点击聚焦正文编辑区 + 键盘 Ctrl+A，生成 focus/selectionchange 事件，
    让框架刷新内部正文模型。覆盖 body / 内嵌 iframe / 通用 contenteditable 三种形态。
    """
    try:
        if editor_type == 'iframe-body':
            await page.frame_locator('iframe').first.locator('body[contenteditable="true"]').first.click(timeout=5000)
        elif editor_type == 'body-contenteditable':
            await page.locator('body[contenteditable="true"]').first.click(timeout=5000)
        elif editor_type and editor_type.startswith('generic-'):
            # 标题编辑区在 data-testid=news-title-input 内，跳过它聚焦正文区
            await page.evaluate("""() => {
                const editables = document.querySelectorAll('[contenteditable="true"]');
                for (const el of editables) {
                    if (!el.closest('[data-testid="news-title-input"]')) {
                        el.focus();
                        break;
                    }
                }
            }""")
        else:
            return False
        await asyncio.sleep(0.3)
        await page.keyboard.press('Control+a')
        await asyncio.sleep(0.3)
        logger.info("Baijiahao: focused content editor + Ctrl+A (simulate human)")
        return True
    except Exception as e:
        logger.warning(f"Baijiahao: focus + select-all failed: {e}")
        return False


async def _paste_html(page: Page, html: str, editor_type: str) -> bool:
    """把正文以「真粘贴」的方式灌进编辑器，返回是否成功。

    为什么不能像原来那样用 execCommand('insertHTML')：那只是程序化写 DOM，**绕过了编辑器的
    paste 管线**。百家号的正文图片不是「DOM 里有个 <img> 就算」—— 编辑器是在 paste 时读到
    <img src="外链">，**重新上传到百家号自己的存储**，传完才登记为「正文图片」。程序化写入
    从不触发这一步，所以封面弹窗的「正文图片」页签里一张都选不到。

    实测对照：手动从文章库预览框复制正文粘贴进去就能选到图，自动化不行 —— 差别只在有没有
    走 paste 事件，不在 HTML 内容本身。

    写真是剪贴板的写法照抄 wangyi.py 里已经在用的那套（授权 → clipboard.write → Ctrl+V）：
    真按 Ctrl+V 才会产生受信任的 paste 事件，合成的 ClipboardEvent 并不可靠。
    代价是**会覆盖用户桌面上当前剪贴板里的内容** —— 网易号现在就是这个行为。
    """
    try:
        # navigator.clipboard.write 要求 document 有焦点
        await page.bring_to_front()
        try:
            await page.context.grant_permissions(
                ["clipboard-read", "clipboard-write"],
                origin="https://baijiahao.baidu.com",
            )
        except Exception as e:
            logger.warning(f"Baijiahao: 授予剪贴板权限失败: {e}")

        # text/html 是主力；text/plain 作为「浏览器式副本」的兜底层一起带上（真复制总是两层）
        await page.evaluate("""async ({html}) => {
            const mk = (s, t) => new Blob([s], {type: t});
            const div = document.createElement('div');
            div.innerHTML = html;
            await navigator.clipboard.write([new ClipboardItem({
                'text/html': mk(html, 'text/html'),
                'text/plain': mk(div.innerText || div.textContent || '', 'text/plain'),
            })]);
        }""", {"html": html})
        await asyncio.sleep(0.3)

        # 聚焦正文编辑区（形态沿用 Step 2 已经算出来的 editor_type）
        focused = await page.evaluate("""(editorType) => {
            const hit = (el) => { if (!el) return false; el.focus(); return true; };
            if (editorType === 'body-contenteditable')
                return hit(document.querySelector('body[contenteditable="true"]'));
            if (editorType === 'iframe-body') {
                const iframes = document.querySelectorAll('iframe');
                for (const f of iframes) {
                    try {
                        const ib = f.contentDocument
                            && f.contentDocument.querySelector('body[contenteditable="true"]');
                        if (ib) return hit(ib);
                    } catch(e) {}
                }
                return false;
            }
            if (editorType && editorType.indexOf('generic-') === 0) {
                for (const el of document.querySelectorAll('[contenteditable="true"]')) {
                    if (!el.closest('[data-testid="news-title-input"]')) return hit(el);
                }
                return false;
            }
            return false;
        }""", editor_type)
        if not focused:
            logger.warning(f"Baijiahao: 真粘贴前没找到可聚焦的正文编辑区 (editor_type={editor_type})")
            return False
        await asyncio.sleep(0.3)

        # 清掉可能残留的内容再粘，避免重复
        await page.keyboard.press('Control+a')
        await asyncio.sleep(0.1)
        await page.keyboard.press('Backspace')
        await asyncio.sleep(0.3)
        await page.keyboard.press('Control+v')
        await asyncio.sleep(0.5)
        logger.info(f"Baijiahao: 已真粘贴正文（clipboard text/html + Ctrl+V），html 长度={len(html)}")
        return True
    except Exception as e:
        logger.warning(f"Baijiahao: 真粘贴失败: {e}")
        return False


async def _dump_visible_texts(page: Page, label: str):
    """输出当前可见主要元素文本（含 iframe 内），用于封面弹窗结构诊断"""
    try:
        texts = await page.evaluate("""() => {
            const out = [];
            const scan = (doc, tag) => {
                if (!doc || !doc.body) return;
                const els = doc.querySelectorAll('div,span,button,li,[role="tab"]');
                for (const el of els) {
                    if (el.offsetParent === null) continue;
                    const t = (el.textContent || '').trim();
                    if (!t || t.length > 30) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width < 30 || r.height < 20) continue;
                    out.push(tag + el.tagName.toLowerCase() + ': ' + t);
                }
            };
            scan(document, '');
            const iframes = document.querySelectorAll('iframe');
            for (let i = 0; i < iframes.length; i++) {
                try { scan(iframes[i].contentDocument, '[iframe' + i + '] '); } catch(e) {}
            }
            return out.slice(0, 30);
        }""")
        logger.info(f"Baijiahao: Visible texts [{label}]: {texts}")
    except Exception as e:
        logger.warning(f"Baijiahao: dump visible texts [{label}] failed: {e}")


async def _dump_editor_probe(page: Page, label: str):
    """标题编辑区没找到时的诊断：列出页面里所有 data-testid 与 contenteditable。

    2026-10-12 线上出现过「Title editor not found」当场判死、日志里什么线索都没有的情况，
    当时无法区分「选择器失效」与「页面还没渲染完」。这行输出就是区分这两者所需的全部信息
    （顺带能看出是否被软登录墙挡住：那种情况下列表会是空的）。定位方法见 CLAUDE.md 的
    「诊断是校准选择器的唯一手段」。
    """
    try:
        info = await page.evaluate("""() => {
            const tids = [];
            document.querySelectorAll('[data-testid]').forEach(e => {
                const v = e.getAttribute('data-testid');
                if (v && tids.indexOf(v) < 0) tids.push(v);
            });
            const eds = [];
            document.querySelectorAll('[contenteditable]').forEach(e => {
                const c = e.className;
                const p = e.closest('[data-testid]');
                eds.push(e.tagName.toLowerCase()
                    + ' ce=' + e.getAttribute('contenteditable')
                    + ' id=' + (e.id || '-')
                    + ' cls=' + (typeof c === 'string' ? c : '').slice(0, 60)
                    + ' inTestid=' + (p ? p.getAttribute('data-testid') : '-'));
            });
            let iframeCe = false;
            document.querySelectorAll('iframe').forEach(f => {
                try {
                    if (f.contentDocument && f.contentDocument.querySelector('[contenteditable]')) iframeCe = true;
                } catch (e) {}
            });
            return {doc_title: document.title, testids: tids, editables: eds, iframe_ce: iframeCe};
        }""")
        logger.info(
            f"Baijiahao: 编辑器诊断 [{label}] doc_title={info.get('doc_title')} "
            f"data-testid={info.get('testids')} iframe内contenteditable={info.get('iframe_ce')}"
        )
        for e in (info.get("editables") or [])[:10]:
            logger.info(f"Baijiahao: 编辑器诊断 [{label}] {e}")
    except Exception as e:
        logger.warning(f"Baijiahao: 编辑器诊断 [{label}] 失败: {e}")


async def publish(
    page: Page,
    account,
    media_paths: list[str],
    title: Optional[str],
    description: Optional[str],
    *,
    before_submit,
) -> bool:
    try:
        logger.info(f"Baijiahao: === START publish for {account.name} (id={account.id}) ===")
        logger.info(f"Baijiahao: Title={title[:50] if title else 'N/A'}, Desc length={len(description) if description else 0}")

        if not description:
            logger.error("Baijiahao: No article content provided")
            return False

        # Step 0: 直接导航到文章编辑页
        logger.info("Baijiahao: Step 0 - Navigating to edit page...")
        try:
            await page.goto(BAIJIAHAO_EDIT_URL, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            logger.error(f"Baijiahao: page.goto failed: {e}")
            return False

        await asyncio.sleep(4)

        current_url = page.url
        logger.info(f"Baijiahao: Current URL={current_url}")

        # 检查是否被重定向到登录页
        if "/login" in current_url or "passport" in current_url:
            logger.error("Baijiahao: Not logged in, redirected to login page")
            return False

        # ========== Step 1: 填入标题 ==========
        logger.info(f"Baijiahao: Step 1 - Filling title: {title[:50] if title else 'N/A'}...")
        title_filled = False
        clean_title = (title or "").replace("\n", "")

        title_sel = '[data-testid="news-title-input"] [contenteditable="true"]'
        for attempt in range(3):  # 最多重试 3 次
            try:
                if attempt == 0:
                    # 这个编辑页是 SPA：2026-10-12 实测 domcontentloaded(t≈0.6s) 之后，
                    # 标题编辑区 t≈3.3s 才进 DOM、t≈4.8s 才可见，而上面只 sleep(4) 就零等待地
                    # 查一次 count()——只剩 0.7s 余量。页面慢一档（冷缓存/网络抖动/机器慢）就必然
                    # 查空，然后下面 break 直接判死，线上表现为「Title editor not found →
                    # Title is required, aborting」，且不留任何诊断信息。
                    # 这里按「进 DOM」等足（count() 本来就不看可见性，而 click() 自己会等可见）。
                    try:
                        await page.wait_for_selector(title_sel, state="attached", timeout=30000)
                    except Exception as e:
                        logger.warning(f"Baijiahao: 等待标题编辑区超时（30s）: {type(e).__name__}")
                title_editor = page.locator(title_sel).first
                if await title_editor.count() == 0:
                    logger.warning("Baijiahao: Title editor not found")
                    await _dump_visible_texts(page, "title-editor")
                    await _dump_editor_probe(page, "title-editor")
                    break

                if attempt == 0:
                    # 方案1：键盘模拟输入（适配 Lexical 编辑器）
                    await title_editor.click()
                    await asyncio.sleep(0.5)
                    await page.keyboard.press('Control+a')
                    await asyncio.sleep(0.1)
                    await page.keyboard.press('Backspace')
                    await asyncio.sleep(0.2)
                    await page.keyboard.type(clean_title, delay=50)
                    await asyncio.sleep(0.5)
                else:
                    # 方案2：evaluate 设置 + 输入事件
                    await title_editor.click()
                    await asyncio.sleep(0.3)
                    await title_editor.evaluate("(el, t) => { el.innerHTML = ''; el.focus(); }", clean_title)
                    await asyncio.sleep(0.2)
                    await page.keyboard.type(clean_title, delay=20)
                    await asyncio.sleep(0.5)

                # 验证标题是否真的被填入
                actual = await title_editor.text_content()
                actual = (actual or "").strip()
                if actual and len(actual) > 0:
                    title_filled = True
                    logger.info(f"Baijiahao: Title verified: '{actual[:50]}'")
                    break
                else:
                    logger.warning(f"Baijiahao: Title empty after attempt {attempt + 1}, retrying...")
            except Exception as e:
                logger.warning(f"Baijiahao: Title attempt {attempt + 1} failed: {e}")

        if not title_filled:
            logger.error("Baijiahao: Title is required, aborting")
            return False

        # ========== Step 2: 填入正文内容 ==========
        logger.info("Baijiahao: Step 2 - Filling content...")
        content_filled = False

        # 将 Markdown 转为 HTML
        html_content = _markdown_to_html(description)
        logger.info(f"Baijiahao: Converted markdown to HTML, length={len(html_content)}")

        try:
            # 先诊断页面结构
            editor_type = await page.evaluate("""() => {
                const body = document.querySelector('body[contenteditable="true"]');
                if (body) return 'body-contenteditable';
                const iframes = document.querySelectorAll('iframe');
                for (const iframe of iframes) {
                    try {
                        const ib = iframe.contentDocument?.querySelector('body[contenteditable="true"]');
                        if (ib) return 'iframe-body';
                    } catch(e) {}
                }
                const editables = document.querySelectorAll('[contenteditable="true"]');
                for (const el of editables) {
                    if (!el.closest('[data-testid="news-title-input"]'))
                        return 'generic-' + el.tagName.toLowerCase();
                }
                return 'none';
            }""")
            logger.info(f"Baijiahao: Editor detection: {editor_type}")

            # 优先「真粘贴」——图片必须走编辑器的 paste 管线才会被它重新上传、登记成
            # 「正文图片」，详见 _paste_html 的 docstring。失败才回退到原来的程序化写入。
            pasted = await _paste_html(page, html_content, editor_type)
            if pasted:
                content_filled = True
            elif editor_type == 'body-contenteditable':
                # 使用 execCommand('insertHTML') — 富文本编辑器标准插入方式
                await page.evaluate("""(html) => {
                    const body = document.querySelector('body[contenteditable="true"]');
                    // 先聚焦并全选
                    body.focus();
                    document.execCommand('selectAll', false, null);
                    // 用 insertHTML 替换全部内容（适配 Lexical/Slate 等框架）
                    document.execCommand('insertHTML', false, html);
                }""", html_content)
                content_filled = True

            elif editor_type == 'iframe-body':
                frame = page.frame_locator('iframe').first
                body = frame.locator('body[contenteditable="true"]').first
                if await body.count() > 0:
                    await body.evaluate("""(el, html) => {
                        el.focus();
                        document.execCommand('selectAll', false, null);
                        document.execCommand('insertHTML', false, html);
                    }""", html_content)
                    content_filled = True

            elif editor_type and editor_type.startswith('generic-'):
                await page.evaluate("""(html) => {
                    const editables = document.querySelectorAll('[contenteditable="true"]');
                    for (const el of editables) {
                        if (!el.closest('[data-testid="news-title-input"]')) {
                            el.focus();
                            document.execCommand('selectAll', false, null);
                            document.execCommand('insertHTML', false, html);
                            break;
                        }
                    }
                }""", html_content)
                content_filled = True

            if pasted:
                logger.info("Baijiahao: 正文已通过真粘贴写入（clipboard text/html + Ctrl+V）")
            elif content_filled:
                logger.warning(
                    "Baijiahao: 真粘贴未成功，回退到 execCommand('insertHTML')"
                    "（文本能进，但外链图片不会被子家号收编 ⇒ 封面里很可能选不到图）"
                )
        except Exception as e:
            logger.warning(f"Baijiahao: Content fill failed: {e}")

        if not content_filled:
            # 最后兜底：纯文本模式
            logger.warning("Baijiahao: Falling back to plain text via keyboard")
            try:
                body = page.locator('body').first
                await body.click()
                await page.keyboard.press('Control+a')
                await page.keyboard.type(description, delay=5)
                content_filled = True
                logger.info("Baijiahao: Content filled as plain text")
            except Exception as e2:
                logger.error(f"Baijiahao: Plain text fallback also failed: {e2}")

        if not content_filled:
            logger.error("Baijiahao: All content filling methods failed, aborting")
            return False

        # 给编辑器时间处理内容，并等它把粘贴进来的外链图片重新上传到自己的存储。
        # 这一步不能省：传完才登记为「正文图片」，没传完就开封面弹窗 ⇒ 弹窗里没有图可选。
        # 15 秒是「取宽裕值」不是实测值 —— 图文越多越大需要越久，实测后再按需调整。
        await asyncio.sleep(15)
        try:
            img_count = await page.evaluate("""() => {
                const inEditor = (root) => {
                    if (!root) return 0;
                    let n = 0;
                    root.querySelectorAll('[contenteditable="true"]').forEach(el => {
                        if (!el.closest('[data-testid="news-title-input"]'))
                            n += el.querySelectorAll('img').length;
                    });
                    return n;
                };
                let n = 0;
                try { n += inEditor(document); } catch(e) {}
                document.querySelectorAll('iframe').forEach(f => {
                    try { n += inEditor(f.contentDocument); } catch(e) {}
                });
                return n;
            }""")
            logger.info(f"Baijiahao: 正文里的 <img> 数量={img_count}（0 说明图片没被编辑器接过）")
        except Exception as e:
            logger.warning(f"Baijiahao: 统计正文图片数失败: {e}")

        # ========== Step 2.5: 模拟人工聚焦正文 + Ctrl+A，让编辑器识别正文（否则 AI 封面取不到全文）==========
        await _focus_and_select_content(page, editor_type)
        await asyncio.sleep(1)

        # ========== Step 3: 封面（每一步失败都终止，不跳过） ==========
        # 百家号已改版：封面弹窗打开后默认就停在「正文图片」页签、且已默认选中一张图，
        # 不再需要「点 AI封面页签 → 点生成 → 等 15s 出图 → 选图」这几步 —— 现在只需等
        # 弹窗里的「确定 (N)」出现并点击（N ≥ 1 即已默认选中）。
        # 旧的 AI 生图路径在下面以注释留档（未删除），恢复方法见注释块开头。
        logger.info("Baijiahao: Step 3 - Cover setup...")

        # 3a: 打开封面弹窗
        # 有图片占位 → 点「更换封面」按钮；没图片占位 → 点「选择封面」文本
        cover_btn = page.locator('button[aria-label="更换封面"]').first
        if await cover_btn.count() > 0:
            await cover_btn.click()
            logger.info("Baijiahao: Clicked '更换封面'")
        else:
            # 没图片占位：Playwright 真实点击文本为"选择封面"的 -text 元素
            cover_el = page.get_by_text("选择封面", exact=True).last
            try:
                if await cover_el.is_visible(timeout=3000):
                    await cover_el.scroll_into_view_if_needed(timeout=5000)
                    await cover_el.click(timeout=5000)
                    logger.info("Baijiahao: Clicked '选择封面' (real click)")
                else:
                    raise Exception("cover element not visible")
            except Exception as e:
                # 兜底：JS 定位 -text 元素坐标 → mouse 真实点击
                logger.warning(f"Baijiahao: get_by_text cover click failed ({e}), trying mouse fallback")
                box = await page.evaluate("""() => {
                    const all = document.querySelectorAll('[class]');
                    for (const el of all) {
                        if (el.textContent.trim() === '选择封面' && /(^| )\\S*-text( |$)/.test(el.className)) {
                            const r = el.getBoundingClientRect();
                            return {x: r.x + r.width / 2, y: r.y + r.height / 2};
                        }
                    }
                    return null;
                }""")
                if box:
                    await page.mouse.click(box['x'], box['y'])
                    logger.info("Baijiahao: Clicked '选择封面' (mouse)")
                else:
                    logger.error("Baijiahao: Neither '更换封面' nor '选择封面' found, aborting")
                    return False

        # ────────── 【AI 生图封面】旧路径，2026-10-16 起停用，代码原地留档（未删除）──────────
        # 停用原因：百家号改版，封面弹窗打开后默认就停在「正文图片」页签、且已默认选中一张图，
        #          此时再切去「AI封面」页签反而是把默认的正文图切走，还白等 15s 生成一张 AI 图。
        # 恢复方法：① 去掉下面整段每行行首的 "# "（其后的缩进保持原样，不要动）；
        #          ② 删掉下方 3b 之前新增的那句 await asyncio.sleep(2)
        #             —— 旧路径在 3c 自带 sleep(15) 等生成，不需要这 2 秒。
        # 恢复前提：确认百家号又改回默认停在「AI封面」页签，或产品上要主动切回 AI 生图。
        # 本段包含（旧编号）：等待封面弹窗出现 → 3b 点「AI封面」页签 → 3c 点生成按钮 → 3d 选中生成图。
#         # 等待封面弹窗出现（顶层 + iframe，兼容新旧版：ai_v2/ai node-key、generateBtn、selectArea、
#         # AI封面/AI封图 tab 文本、旧版「根据全文智能生成封面」span）
#         modal_ready = False
#         for _ in range(8):
#             await asyncio.sleep(1)
#             ready = await page.evaluate("""() => {
#                 const check = (doc) => {
#                     if (!doc || !doc.body) return false;
#                     if (doc.querySelector('[data-node-key="ai_v2"], [data-node-key="ai"], [class*="generateBtn"], [class*="selectArea"]')) return true;
#                     const tabs = doc.querySelectorAll('[role="tab"]');
#                     for (const tab of tabs) {
#                         const t = (tab.textContent || '').trim();
#                         if (t === 'AI封面' || t === 'AI封图' || t === 'AI 封面' || t === '智能封面') return true;
#                     }
#                     const spans = doc.querySelectorAll('span');
#                     for (const s of spans) {
#                         if (s.textContent.includes('根据全文智能生成封面')) return true;
#                     }
#                     return false;
#                 };
#                 if (check(document)) return true;
#                 const iframes = document.querySelectorAll('iframe');
#                 for (const f of iframes) {
#                     try { if (check(f.contentDocument)) return true; } catch(e) {}
#                 }
#                 return false;
#             }""")
#             if ready:
#                 modal_ready = True
#                 break
#         if not modal_ready:
#             await _dump_visible_texts(page, "cover-modal")
#             logger.error("Baijiahao: Cover modal did not open, aborting")
#             return False
#         logger.info("Baijiahao: Cover modal opened")
#
#         # 3b: 点击「AI封面」tab —— 兼容默认已选中态（顶层 + iframe）
#         ai_tab_clicked = await page.evaluate("""() => {
#             const clickTab = (doc) => {
#                 if (!doc || !doc.body) return false;
#                 const tabs = doc.querySelectorAll('[role="tab"]');
#                 for (const tab of tabs) {
#                     const t = (tab.textContent || '').trim();
#                     if (t === 'AI封面' || t === 'AI封图' || t === 'AI 封面' || t === '智能封面') {
#                         const tabWrap = tab.closest('.cheetah-tabs-tab');
#                         const active = tab.getAttribute('aria-selected') === 'true'
#                             || (tabWrap && tabWrap.className.includes('cheetah-tabs-tab-active'));
#                         if (!active) tab.click();
#                         return true;
#                     }
#                 }
#                 const node = doc.querySelector('[data-node-key="ai_v2"], [data-node-key="ai"]');
#                 if (node) { node.click(); return true; }
#                 return false;
#             };
#             if (clickTab(document)) return true;
#             const iframes = document.querySelectorAll('iframe');
#             for (const f of iframes) {
#                 try { if (clickTab(f.contentDocument)) return true; } catch(e) {}
#             }
#             return false;
#         }""")
#         if not ai_tab_clicked:
#             await _dump_visible_texts(page, "ai-tab")
#             logger.error("Baijiahao: AI cover tab not found, aborting")
#             return False
#         logger.info("Baijiahao: AI cover tab ready")
#         await asyncio.sleep(1)
#
#         # 3c: 点击 AI 封面生成按钮
#         # 新版：无文本背景图按钮 #ai-cover-tab-v2-step-1 / [class*="generateBtn"]
#         # 旧版：span 文本「根据全文智能生成封面」
#         # 顶层 Playwright 真实点击优先，失败后 JS 顶层 + iframe 双扫兜底
#         gen_clicked = False
#         gen_btn = page.locator('#ai-cover-tab-v2-step-1').first
#         if await gen_btn.count() > 0:
#             try:
#                 await gen_btn.click(timeout=5000)
#                 gen_clicked = True
#                 logger.info("Baijiahao: AI cover generate button clicked (#ai-cover-tab-v2-step-1)")
#             except Exception as e:
#                 logger.warning(f"Baijiahao: generate button click failed: {e}")
#         if not gen_clicked:
#             gen_res = await page.evaluate("""() => {
#                 const hit = {clicked: false, kind: ''};
#                 const clickGen = (doc) => {
#                     if (!doc || !doc.body) return false;
#                     const btn = doc.querySelector('#ai-cover-tab-v2-step-1') || doc.querySelector('[class*="generateBtn"]');
#                     if (btn) { btn.click(); hit.kind = 'new-btn'; return true; }
#                     const spans = doc.querySelectorAll('span');
#                     for (const s of spans) {
#                         if (s.textContent.includes('根据全文智能生成封面')) { s.click(); hit.kind = 'legacy-span'; return true; }
#                     }
#                     return false;
#                 };
#                 if (clickGen(document)) { hit.clicked = true; return hit; }
#                 const iframes = document.querySelectorAll('iframe');
#                 for (const f of iframes) {
#                     try { if (clickGen(f.contentDocument)) { hit.clicked = true; return hit; } } catch(e) {}
#                 }
#                 return hit;
#             }""")
#             if gen_res.get('clicked'):
#                 gen_clicked = True
#                 logger.info(f"Baijiahao: AI cover generate button clicked (JS: {gen_res.get('kind')})")
#         if not gen_clicked:
#             await _dump_visible_texts(page, "generate-btn")
#             logger.error("Baijiahao: AI cover generate button not found, aborting")
#             return False
#         logger.info("Baijiahao: AI cover generation started, waiting for images...")
#         await asyncio.sleep(15)
#
#         # 3d: 等待生成的图片出现并选中一张（新版 selectArea 选择标记；旧版无此步直接出确定；顶层 + iframe）
#         image_selected = False
#         for i in range(30):
#             await asyncio.sleep(2)
#             sel = await page.evaluate("""() => {
#                 const scan = (doc) => {
#                     if (!doc || !doc.body) return 'none';
#                     const area = doc.querySelector('[class*="selectArea"]');
#                     if (!area || area.offsetParent === null) return 'none';
#                     const wrap = area.closest('[class*="-wrap"]');
#                     const already = wrap && wrap.className.includes('selected');
#                     if (already) return 'already-selected';
#                     const target = wrap ? (wrap.querySelector('img') || area) : area;
#                     target.click();
#                     return 'clicked';
#                 };
#                 let r = scan(document);
#                 if (r !== 'none') return r;
#                 const iframes = document.querySelectorAll('iframe');
#                 for (const f of iframes) {
#                     try { r = scan(f.contentDocument); if (r !== 'none') return r; } catch(e) {}
#                 }
#                 return 'waiting';
#             }""")
#             if sel == 'clicked':
#                 logger.info("Baijiahao: AI image clicked to select")
#                 image_selected = True
#                 break
#             elif sel == 'already-selected':
#                 logger.info("Baijiahao: AI image already selected")
#                 image_selected = True
#                 break
#             # 旧版兼容：约 16s 后仍无选图区，但「确定 (N)」已出现 → 旧版无选图步骤，跳过
#             if i >= 7:
#                 has_confirm = await page.evaluate("""() => {
#                     const scan = (doc) => {
#                         if (!doc || !doc.body) return false;
#                         const btns = doc.querySelectorAll('button');
#                         for (const b of btns) {
#                             if (/确定 \\(\\d+\\)/.test(b.textContent.trim()) && b.offsetParent !== null) return true;
#                         }
#                         return false;
#                     };
#                     if (scan(document)) return true;
#                     const iframes = document.querySelectorAll('iframe');
#                     for (const f of iframes) {
#                         try { if (scan(f.contentDocument)) return true; } catch(e) {}
#                     }
#                     return false;
#                 }""")
#                 if has_confirm:
#                     logger.info("Baijiahao: Legacy cover mode detected, skipping image selection")
#                     image_selected = True
#                     break
#         if not image_selected:
#             await _dump_visible_texts(page, "ai-images")
#             logger.error("Baijiahao: No AI image appeared after generation, aborting")
#             return False
#         await asyncio.sleep(1)

        # 3b: 轮询点击「确定 (N)」，处理"封面裁剪处理中"的重试（顶层 + iframe）
        # 弹窗打开后默认停在「正文图片」页签并已默认选中，所以这段既是「等弹窗渲染完」
        # 也是「点确定」，不需要上游任何生成/选图步骤。
        await asyncio.sleep(2)  # 入场有动画，动画期间按钮 offsetParent 仍为 null，会白跑两轮
        logger.info("Baijiahao: Polling for confirm button...")
        for i in range(30):
            result = await page.evaluate("""() => {
                const scan = (doc) => {
                    if (!doc || !doc.body) return 'waiting';
                    const btns = doc.querySelectorAll('button');
                    for (const b of btns) {
                        const t = b.textContent.trim();
                        if (/确定 \\(\\d+\\)/.test(t) && b.offsetParent !== null) {
                            b.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
                            b.dispatchEvent(new PointerEvent('pointerup', {bubbles: true}));
                            return 'clicked-' + t;
                        }
                    }
                    return 'waiting';
                };
                let r = scan(document);
                if (r !== 'waiting') return r;
                const iframes = document.querySelectorAll('iframe');
                for (const f of iframes) {
                    try { r = scan(f.contentDocument); if (r !== 'waiting') return r; } catch(e) {}
                }
                return 'waiting';
            }""")
            if result.startswith('clicked-'):
                logger.info(f"Baijiahao: Confirm clicked: {result}")
                await asyncio.sleep(1)
                # 检查按钮是否还在（还在说明点击没成功，可能弹了"封面裁剪处理中"）
                still_there = await page.evaluate("""() => {
                    const scan = (doc) => {
                        if (!doc || !doc.body) return false;
                        const btns = doc.querySelectorAll('button');
                        for (const b of btns) {
                            if (/确定 \\(\\d+\\)/.test(b.textContent.trim()) && b.offsetParent !== null)
                                return true;
                        }
                        return false;
                    };
                    if (scan(document)) return true;
                    const iframes = document.querySelectorAll('iframe');
                    for (const f of iframes) {
                        try { if (scan(f.contentDocument)) return true; } catch(e) {}
                    }
                    return false;
                }""")
                if not still_there:
                    logger.info("Baijiahao: Confirm dialog closed, success!")
                    break
                else:
                    logger.info("Baijiahao: Confirm still visible (封面裁剪处理中?), waiting 5s retry...")
                    await asyncio.sleep(5)
            else:
                await asyncio.sleep(2)
        else:
            await _dump_visible_texts(page, "cover-confirm")
            logger.error("Baijiahao: Confirm button never succeeded after 60s, aborting")
            return False
        logger.info("Baijiahao: Cover confirmed, waiting 10s...")
        await asyncio.sleep(10)

        # ========== Step 4: 勾选协议复选框 ==========
        logger.info("Baijiahao: Step 4 - Checking agreement checkbox...")
        try:
            checkbox = page.locator('input.cheetah-checkbox-input[type="checkbox"]').first
            if await checkbox.count() > 0:
                is_checked = await checkbox.is_checked()
                if not is_checked:
                    await checkbox.check()
                    await asyncio.sleep(0.5)
                    logger.info("Baijiahao: Agreement checkbox checked")
                else:
                    logger.info("Baijiahao: Agreement checkbox already checked")
            else:
                logger.warning("Baijiahao: Agreement checkbox not found")
        except Exception as e:
            logger.warning(f"Baijiahao: Checkbox check failed: {e}")

        await before_submit()
        # ========== Step 5: 点击发布 ==========
        logger.info("Baijiahao: Step 5 - Clicking publish button...")
        try:
            publish_btn = page.locator('button[data-testid="publish-btn"]').first
            if await publish_btn.count() > 0:
                await publish_btn.click()
                logger.info("Baijiahao: Publish button clicked")
            else:
                logger.warning("Baijiahao: Publish button not found")
                return False
        except Exception as e:
            logger.error(f"Baijiahao: Publish click failed: {e}")
            return False

        # 等待发布结果
        await asyncio.sleep(5)

        # ========== Step 6: 确认结果 ==========
        current_url = page.url
        logger.info(f"Baijiahao: Post-publish URL={current_url}")
        if "/edit" not in current_url:
            logger.info("Baijiahao: Publish appears successful (left edit page)")
        else:
            logger.warning("Baijiahao: Still on edit page, publish may have failed")

        logger.info(f"Baijiahao: === END publish for {account.name} ===")
        return True

    except Exception as e:
        logger.error(f"Baijiahao: Unexpected error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

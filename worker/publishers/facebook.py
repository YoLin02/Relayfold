"""Facebook 视频帖发布 —— Playwright 浏览器自动化。

发布到「当前浏览器里那个身份」的时间线：账号登的是个人号就发个人时间线，
登的是主页管理员就发主页。切身份要手动在浏览器里做，发布器不代替用户选。

流程（按真机标定）：
  首页点「照片/视频」→ 选文件 → 弹出「发帖」框 → 写正文
  → 分享对象改成「公开」→ AI 标签改成「开」→ 点「发帖」
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from playwright.async_api import Page

from ._text import plain_text

logger = logging.getLogger("video_publisher")

HOME_URL = "https://www.facebook.com/"

# 首页发帖框下面那个「照片/视频」入口（图库图标）
_MEDIA_BTN_SELECTORS = (
    'div[aria-label="照片/视频"]',
    'div[aria-label="Photo/video"]',
    'div[role="button"][aria-label="照片/视频"]',
    'div[role="button"][aria-label="Photo/video"]',
    'div[role="button"]:has-text("照片/视频")',
    'div[role="button"]:has-text("Photo/video")',
)

# ---- 页面内定位脚本 ----------------------------------------------------------
# Facebook 的 class 名是混淆的，只能靠 aria-label 和可见文案定位。找到目标后
# 打一个 data-zx-* 标记，外层再用 Playwright 点击，这样点击走的是真实事件链。

# 通用定位策略：Facebook 的弹框里这些按钮未必是 role="button"（实测「公开」
# 和「AI 标签」两个按钮就不是），所以不限定标签和 role，改为在**最上层的可见
# 弹框**里按可见文案找，取最内层命中的元素打标记。
#
# 注意先用 textContent 粗筛（便宜），命中后才调 innerText（会触发布局），
# 否则在几千个节点的 FB 页面上逐个 innerText 会卡住。

_JS_AUDIENCE = """
() => {
  document.querySelectorAll('[data-zx-audience]').forEach(e => e.removeAttribute('data-zx-audience'));
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const editor = document.querySelector('[contenteditable="true"][role="textbox"]');
  let root = editor && editor.closest('[role="dialog"]');
  if (!root) {
    const dlgs = [...document.querySelectorAll('[role="dialog"]')].filter(vis);
    root = dlgs[dlgs.length - 1];
  }
  if (!root) return null;
  const names = ['公开', '好友', '密友', '仅自己', 'Public', 'Friends', 'Only me'];
  const hits = [];
  for (const el of root.querySelectorAll('*')) {
    const t = (el.textContent || '').trim();
    if (!t || t.length >= 20) continue;
    if (!names.some(n => t.includes(n))) continue;
    if (!vis(el)) continue;
    hits.push({ el, t });
  }
  if (!hits.length) return null;
  const clickable = hits.filter(h => h.el.closest('[role="button"], [tabindex="0"], button, a, label'));
  const pool = clickable.length ? clickable : hits;
  const best = pool.find(h => !pool.some(o => o !== h && h.el.contains(o.el)));
  if (!best) return null;
  best.el.setAttribute('data-zx-audience', '1');
  return best.t;
}
"""

_JS_AI_LABEL = """
() => {
  document.querySelectorAll('[data-zx-ai]').forEach(e => e.removeAttribute('data-zx-ai'));
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const editor = document.querySelector('[contenteditable="true"][role="textbox"]');
  let root = editor && editor.closest('[role="dialog"]');
  if (!root) {
    const dlgs = [...document.querySelectorAll('[role="dialog"]')].filter(vis);
    root = dlgs[dlgs.length - 1];
  }
  if (!root) return null;
  const re = /AI\\s*标签|AI\\s*label/i;
  const hits = [];
  for (const el of root.querySelectorAll('*')) {
    const t = (el.textContent || '').trim();
    if (!t || t.length >= 30 || !re.test(t)) continue;
    if (!vis(el)) continue;
    hits.push({ el, t });
  }
  if (!hits.length) return null;
  const clickable = hits.filter(h => h.el.closest('[role="button"], [tabindex="0"], button, a, label'));
  const pool = clickable.length ? clickable : hits;
  const best = pool.find(h => !pool.some(o => o !== h && h.el.contains(o.el)));
  if (!best) return null;
  best.el.setAttribute('data-zx-ai', '1');
  return best.t;
}
"""

# 「帖子分享对象」弹框里的「公开」选项。选项行里除了名字还有一行说明，
# 文本会是「公开 Facebook 站内或站外的任何人」。
_JS_PICK_PUBLIC = """
() => {
  document.querySelectorAll('[data-zx-public]').forEach(e => e.removeAttribute('data-zx-public'));
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const dlgs = [...document.querySelectorAll('[role="dialog"]')].filter(vis);
  const root = dlgs[dlgs.length - 1];
  if (!root) return null;
  const hits = [];
  for (const el of root.querySelectorAll('*')) {
    const t = (el.textContent || '').trim();
    if (!t || t.length >= 60) continue;
    if (!t.includes('公开') && !t.includes('Public')) continue;
    if (!vis(el)) continue;
    hits.push({ el, t });
  }
  if (!hits.length) return null;
  const clickable = hits.filter(h => h.el.closest('[role="radio"], [role="button"], [tabindex="0"], label, button'));
  const pool = clickable.length ? clickable : hits;
  const best = pool.find(h => !pool.some(o => o !== h && h.el.contains(o.el)));
  if (!best) return null;
  best.el.setAttribute('data-zx-public', '1');
  return best.t;
}
"""

# 找不到目标时把页面上的可点元素 dump 出来，便于按真实结构标定。
# 扫全 body 而不是只扫弹框：按钮有可能根本没被弹框包住，那样只扫弹框会一片空白。
# 每条用 IN / OUT 标出在不在最上层弹框里。
# 注意用 textContent + getBoundingClientRect：弹框是 position:fixed（offsetParent
# 恒为 null），且 Facebook 用 content-visibility 让 innerText 漏掉未渲染的内容。
_JS_DUMP = """
() => {
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const editor = document.querySelector('[contenteditable="true"][role="textbox"]');
  const root = (editor && editor.closest('[role="dialog"]')) ||
               [...document.querySelectorAll('[role="dialog"]')].filter(vis).pop();
  const fmt = (el, where) => {
    if (!vis(el)) return null;
    const t = (el.textContent || '').trim();
    if (!t || t.length > 200) return null;
    const role = el.getAttribute('role') || '';
    const aria = el.getAttribute('aria-label') || '';
    const tab = el.getAttribute('tabindex');
    if (!role && !aria && tab !== '0') return null;
    return where + ' ' + el.tagName.toLowerCase() + ' role=' + role + ' aria=' + aria +
           ' tab=' + (tab || '') + ' <' + t.slice(0, 40) + '>';
  };
  const out = [];
  // 先扫弹框内部：首页元素成百上千，先扫 body 会把 40 条名额占满，弹框里一条都看不到
  if (root) {
    out.push('ROOT ' + root.tagName.toLowerCase() + ' role=' + (root.getAttribute('role') || '') +
             ' aria=' + (root.getAttribute('aria-label') || '') +
             ' children=' + root.children.length +
             ' text=<' + (root.textContent || '').trim().slice(0, 60) + '>');
    for (const el of root.querySelectorAll('*')) {
      if (out.length >= 40) break;
      const s = fmt(el, 'IN ');
      if (s) out.push(s);
    }
  }
  // 还不够再补弹框外的，主要用来确认按钮是不是压根没在弹框里
  for (const el of document.body.querySelectorAll('*')) {
    if (out.length >= 60) break;
    if (root && root.contains(el)) continue;
    const s = fmt(el, 'OUT');
    if (s) out.push(s);
  }
  return out;
}
"""

# 「标记你的内容」弹框里的开关：on / off / none
#
# 这个弹框打开时发帖框还在后面，两个 dialog 同时可见，所以不能按"最后一个
# dialog"取根——按文案锚定到「标记你的内容」那个框。
# 开关本体是 Meta 自己的胶囊滑块，实测既没有 role="switch" 也没有
# input[type=checkbox]，只能退一步认 aria-checked。
_JS_SWITCH_STATE = """
() => {
  document.querySelectorAll('[data-zx-switch]').forEach(e => e.removeAttribute('data-zx-switch'));
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const dlgs = [...document.querySelectorAll('[role="dialog"]')].filter(vis);
  const root = dlgs.find(d => (d.textContent || '').includes('添加 AI 标签')) ||
               dlgs.find(d => (d.textContent || '').includes('标记你的内容')) ||
               dlgs[dlgs.length - 1];
  if (!root) return 'none';
  const sw = root.querySelector(
    '[role="switch"], input[type="checkbox"], [role="checkbox"], [aria-checked]'
  );
  if (!sw) return 'none';
  const on = sw.getAttribute('aria-checked') === 'true' ||
             sw.getAttribute('aria-pressed') === 'true' ||
             sw.checked === true;
  if (on) return 'on';
  sw.setAttribute('data-zx-switch', '1');
  return 'off';
}
"""

# 开关连 aria-checked 都没有时的兜底：点「添加 AI 标签」这一行最右侧的控件。
# 开关必然在行尾，「知道了」按钮在下方，靠文案排除掉。
_JS_MARK_SWITCH_ROW = """
() => {
  document.querySelectorAll('[data-zx-switch-row]').forEach(e => e.removeAttribute('data-zx-switch-row'));
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const dlgs = [...document.querySelectorAll('[role="dialog"]')].filter(vis);
  const root = dlgs.find(d => (d.textContent || '').includes('添加 AI 标签')) ||
               dlgs.find(d => (d.textContent || '').includes('标记你的内容'));
  if (!root) return null;
  const label = [...root.querySelectorAll('*')].find(el =>
    (el.textContent || '').trim().startsWith('添加 AI 标签') && vis(el) &&
    ![...el.children].some(c => (c.textContent || '').trim().startsWith('添加 AI 标签'))
  );
  if (!label) return null;
  // 开关和「添加 AI 标签」在同一行、位于它右侧。不按"行容器"找——说明文字和
  // 标签往往挤在同一个 flex 列里，爬上去会连开关一起排除掉。
  // 用文本的实际范围而不是盒子：标签若是块级元素会撑满整行，右边距就恒在
  // 开关右侧，开关永远过不了左边界判断。
  const box = label.getBoundingClientRect();
  const rng = document.createRange();
  rng.selectNodeContents(label);
  const tb = rng.getBoundingClientRect();
  const lb = (tb.width > 0 && tb.height > 0) ? tb : box;
  const cands = [...root.querySelectorAll('*')].filter(vis).filter(e => {
    if (e === label || e.contains(label)) return false;
    const r = e.getBoundingClientRect();
    // 垂直只要有交叠即可：开关常在一整行的垂直居中位置，和标签的垂直中心对不齐
    const overlap = Math.min(lb.bottom, r.bottom) - Math.max(lb.top, r.top);
    return r.left >= lb.right - 2 && overlap > 0;
  });
  if (!cands.length) return null;
  // 取最靠右的；right 相同取面积最小的（容器外壳 vs 开关本体，选本体）
  cands.sort((a, b) => {
    const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
    if (Math.abs(rb.right - ra.right) > 1) return rb.right - ra.right;
    return ra.width * ra.height - rb.width * rb.height;
  });
  const best = cands[0];
  best.setAttribute('data-zx-switch-row', '1');
  return (best.getAttribute('aria-label') || String(best.className || '').slice(0, 40) ||
          best.tagName.toLowerCase());
}
"""

# 按可见文案定位按钮（完成 / 知道了 / 发帖）。同样不限定 role="button"，
# 但优先取落在可点区域里的元素——弹框标题「发帖」和按钮「发帖」文案相同，
# 不加这层会点到标题。
_JS_MARK_BUTTON = """
(args) => {
  document.querySelectorAll('[data-zx-click]').forEach(e => e.removeAttribute('data-zx-click'));
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const hits = [];
  for (const el of document.body.querySelectorAll('*')) {
    const t = (el.textContent || '').trim();
    if (!t || t.length > 40) continue;
    if (!args.includes(t)) continue;
    if (!vis(el)) continue;
    hits.push({ el, t });
  }
  if (!hits.length) return null;
  const clickable = hits.filter(h => h.el.closest('[role="button"], [tabindex="0"], button, a'));
  const pool = clickable.length ? clickable : hits;
  const best = pool.find(h => !pool.some(o => o !== h && h.el.contains(o.el)));
  if (!best) return null;
  best.el.setAttribute('data-zx-click', '1');
  return best.t;
}
"""


# 发帖弹框里是否还挂着上传/转码进度
_JS_UPLOADING = """
() => {
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const dlgs = [...document.querySelectorAll('[role="dialog"]')].filter(vis);
  const root = dlgs[dlgs.length - 1];
  if (!root) return false;
  return !!root.querySelector('[role="progressbar"], [aria-busy="true"]');
}
"""


def _ai_label_on(label: str) -> bool:
    """「AI 标签：开」才算已开启，其它一律当未开启。

    按钮 innerText 会带下拉箭头（「AI 标签： 关▾」），所以按包含判断，不按结尾。
    """
    s = (label or "").strip().lower()
    return not ("关" in s or "off" in s)


async def publish(
    page: Page,
    account,
    media_paths: list[str],
    title: Optional[str] = None,
    description: Optional[str] = None,
    *,
    before_submit,
) -> bool:
    logger.info(f"Facebook: 开始发布 {account.name}，media={media_paths}")

    if not media_paths:
        raise RuntimeError("Facebook 发布需要视频文件")
    video = media_paths[0]
    if not os.path.exists(video):
        raise RuntimeError(f"视频文件不存在：{os.path.basename(video)}")
    # 记下大小：真机上出现「FB 上只有前几秒」时，先看这里对不对得上素材库
    logger.info(
        f"Facebook: 待发布视频 {os.path.basename(video)} "
        f"{os.path.getsize(video) / 1024 / 1024:.1f}MB"
    )

    await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=90000)
    await asyncio.sleep(5)

    current = page.url.lower()
    if "/login" in current or "checkpoint" in current:
        raise RuntimeError("Facebook 登录已失效或被风控拦截，请重新登录账号")

    # ① 首页点「照片/视频」，把文件直接喂给弹出的文件选择器
    media_btn = await _first(page, _MEDIA_BTN_SELECTORS, timeout=2500)
    if not media_btn:
        raise RuntimeError("Facebook 未找到「照片/视频」按钮（页面版式可能变了）")
    await _choose_file(page, media_btn, video)
    logger.info("Facebook: 视频已选择，等待上传")

    # ② 等「发帖」弹框
    try:
        await page.wait_for_selector(
            'div[role="dialog"] div[contenteditable="true"][role="textbox"]', timeout=90000
        )
    except Exception:
        raise RuntimeError("Facebook 选完视频后没有打开发帖弹框")
    await asyncio.sleep(3)

    # ③ 写正文
    text = plain_text(title, description)
    if text:
        editor = await page.query_selector(
            'div[role="dialog"] div[contenteditable="true"][role="textbox"]'
        )
        if not editor:
            raise RuntimeError("Facebook 发帖弹框里没找到正文输入框")
        await editor.click()
        await asyncio.sleep(0.5)
        await page.keyboard.press("Control+a")
        await page.keyboard.press("Delete")
        await asyncio.sleep(0.3)
        await page.keyboard.insert_text(text)
        await asyncio.sleep(1.5)
        logger.info(f"Facebook: 正文已填写（{len(text)} 字）")
    else:
        logger.warning("Facebook: 没有正文，只发视频")

    # ⑥ 等视频传完（「发帖」从灰变蓝）再点
    if not await _wait_post_enabled(page, timeout=600):
        raise RuntimeError("Facebook 视频上传/转码超时（30 分钟），「发帖」一直不可用")
    await before_submit()
    if not await _click_button(page, ("发帖", "Post")):
        raise RuntimeError("Facebook 没找到「发帖」按钮")
    logger.info("Facebook: 已点击「发帖」")

    # ⑦ 弹框关闭视为成功
    for _ in range(12):
        await asyncio.sleep(5)
        try:
            closed = await page.evaluate(
                """() => {
                    const d = document.querySelector('div[role="dialog"]');
                    return !d || !d.querySelector('div[contenteditable="true"]');
                }"""
            )
        except Exception:
            return True
        if closed:
            logger.info(f"Facebook: 发布完成 {account.name}")
            return True

    raise RuntimeError("Facebook 点击「发帖」后弹框未关闭，可能被风控拦截")


# ---- 辅助 --------------------------------------------------------------------

async def _first(page: Page, selectors, timeout: int = 2500):
    """按顺序试一组选择器，返回第一个可见元素。"""
    for sel in selectors:
        try:
            el = await page.wait_for_selector(sel, timeout=timeout, state="visible")
            if el:
                return el
        except Exception:
            continue
    return None


async def _choose_file(page: Page, btn, video: str) -> None:
    """点「照片/视频」后 Playwright 能拦到文件选择器；拦不到就退回直接喂 input。"""
    try:
        async with page.expect_file_chooser(timeout=15000) as info:
            await btn.click()
        chooser = await info.value
        await chooser.set_files(video)
        return
    except Exception as e:
        logger.warning(f"Facebook: 没拦到文件选择器（{e}），改用 input[type=file]")
    inputs = await page.query_selector_all('input[type="file"]')
    if not inputs:
        raise RuntimeError("Facebook 点「照片/视频」后没有弹出文件选择器")
    await inputs[-1].set_input_files(video)


async def _click_button(page: Page, texts) -> bool:
    """按可见文案点一个 role=button。"""
    hit = await page.evaluate(_JS_MARK_BUTTON, list(texts))
    if not hit:
        return False
    await page.click('[data-zx-click="1"]')
    return True


async def _wait_post_enabled(page: Page, timeout: int) -> bool:
    """等「发帖」从灰变可点（视频上传/转码期间是 aria-disabled）。

    每轮都重新定位按钮，不持有句柄——转码完成后 Facebook 会重渲染这一行，
    旧句柄会 detached。

    另外还要确认弹框里已经没有上传进度：aria-disabled 不是 Facebook 表达
    「上传中」的唯一方式，光看它会在视频没传完时就把帖子发出去。
    """
    for _ in range(max(1, timeout // 10)):
        if await page.evaluate(_JS_UPLOADING):
            await asyncio.sleep(10)
            continue
        hit = await page.evaluate(_JS_MARK_BUTTON, ["发帖", "Post"])
        if hit:
            el = await page.query_selector('[data-zx-click="1"]')
            if el:
                try:
                    if (await el.get_attribute("aria-disabled")) != "true":
                        return True
                except Exception:
                    pass
        await asyncio.sleep(10)
    return False

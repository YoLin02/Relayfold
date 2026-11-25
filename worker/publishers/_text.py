"""社媒发布共用的正文处理。

Facebook / Instagram / Twitter 的发布框都是纯文本（没有富文本编辑器，
粘进去 `##` `**` 就是字面字符），所以发之前先把 markdown 压成纯文本。
"""
from __future__ import annotations

import re
from typing import Optional


def plain_text(title: Optional[str], description: Optional[str]) -> str:
    """把标题与正文合成一段纯文本；标题已出现在正文开头时不重复。"""
    text = (description or "").strip()
    head = (title or "").strip()
    if head and head not in text:
        text = f"{head}\n\n{text}".strip()

    text = re.sub(r"!\[[^\]]*\]\([^\)]*\)", "", text)        # 图片语法整段去掉
    text = re.sub(r"\[([^\]]*)\]\([^\)]*\)", r"\1", text)     # 链接只留文字
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)       # 井号标题
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)           # 加粗
    text = re.sub(r"[ \t]+\n", "\n", text)                   # 删图后残留的行尾空格
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

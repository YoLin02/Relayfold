import re
from pathlib import Path

from catalog import PLATFORMS


CUSTOM_PLATFORMS = {"douyin", "xiaohongshu"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
CONTENT_FIELDS = {"title", "description", "tags", "cover"}


def local_file(value, extensions):
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError("本地文件路径无效。")
    path = Path(value)
    try:
        if path.is_absolute() and path.suffix.lower() in extensions and path.is_file() and path.stat().st_size:
            return path.resolve()
    except OSError:
        pass
    raise ValueError("本地文件不存在、为空或文件格式有误。")


def resolve_content(data, bindings, kind, sources):
    custom = data.get("overrides", {})
    allowed = {row["id"] for row in bindings if row["platform"] in CUSTOM_PLATFORMS}
    if not isinstance(custom, dict) or custom.keys() - allowed:
        raise ValueError("平台覆盖设置包含未选中或不支持的账号。")
    defaults = {key: data.get(key, "") for key in CONTENT_FIELDS}
    if any(not isinstance(value, str) for value in defaults.values()):
        raise ValueError("通用发布内容格式无效。")
    result = {}
    for row in bindings:
        target = custom.get(row["id"], {})
        if not isinstance(target, dict) or target.keys() - CONTENT_FIELDS:
            raise ValueError("平台覆盖设置无效。")
        supports_custom = row["id"] in allowed
        fields = defaults | target if supports_custom else {key: defaults[key] for key in ("title", "description")}
        if any(not isinstance(value, str) for value in fields.values()):
            raise ValueError("发布内容格式无效。")

        spec = PLATFORMS[row["platform"]]
        title, description = fields["title"].strip(), fields["description"].strip()
        if not title or len(title) > spec.title_limit:
            raise ValueError(f"请填写{spec.label}标题，最多 {spec.title_limit} 个字符。")
        if kind == "article" and not description:
            raise ValueError("请填写文章正文。")
        tags = list(dict.fromkeys(
            tag.strip().strip("#＃").strip()
            for tag in re.split(r"[,，、\r\n]+", fields.get("tags", "")) if tag.strip().strip("#＃").strip()
        ))
        if len(tags) > 10 or any(len(tag) > 30 or "#" in tag or "＃" in tag for tag in tags):
            raise ValueError(f"{spec.label}最多可填写 10 个标签，每个最多 30 个字符。")
        tag_length = sum(len(tag) + 2 for tag in tags)
        if len(description) + tag_length > (50000 if kind == "article" else 1000):
            raise ValueError(f"{spec.label}正文和标签超出长度限制。")

        cover = local_file(fields["cover"], IMAGE_EXTENSIONS) if fields.get("cover") else None
        if kind == "image" and cover and cover not in sources:
            raise ValueError(f"请从本批图片中选择{spec.label}图文封面。")
        result[row["id"]] = {"title": title, "description": description, "tags": tags, "cover": cover}
    return result

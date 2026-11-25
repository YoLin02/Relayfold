import hashlib
import re
from importlib import import_module
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx

from catalog import PLATFORMS
from publishers import company_website_v2, devto, douyin, xiaohongshu


def valid_url(value):
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("请输入完整的 HTTPS 地址。")
    try:
        parts.port
    except ValueError as exc:
        raise ValueError("HTTPS 地址的端口无效。") from exc
    return value


def platform_settings(platform, values):
    def required(key, label):
        value = str(values.get(key) or "").strip()
        if not value:
            raise ValueError(f"请填写{label}。")
        return value

    if platform == "company_website":
        return {"website_url": valid_url(required("website_url", "CMS 文章管理页"))}
    if platform == "devto":
        return {"api_password": required("api_password", "DEV API Key")}
    if platform == "company_website_v2":
        base = valid_url(required("api_base", "CMS API 基址"))
        url = urlsplit(base)
        if url.query or url.fragment:
            raise ValueError("CMS API 基址请填写到接口前缀，去掉查询参数和页面锚点。")
        return {"api_base": base.rstrip("/"), "website_url": valid_url(required("website_url", "目标站点地址")),
                "api_username": required("api_username", "CMS 用户名"), "api_password": required("api_password", "CMS 密码"),
                "cms_site_id": str(values.get("cms_site_id") or "").strip(),
                "cms_category_id": str(values.get("cms_category_id") or "").strip()}
    raise ValueError("这个平台使用浏览器登录。")


def normalize_options(platforms, options):
    result = {}
    if "bilibili" in platforms:
        source = str(options.get("bili_source", "")).strip()
        category = str(options.get("bili_category", "")).strip()
        tags = [tag.strip() for tag in re.split(r"[,，]", str(options.get("bili_tags", ""))) if tag.strip()]
        if source not in {"自制", "转载"} or not category.strip(" / ") or not tags or len(tags) > 10:
            raise ValueError("请填写 B 站分区、稿件类型和 1–10 个标签。")
        origin = str(options.get("bili_origin", "")).strip()
        if source == "转载" and not origin:
            raise ValueError("请填写 B 站转载来源。")
        result.update(bili_source=source, bili_category=category, bili_tags=list(dict.fromkeys(tags)), bili_origin=origin)
    if "youtube" in platforms:
        visibility = options.get("youtube_visibility")
        kids = options.get("youtube_kids")
        if visibility not in {"PUBLIC", "UNLISTED", "PRIVATE"} or not isinstance(kids, bool):
            raise ValueError("请选择 YouTube 可见范围和儿童内容声明。")
        result.update(youtube_visibility=visibility, youtube_kids=kids)
    if "reddit" in platforms:
        target = str(options.get("reddit_target", "")).strip().strip("/")
        if not re.fullmatch(r"(?:r|user)/[A-Za-z0-9_-]{2,32}", target):
            raise ValueError("请填写 Reddit 目标，例如 r/example 或 user/example。")
        result["reddit_target"] = "/" + target
    if "csdn" in platforms:
        result["csdn_keywords"] = str(options.get("csdn_keywords") or "").strip()
    return result


async def api_identity(binding):
    current = binding["settings"]
    try:
        if binding["platform"] == "devto":
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(f"{devto.API_BASE}/users/me", headers={"api-key": current["api_password"]})
            response.raise_for_status()
            info = response.json()
            identity = str(info.get("id") or "")
            name = info.get("username") or info.get("name") or ""
        else:
            account = SimpleNamespace(**current, id=binding["id"])
            token = await company_website_v2._login(account)
            site_id = await company_website_v2.resolve_site_id(account, token)
            if not site_id:
                raise ValueError("CMS 凭据下找不到指定的站点。")
            identity = f"{current['api_base']}\0{current['api_username']}\0{site_id}"
            binding["api_runtime"] = {"site_id": site_id, "token": token}
            name = urlsplit(current["website_url"]).hostname
    except (httpx.HTTPError, RuntimeError, KeyError) as exc:
        raise ValueError("API 凭据验证失败。请检查目标站点、账号和网络。") from exc
    if not identity:
        raise ValueError("平台未返回可核对的账号标识。")
    return {"proof": hashlib.sha256(f"{binding['platform']}\0{identity}".encode()).hexdigest(), "name": name}


async def publish_api(binding, task, before_submit):
    settings = binding["settings"]
    account = SimpleNamespace(id=binding["id"], name=binding["label"], **settings)
    if binding["platform"] == "devto":
        return await devto.publish(None, account, [], task["title"], task["description"], before_submit=before_submit)

    account.site_id = binding["api_runtime"]["site_id"]
    blocks, cover = company_website_v2._description_to_content(task["description"])
    if not blocks:
        raise ValueError("正文转换后为空。")
    pieces = company_website_v2._build_payload(account, task["title"], company_website_v2._slugify(task["title"]),
                                               blocks, cover, settings.get("cms_category_id") or None)
    await before_submit()
    ok, data = await company_website_v2._create_article(account, binding["api_runtime"]["token"], pieces)
    return str(data["id"]) if ok and isinstance(data, dict) and data.get("id") else None


async def publish_browser(page, binding, task, before_submit, *, progress=None):
    platform = binding["platform"]
    options = task["options"]
    account = SimpleNamespace(name=binding["label"], id=binding["id"], **options)
    if platform == "company_website":
        account.website_url = binding["settings"]["website_url"]
    if platform == "reddit":
        account.website_url = options["reddit_target"]
    files = task["media_files"] if task["kind"] != "article" or platform == "wangyi" else []
    cover = task.get("cover", "")
    tags = task.get("tags", [])
    if task["kind"] == "image" and cover:
        files = [cover, *(path for path in files if path != cover)]
    args = (page, account, files, task["title"], task["description"])
    if platform == "douyin":
        if task["kind"] == "image":
            return await douyin.publish_image(*args, task["declaration"], before_submit, tags=tags)
        return await douyin.publish(*args, task["declaration"], before_submit, tags=tags, cover=cover)
    if platform == "xiaohongshu":
        home = urlsplit(page.url).netloc
        target = task["kind"]
        link = f"https://{home}/publish/publish?from=menu&target={target}"
        if target == "image":
            return await xiaohongshu.publish_image(*args, before_submit=before_submit, publish_url=link, tags=tags)
        return await xiaohongshu.publish_video(*args, before_submit, link, tags=tags, cover=cover, progress=progress)

    if platform not in PLATFORMS:
        raise ValueError("发布平台未注册。")
    publisher = import_module(f"publishers.{platform}")
    if platform == "csdn":
        return await publisher.publish(*args, options.get("csdn_keywords", ""), before_submit=before_submit)
    return await publisher.publish(*args, before_submit=before_submit)

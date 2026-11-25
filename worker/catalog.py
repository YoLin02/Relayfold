from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class Platform:
    label: str
    kinds: tuple[str, ...]
    home: str
    auth: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    identity: tuple[str, ...] = ()
    manage: str = ""
    mode: str = "browser"
    category: str = "国内"
    note: str = ""
    cookie_scopes: tuple[str, ...] = ()
    title_limit: int = 100

    @property
    def hosts(self):
        host = urlparse(self.home).hostname
        return {host, *self.aliases} if host else set(self.aliases)


V, I, A = "video", "image", "article"
PLATFORMS = {
    "douyin": Platform("抖音", (V, I), "https://creator.douyin.com/", ("sessionid", "sessionid_ss"),
                       identity=("uid_tt", "uid_tt_ss"), manage="/creator-micro/content/manage", title_limit=30),
    "xiaohongshu": Platform("小红书", (V, I), "https://creator.xiaohongshu.com/", ("web_session",),
                            ("creator.rednote.com",), manage="/new/note-manager", title_limit=20),
    "kuaishou": Platform("快手", (V,), "https://cp.kuaishou.com/", ("kuaishou.server.web_st", "kuaishou.server.web.at", "userId"),
                         ("www.kuaishou.com",), identity=("userId",), manage="/article/manage/video"),
    "shipinghao": Platform("微信视频号", (V,), "https://channels.weixin.qq.com/platform/", ("sessionid", "wxuin", "uin", "finder_uin", "exportkey"),
                           identity=("finder_uin", "wxuin", "uin"), manage="/platform/post/list"),
    "bilibili": Platform("哔哩哔哩", (V,), "https://member.bilibili.com/", ("SESSDATA",), identity=("DedeUserID",),
                         manage="/platform/upload-manager/article", note="投稿时选择平台分区和转载类型。", title_limit=80),
    "zhihu": Platform("知乎", (A,), "https://www.zhihu.com/creator", ("z_c0",), ("zhuanlan.zhihu.com",)),
    "toutiao": Platform("头条号", (A,), "https://mp.toutiao.com/profile_v4/index", ("sessionid", "sessionid_ss"),
                        identity=("uid_tt", "uid_tt_ss"), title_limit=28),
    "csdn": Platform("CSDN", (A,), "https://mp.csdn.net/", ("UserToken", "UserInfo"),
                     ("www.csdn.net", "passport.csdn.net", "blog.csdn.net"), identity=("UserName",)),
    "jianshu": Platform("简书", (A,), "https://www.jianshu.com/writer", ("remember_user_token", "_m7e_session", "_session_id"),
                        ("jianshu.com",)),
    "sohu": Platform("搜狐号", (A,), "https://mp.sohu.com/mpfe/v4/contentManagement/first/page", ("ppinf", "pprdig", "ppuid", "mp_session", "sessionid"),
                     identity=("ppuid",)),
    "wechat_mp": Platform("微信公众号", (A,), "https://mp.weixin.qq.com/", ("slave_sid", "slave_user", "bizuin"),
                          identity=("bizuin", "slave_user"), note="生成草稿，最终群发在公众号后台完成。"),
    "baijiahao": Platform("百家号", (A,), "https://baijiahao.baidu.com/", ("BDUSS", "BDUSS_BFESS")),
    "wangyi": Platform("网易号", (A,), "https://mp.163.com/", ("P_INFO", "S_INFO", "NTES_SESS", "NTES_P_SESS", "sessionId")),
    "tiktok": Platform("TikTok", (V,), "https://www.tiktok.com/tiktokstudio", ("sessionid", "sessionid_ss"),
                       identity=("uid_tt", "uid_tt_ss"), category="海外"),
    "youtube": Platform("YouTube", (V,), "https://studio.youtube.com/", ("LOGIN_INFO", "__Secure-3PSID", "__Secure-1PSID", "SID"),
                        ("www.youtube.com",), category="海外", cookie_scopes=("www.youtube.com",)),
    "facebook": Platform("Facebook", (V,), "https://www.facebook.com/", ("xs",), identity=("c_user",), category="海外"),
    "instagram": Platform("Instagram", (V,), "https://www.instagram.com/", ("sessionid",), identity=("ds_user_id",), category="海外"),
    "twitter": Platform("X / Twitter", (V,), "https://x.com/home", ("auth_token",), ("twitter.com",), identity=("twid",), category="海外"),
    "reddit": Platform("Reddit", (A,), "https://www.reddit.com/", ("reddit_session", "token_v2"),
                       ("reddit.com",), category="海外", note="每篇文章指定目标社区或个人主页。"),
    "medium": Platform("Medium", (A,), "https://medium.com/me/stories/public", ("sid", "uid"), identity=("uid",), category="海外"),
    "linkedin": Platform("LinkedIn", (A,), "https://www.linkedin.com/feed/", ("li_at",), category="海外"),
    "blogger": Platform("Blogger", (A,), "https://draft.blogger.com/home", ("SID", "__Secure-1PSID", "__Secure-3PSID", "BLOGGER_SSO"),
                        ("www.blogger.com", "blogger.com"), category="海外", cookie_scopes=("www.google.com",)),
    "quora": Platform("Quora", (A,), "https://www.quora.com/", ("m-b", "m-s", "m-uid"), identity=("m-uid",), category="海外"),
    "devto": Platform("DEV Community", (A,), "https://dev.to/dashboard", mode="api", category="海外", note="需要 DEV API Key。"),
    "company_website": Platform("企业官网 · 网页 CMS", (A,), "", ("PHPSESSID", "pbootcms", "sessionid"),
                                mode="custom_browser", category="自定义", note="填写 PbootCMS 文章管理页的 HTTPS 地址。"),
    "company_website_v2": Platform("企业官网 · API", (A,), "", mode="api", category="自定义",
                                   note="填写自己的 CMS API、站点域名和账号凭据。"),
}


def public_catalog():
    return [{"id": key, "label": spec.label, "kinds": list(spec.kinds), "category": spec.category,
             "mode": spec.mode, "note": spec.note, "title_limit": spec.title_limit} for key, spec in PLATFORMS.items()]

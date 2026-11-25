<p align="center">
  <img src="src/assets/relayfold-mark.png" width="96" height="96" alt="Relayfold 图标">
</p>

<h1 align="center">Relayfold</h1>
<p align="center"><strong>Windows 本地多账号内容分发工作台</strong></p>

<p align="center">
  <a href="https://github.com/YoLin02/Relayfold/tree/v0.0.1"><img alt="版本 v0.0.1" src="https://img.shields.io/badge/version-v0.0.1-2563eb?style=flat"></a>
  <img alt="Windows x64" src="https://img.shields.io/badge/desktop-Windows%20x64-0078d4?style=flat">
  <img alt="Electron 和 React" src="https://img.shields.io/badge/UI-Electron%20%2B%20React-0891b2?style=flat">
  <img alt="Python Worker" src="https://img.shields.io/badge/worker-Python-3776ab?style=flat">
  <a href="#平台支持与验证"><img alt="26 个平台入口" src="https://img.shields.io/badge/targets-26-6554c0?style=flat"></a>
  <a href="#平台支持与验证"><img alt="2 个平台已验证真实视频提交" src="https://img.shields.io/badge/live%20verified-2%20platforms-2e8b57?style=flat"></a>
</p>

<p align="center">
  <a href="#主要功能">主要功能</a> ·
  <a href="#平台支持与验证">平台支持与验证</a> ·
  <a href="#从源码启动">从源码启动</a> ·
  <a href="#技术栈">技术栈</a>
</p>

Relayfold 把账号绑定、素材编辑、差异化群发和发布记录放在一个桌面应用里。选一次素材，勾选多个平台账号，按需修改各平台的内容，最后统一核对并提交。账号会话、发布队列和历史保存在本机。

## 主要功能

- **多账号与发布组**。常规组每个平台可绑定一个账号。自定义组可添加同一平台的多个账号，各自保存登录态。入队后切组，任务继续使用创建时选定的账号。
- **视频、图文和文章群发**。抖音和小红书可分别覆盖通用标题、正文、标签和封面。确认页逐一核对目标账号和最终内容。
- **定时发布与托盘常驻**。预约支持改期和取消。关窗后继续从托盘运行，电脑须保持唤醒并联网。预约时间是开始处理的时间，作品公开时间取决于上传和审核。
- **发布记录与诊断**。按日期筛选、查看回执或诊断、删除本地记录。平台确认收稿时显示「已提交」，提交结果不明确时显示「待核对」。
- **工作台设置**。可切换国内或国外平台、主题色，使用 `Ctrl+K` 搜索账号、发布组和页面。

## 平台支持与验证

下表列出源码中可选的 **26 个发布入口**。真实验证按内容类型记录，平台回执表示确认提交，公开状态以平台审核为准。

| 范围 | 平台 | 内容 | 验证 |
| --- | --- | --- | --- |
| 国内 | 抖音 | 视频、图文 | **视频 · 真实提交已验证**；图文 · 模拟表单已验证 |
| 国内 | 小红书 | 视频、图文 | **视频 · 真实提交已验证**；图文 · 模拟表单已验证 |
| 国内 | 快手 | 视频 | 已接入 · 待真实验证 |
| 国内 | 微信视频号 | 视频 | 已接入 · 待真实验证 |
| 国内 | 哔哩哔哩 | 视频 | 已接入 · 待真实验证 |
| 国内 | 知乎 | 文章 | 已接入 · 待真实验证 |
| 国内 | 头条号 | 文章 | 已接入 · 待真实验证 |
| 国内 | CSDN | 文章 | 已接入 · 待真实验证 |
| 国内 | 简书 | 文章 | 已接入 · 待真实验证 |
| 国内 | 搜狐号 | 文章 | 已接入 · 待真实验证 |
| 国内 | 微信公众号 | 文章草稿 | 已接入 · 待真实验证 |
| 国内 | 百家号 | 文章 | 已接入 · 待真实验证 |
| 国内 | 网易号 | 文章 | 已接入 · 待真实验证 |
| 国外 | TikTok | 视频 | 已接入 · 待真实验证 |
| 国外 | YouTube | 视频 | 已接入 · 待真实验证 |
| 国外 | Facebook | 视频 | 已接入 · 待真实验证 |
| 国外 | Instagram | 视频 | 已接入 · 待真实验证 |
| 国外 | X / Twitter | 视频 | 已接入 · 待真实验证 |
| 国外 | Reddit | 文章 | 已接入 · 待真实验证 |
| 国外 | Medium | 文章 | 已接入 · 待真实验证 |
| 国外 | LinkedIn | 文章 | 已接入 · 待真实验证 |
| 国外 | Blogger | 文章 | 已接入 · 待真实验证 |
| 国外 | Quora | 文章 | 已接入 · 待真实验证 |
| 国外 | DEV Community | 文章 | 已接入 · 待真实验证 |
| 自定义 | 企业官网 · 网页 CMS | 文章 | 已接入 · 待真实验证 |
| 自定义 | 企业官网 · API | 文章 | 已接入 · 待真实验证 |

微信公众号任务写入草稿，最终群发在公众号后台完成。自定义官网入口需配置自己的 CMS。

## 从源码启动

需要 Windows x64、Node.js 22.12+、Python 3.11+ 和 Google Chrome。

```powershell
git clone https://github.com/YoLin02/Relayfold.git
cd Relayfold
npm ci
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r worker\requirements.txt
$env:ZT_PYTHON = (Resolve-Path '.\.venv\Scripts\python.exe').Path
npm run build
npm start
```

开发时可将 `ZT_PUBLISHER_DATA_DIR` 指向独立目录，隔离浏览器会话与测试发布记录。Windows x64 打包版可通过本机环境变量 `RELAYFOLD_UPDATE_SSH_HOST`、`RELAYFOLD_UPDATE_SSH_DIRECTORY` 和 `RELAYFOLD_UPDATE_PUBLIC_KEY` 启用签名更新。

运行本地测试

```powershell
& $env:ZT_PYTHON -B -m unittest discover -s tests -p '*_test.py'
npm run test:e2e
```

## 技术栈

| 模块 | 实现 |
| --- | --- |
| `electron/` | Electron、IPC、Windows 托盘和本地 Worker 管理 |
| `src/` | React 19、TypeScript、Vite、Tailwind CSS v4、shadcn/ui v4、Radix UI、Lucide |
| `worker/` | Python、Playwright、Patchright 1.64.4，按平台封装网页流程或 API |
| 本地数据 | SQLite 记录发布组、任务和回执。浏览器会话按绑定账号隔离，登录态备份使用 Windows DPAPI |

## 规划

**评论收件箱**处于调研阶段。计划先聚合抖音和小红书自有作品的评论，按账号和作品筛选，以原作品所属账号手动回复，并核对平台回执。

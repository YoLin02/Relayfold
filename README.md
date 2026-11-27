<p align="center">
  <img src="src/assets/relayfold-mark.png" width="76" height="76" alt="Relayfold 图标">
</p>

<h1 align="center">Relayfold</h1>
<p align="center"><strong>面向剪辑师和内容团队的本地视频制作与多平台发布工作台</strong></p>

<p align="center">
  <a href="https://github.com/YoLin02/Relayfold/tree/main"><img alt="源码版本 0.0.3" src="https://img.shields.io/badge/源码-v0.0.3-2563eb?style=flat"></a>
  <img alt="Windows x64" src="https://img.shields.io/badge/Windows-x64-475569?style=flat">
  <img alt="本地 Whisper 和 Qwen3-TTS" src="https://img.shields.io/badge/本地推理-Whisper%20%2B%20Qwen3--TTS-0891b2?style=flat">
  <a href="#平台支持与验证"><img alt="24 个预设平台及 2 种自定义 CMS 接入" src="https://img.shields.io/badge/发布适配-24%20预设%20%2B%202%20CMS-475569?style=flat"></a>
</p>

<p align="center">
  <a href="#剪辑工作流">剪辑工作流</a> ·
  <a href="#多平台一键发布">多平台一键发布</a> ·
  <a href="#界面预览">界面预览</a> ·
  <a href="#安装与运行">安装与运行</a> ·
  <a href="#平台支持与验证">平台支持与验证</a>
</p>

Relayfold 把**素材获取、字幕与 Word 对稿、本地声音制作、成片导出、多平台一键发布**放进同一个 Windows 应用。下载 B 站视频或导入本地素材，校对字幕、克隆并复用音色，导出 SRT、WAV 或烧录字幕的 MP4。成片可以直接进入发布草稿，也可以从本地选择已有素材，统一准备视频、图文或文章。选好账号并确认后，Relayfold 会为每个目标建立发布任务，并跟踪回执。

![Relayfold 工作台，左侧为独立工具入口，右侧为当前发布组的账号状态、任务趋势和最近发布](docs/screenshots/workbench.png)

## 剪辑工作流

| 入口 | 可完成的操作 | 输出与交接 |
| --- | --- | --- |
| **视频下载** | 解析 B 站视频链接或分享短链，选择清晰度，查看进度或重试。 | 打开本地文件夹，或将所选素材直接送去提取字幕。 |
| **提取字幕** | 导入本地视频，提取内封文字字幕或读取同名字幕文件。也可用 Whisper 从音轨识别，适用于无文字轨或烧录字幕的视频。 | 编辑时间和文本，点击台词定位预览，保存并导出 SRT。 |
| **脚本核对** | 导入 Word `.docx`，对照原稿和视频字幕。差异可以试听、标记为已核对，或跳到对应的时间轴条目修改。 | 保存修改后重新核对，继续使用当前素材及字幕版本。 |
| **配音与音色** | 按需下载 Qwen3‑TTS 0.6B 或 1.7B Base，或选用已有模型。可截取参考录音、自动识别并校对原文，克隆、保存和复用音色。 | 试听并导出 24 kHz WAV。音色库支持重命名和导入兼容的旧音色。 |
| **合成字幕** | 为所选视频加载已保存字幕或独立 SRT，预览字幕合成效果。 | 输出新的硬字幕 MP4，可继续在剪辑软件使用或带入发布草稿。 |

字幕和配音可作为独立素材交给剪辑软件。生成的 WAV 可在剪辑软件内放回音轨、对齐和混音。字幕识别、模型推理和媒体处理在本机运行，素材、音色、账号会话和任务记录保存在本机。

## 界面预览

以下为 **0.0.3** 运行界面，账号、任务和媒体均为演示数据。

| 脚本与字幕核对 | 本地配音与音色库 |
| --- | --- |
| [![Word 原稿核对与视频字幕预览](docs/screenshots/word-script-review.png)](docs/screenshots/word-script-review.png) | [![模型选择、参考录音、克隆音色和生成配音](docs/screenshots/voice-workspace.png)](docs/screenshots/voice-workspace.png) |

| 字幕成片 | 群发前核对 |
| --- | --- |
| [![预览并生成烧录字幕的视频](docs/screenshots/subtitle-synthesis.png)](docs/screenshots/subtitle-synthesis.png) | [![核对各平台的最终文案和目标账号](docs/screenshots/publish-review.png)](docs/screenshots/publish-review.png) |

[视频下载](docs/screenshots/video-download.png) · [发布草稿](docs/screenshots/publish-workspace.png) · [平台账号](docs/screenshots/platform-accounts.png) · [消息与评论](docs/screenshots/xiaohongshu-comments.png)

## 多平台一键发布

「新建发布」支持单账号提交和多账号群发，也可接收「合成字幕」生成的成片。

1. **绑定目标账号。** 在「平台账号」中登录并确认要使用的账号。常规组每个平台一个账号，自定义组支持同一平台多个账号。目标列表按当前发布组、平台范围和内容类型筛选，官网接入可用于国内和国外范围。
2. **准备一份内容。** 可选本地 MP4 或 MOV 视频、1–18 张 JPG／PNG／WebP 图片，或填写长文章正文。抖音和小红书支持各自的标题、正文、标签和封面。根据目标还可填写平台专用项，例如哔哩哔哩分区及稿件类型、YouTube 可见范围和儿童内容声明，以及 Reddit 目标社区。
3. **核对后提交。** 「核对并群发」会并排显示目标账号、共用素材和各平台最终文案。可立即提交，也可预约任务开始时间，已预约的任务支持改期和取消。
4. **跟踪回执和诊断。** 每个目标都有独立记录，包含提交状态、作品回执或诊断。确认提交后显示「已提交」，结果不明确时显示「待核对」，可到对应平台确认后再决定是否重试。入队后切换发布组，任务继续使用原定账号。

![发布草稿，左侧编辑通用及分平台文案，右侧选择发布目标](docs/screenshots/publish-workspace.png)

队列在 Windows 托盘中继续运行，定时发布要求电脑保持唤醒并联网。预约时间是任务开始处理的时间，作品公开时间取决于上传和平台审核。平台账号可检查登录、重新绑定或删除绑定，发布记录可按日期筛选并查看回执和诊断。

### 工作台与消息

- **工作台**显示当前发布组的账号状态、待执行任务和最近发布。切换 7 天或 30 天趋势后，可按日查看任务状态分布。左下角的头像菜单可切换和管理发布组，切换时保留当前剪辑工具、所选视频和字幕编辑。
- **消息与评论**提供小红书收到评论、完整评论和回复核对。抖音提供官方评论及私信入口，支持保存本地私信草稿。

## 安装与运行

**0.0.3 源码版本**适用于 Windows x64。需要 Node.js 22.12+ 和 Python 3.11+。视频与音频工具需要系统 PATH 中的 FFmpeg 和 FFprobe，网页发布需要 Google Chrome。

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

**本地配音环境**面向 Windows x64 和 NVIDIA CUDA。可在「剪辑工具 → 配音与音色」按需安装，也可选用已有 Qwen3‑TTS 环境的 `python.exe`。自动安装需要至少 12 GiB 可用空间，0.6B 和 1.7B 模型分别约 2.52 GB 和 4.54 GB，另计。模型下载支持文件校验和续传。参考录音可选取 3 至 30 秒的单人片段。

**已有便携包**为早期的 0.0.2 预览版。下载后完整解压，再运行 `Relayfold.exe`。上方界面对应 0.0.3 源码。 [下载 0.0.2 Windows x64 便携预览包](https://erp.gzsenhan.com:18443/relayfold/Relayfold-0.0.2-Windows-x64-20261127.zip) · [SHA-256 校验文件](https://erp.gzsenhan.com:18443/relayfold/Relayfold-0.0.2-Windows-x64-20261127.zip.sha256) · [历史 GitHub Releases](https://github.com/YoLin02/Relayfold/releases)

## 平台支持与验证

仓库包含 **24 个预设平台和 2 种自定义官网接入**。以下内容类型和状态对应当前源码。「待实测」表示发布适配已接入，尚待真实账号提交验收。视频下载入口支持 B 站。

### 国内平台

| 平台 | 内容类型 | 验证状态或使用说明 |
| --- | --- | --- |
| 抖音 | 视频、图文 | 视频已验证真实提交，图文已验证模拟表单。发布前选择作品声明。 |
| 小红书 | 视频、图文 | 视频已验证真实提交，图文已验证模拟表单。 |
| 快手 | 视频 | 待实测。 |
| 微信视频号 | 视频 | 待实测。 |
| 哔哩哔哩 | 视频 | 待实测。需填写分区、稿件类型及标签，转载稿件还需来源。 |
| 知乎 | 文章 | 待实测。 |
| 头条号 | 文章 | 待实测。 |
| CSDN | 文章 | 待实测。支持填写平台关键词。 |
| 简书 | 文章 | 待实测。 |
| 搜狐号 | 文章 | 待实测。 |
| 微信公众号 | 文章草稿 | 待实测。写入草稿箱，最终群发在公众号后台完成。 |
| 百家号 | 文章 | 待实测。 |
| 网易号 | 文章 | 待实测。支持使用文章配图。 |

### 海外平台

| 平台 | 内容类型 | 验证状态或使用说明 |
| --- | --- | --- |
| TikTok | 视频 | 待实测。 |
| YouTube | 视频 | 待实测。需设置视频可见范围和儿童内容声明。 |
| Facebook | 视频 | 待实测。 |
| Instagram | 视频 | 待实测。 |
| X / Twitter | 视频 | 待实测。 |
| Reddit | 文章 | 待实测。需指定目标社区或个人主页。 |
| Medium | 文章 | 待实测。 |
| LinkedIn | 文章 | 待实测。 |
| Blogger | 文章 | 待实测。 |
| Quora | 文章 | 待实测。 |
| DEV Community | 文章 | 待实测。通过 DEV API Key 接入。 |

### 自定义官网

| 接入方式 | 内容类型 | 验证状态或使用说明 |
| --- | --- | --- |
| 企业官网 · 网页 CMS | 文章 | 待实测。配置自有 PbootCMS 的 HTTPS 文章管理页，从浏览器登录。 |
| 企业官网 · API | 文章 | 待实测。配置自有 CMS API、站点和账号凭据。 |

发布适配器包含在仓库内，自有 CMS 和 DEV 凭据由使用者在本机填写并加密保存。小红书的笔记同步、评论读取和回复提交有真实验证记录。桌面隔离测试覆盖发送期间切组、原账号隔离和待核对处理。 [发布适配器源码](worker/publishers/)

## 开发与测试

界面使用 Electron、React、TypeScript 和 shadcn/ui。本地 Worker 使用 Python 和 SQLite，媒体处理基于 yt-dlp、FFmpeg、FFprobe、whisper.cpp 和 Qwen3‑TTS，网页发布通过 Playwright 或 Patchright 运行。浏览器会话按绑定账号隔离，支持 Windows DPAPI 登录态备份。依赖来源见 [THIRD_PARTY.md](THIRD_PARTY.md)。

| 目录 | 项目模块 |
| --- | --- |
| `src/` | 工作台、剪辑与配音工具、账号管理和发布界面 |
| `electron/` | 桌面窗口、托盘、IPC 和本地 Worker 管理 |
| `worker/` | 下载、字幕处理、本地配音、账号会话与发布队列 |
| `worker/publishers/` | 各平台的网页发布和 API 适配器 |
| `tests/` | 媒体、发布队列、账号隔离和桌面端回归测试 |

开发和演示时可将 `ZT_PUBLISHER_DATA_DIR` 指向独立目录，用单独的素材、浏览器会话和任务记录。

```powershell
npm run build
& $env:ZT_PYTHON -B -m unittest discover -s tests -p '*_test.py'
npm run test:e2e
```

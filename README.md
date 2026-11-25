<p align="center">
  <img src="assets/relayfold-mark.png" width="92" height="92" alt="Relayfold 图标">
</p>

<h1 align="center">Relayfold</h1>

<p align="center">面向 Windows 的本地多账号内容分发工作台</p>
<p align="center"><strong>v0.0.1</strong> · Windows · Electron + React + Python</p>

Relayfold 把账号绑定、素材编辑、差异化群发和发布记录放在一个桌面应用里。创作者可在同一个工作台管理抖音、小红书等平台的多个账号，上传一次素材，按平台调整文案，核对目标后统一提交。

## 已有功能

| 功能 | 使用方式 |
| --- | --- |
| 多账号管理 | 常规组每个平台可绑定一个账号。自定义组可添加同一平台的多个账号，每个账号独立保存登录态。 |
| 差异化群发 | 选择一次素材，在通用模板填标题、正文、标签和封面，再为抖音、小红书单独覆盖需要修改的字段。发布前可核对各目标的最终内容。 |
| 视频、图文与文章 | 支持视频、多图和长文章，按内容类型筛选可用平台。国内平台和国外平台可在设置中切换。微信公众号适配器将文章保存为平台草稿。 |
| 定时发布 | 预约时固定当次素材、内容和目标账号。进入 Windows 托盘后可继续运行，待执行任务支持改期与取消。 |
| 发布记录 | 按日期筛选、查看任务状态和诊断、删除本地记录。有作品回执时保留回执，提交结果不明确时标为「待核对」。 |

定时任务需要电脑保持唤醒、联网，且 Relayfold 正在运行。预约时间是本机开始处理的时间，作品公开时间取决于平台上传与审核。

## 技术栈与实现

| 模块 | 技术与实现 |
| --- | --- |
| Windows 桌面 | Electron 管理窗口、系统托盘和本地 Worker。渲染进程通过 preload 暴露的 IPC 接口调用桌面能力。 |
| 前端 | React 19、TypeScript、Vite、Tailwind CSS v4、shadcn/ui v4（Radix Nova + Neutral）和 Lucide。 |
| 发布 Worker | Python 3.11+ 按平台适配发布流程。网页平台使用 Playwright，抖音视频适配使用 Patchright 1.64.4。部分平台使用各自的 API。 |
| 本地存储 | SQLite 保存账号组、绑定、任务和回执。浏览器会话按账号绑定隔离，登录态备份由 Windows DPAPI 保护。 |

确认发布时，Worker 把具体账号绑定 ID 和已核对的内容写入任务。切组只改变当前工作台的视图，排队、定时或进行中的任务继续使用入队时选定的账号。回执用于关联平台作品，也能为后续的评论收件箱提供作品入口。

## 规划中的评论收件箱

首期覆盖已绑定账号在抖音和小红书发布的自有作品。按账号组、平台、具体账号和作品筛选评论，选中一条后在应用内以作品所属账号手动回复。

- 抖音优先验证官方视频评论读取与回复权限。
- 小红书验证现有扫码绑定在网页端读取和回复自有笔记评论的能力。
- 仅在收到平台确认或回读到回复后标为「已回复」。结果不明确时保留「待核对」。

## 上游参考

- 抖音视频上传流程参考 [social-auto-upload](https://github.com/dreammis/social-auto-upload)。
- 桌面进程边界和发布结果确认流程参考 [MultiPublish](https://github.com/whut09/MultiPublish)。
- 小红书评论适配调研参考 [xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp)。

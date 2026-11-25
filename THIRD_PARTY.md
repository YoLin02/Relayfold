# 代码来源

- 界面组件使用 [shadcn/ui](https://github.com/shadcn-ui/ui) v4 官方 registry 的 Radix Nova 源码与 Neutral 主题。图标占位符在导入时转换为 Lucide 图标，原项目采用 MIT 许可证。
- Command 搜索底层使用 [cmdk](https://github.com/pacocoursey/cmdk)，附有 MIT 许可证。
- 应用内置 [Geist](https://fontsource.org/fonts/geist) 和 [Noto Sans SC](https://fontsource.org/fonts/noto-sans-sc) 可变字体，随包附带 SIL Open Font License 1.1。
- 已有平台发布器抽取自用户本地 `matrix-browser-worker`，以该源码的使用条件为准。B 站适配使用创作中心网页。
- 桌面进程边界和结果确认流程参考 [MultiPublish](https://github.com/whut09/MultiPublish)，平台扩展调研参考 [social-auto-upload](https://github.com/dreammis/social-auto-upload)。
- 抖音图文入口、抖音与小红书的封面和话题交互参考 [social-auto-upload 对应版本](https://github.com/dreammis/social-auto-upload/tree/409d4fdd33f3eb0d946310af93633ddb5eebe1d5/uploader)，采用本项目现有的账号校验和单次提交机制。
- 抖音视频上传步骤改编自 [social-auto-upload · DouYinVideo](https://github.com/dreammis/social-auto-upload/blob/409d4fdd33f3eb0d946310af93633ddb5eebe1d5/uploader/douyin_uploader/main.py)，随附 MIT 许可证。视频发布使用 Patchright 1.64.4，包内包含该依赖的许可证。
- Windows 便携包中的 Electron、Python 和 Playwright 随附上游许可证文件。

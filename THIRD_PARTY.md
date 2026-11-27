# 代码来源

- 界面组件使用 [shadcn/ui](https://github.com/shadcn-ui/ui) v4 官方 registry 的 Radix Nova 源码与 Neutral 主题。图标占位符在导入时转换为 Lucide 图标，原项目采用 MIT 许可证。
- Command 搜索底层使用 [cmdk](https://github.com/pacocoursey/cmdk)，附有 MIT 许可证。
- 应用内置 [Geist](https://fontsource.org/fonts/geist) 和 [Noto Sans SC](https://fontsource.org/fonts/noto-sans-sc) 可变字体，随包附带 SIL Open Font License 1.1。
- 已有平台发布器抽取自用户本地 `matrix-browser-worker`，以该源码的使用条件为准。B 站适配使用创作中心网页。
- 桌面进程边界和结果确认流程参考 [MultiPublish](https://github.com/whut09/MultiPublish)，平台扩展调研参考 [social-auto-upload](https://github.com/dreammis/social-auto-upload)。
- 抖音图文入口、抖音与小红书的封面和话题交互参考 [social-auto-upload 对应版本](https://github.com/dreammis/social-auto-upload/tree/409d4fdd33f3eb0d946310af93633ddb5eebe1d5/uploader)，采用本项目现有的账号校验和单次提交机制。
- 抖音视频上传步骤改编自 [social-auto-upload · DouYinVideo](https://github.com/dreammis/social-auto-upload/blob/409d4fdd33f3eb0d946310af93633ddb5eebe1d5/uploader/douyin_uploader/main.py)，随附 MIT 许可证。视频发布使用 Patchright 1.64.4，包内包含该依赖的许可证。
- Windows 便携包中的 Electron、Python 和 Playwright 随附上游许可证文件。
- 素材解析和下载使用 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 的 PyPI wheel（Unlicense），许可证随该依赖提供。媒体探测和字幕转换调用系统安装的 FFprobe 与 FFmpeg。
- 字幕操作流程参考 [VideoCaptioner](https://github.com/WEIFENG2333/VideoCaptioner/blob/master/docs/guide/getting-started.md)。本地识别使用 [whisper.cpp v1.8.3](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.8.3)、[多语言 Whisper Small](https://huggingface.co/ggerganov/whisper.cpp) 和 [Silero VAD](https://github.com/snakers4/silero-vad)，许可证为 MIT。应用首次使用时可按校验值下载模型与 Windows x64 运行组件。
- 本地配音使用 [Qwen3‑TTS](https://github.com/QwenLM/Qwen3-TTS) 和官方 0.6B、1.7B Base 权重，许可证为 Apache-2.0。模型从 Qwen 官方发布的魔搭或 Hugging Face 仓库按需下载。独立运行环境使用 [uv](https://github.com/astral-sh/uv) 和 [PyTorch](https://pytorch.org/)，相关许可证随上游下载的组件提供。

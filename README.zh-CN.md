# Video2Knowledge

简体中文 | [English](README.md)

Video2Knowledge 是一套本地优先的处理流程，可将哔哩哔哩视频整理成个人可搜索的知识库。它会逐个下载视频，通过 MLX Audio 上的 Whisper Large V3 Turbo 转录音频，使用大语言模型丰富转录内容，并生成 Markdown、LRC 和 JSON 时间轴文件。它还可以将 Markdown 转换回同步语音，并导出兼容 Apple Music 的 M4A 文件。

> **项目状态：** Alpha。核心流程已可在 Apple 芯片 Mac 上运行，但 API 和配置方式在首个稳定版本发布前仍可能发生变化。

## 功能

- 接收哔哩哔哩视频链接，或在本地网页界面中搜索视频和创作者。
- 使用 [`bili-dl`](https://github.com/war-ning/bili-dl) 下载需要登录或充电专属的内容；未配置 `bili-dl` 时回退到 `yt-dlp`。
- 默认复用已下载的媒体文件，也支持明确指定强制刷新。
- 通过兼容 OpenAI API 的 MLX Audio 服务在本地完成转录。
- 生成核心摘要、延伸洞察、建议和后续问题。
- 保存便于阅读的 Markdown、同步歌词 LRC 和机器可读的 JSON 时间轴。
- 将 Markdown 转换为语音，并可选封装为适用于 Apple Music 的 AAC/M4A 文件。
- 串行执行下载任务，避免没有哔哩哔哩大会员的账号并行启动多个任务。

Video2Knowledge 不会绕过平台授权、充电内容的访问控制或 DRM。请仅下载和保留你有权使用的内容。

## 环境要求

- 搭载 Apple 芯片的 macOS
- Python 3.11 或 3.12
- [Git](https://git-scm.com/)
- 用于导出 Apple Music M4A 的 [FFmpeg](https://ffmpeg.org/)
- 用于语音转录和语音合成的 [MLX Audio](https://github.com/Blaizzy/mlx-audio) 服务
- 已登录的 Codex CLI（默认大语言模型后端），或兼容 OpenAI API 的本地服务，例如 Ollama

## 安装

### 推荐方式：uv

```bash
git clone <你的仓库地址> video2knowledge
cd video2knowledge
git clone https://github.com/war-ning/bili-dl vendor/bili-dl

uv sync --extra bilibili --extra audio --extra dev
source .venv/bin/activate
v2k init
```

### Conda 和 pip

```bash
git clone <你的仓库地址> video2knowledge
cd video2knowledge
git clone https://github.com/war-ning/bili-dl vendor/bili-dl

conda create -n video2knowledge python=3.12
conda activate video2knowledge
python -m pip install -e ".[bilibili,audio,dev]"
v2k init
```

可以使用 `pip install -e ".[mlx]"` 将 MLX Audio 服务安装到同一环境，也可以在单独的环境中运行。首次启动时会下载配置的模型：

```bash
mlx_audio.server --host 127.0.0.1 --port 8000
```

默认数据目录为启动 `v2k` 时所在目录下的 `./video2knowledge-data`。如需使用其他位置，请在执行命令前设置 `V2K_DATA_DIR`。运行时数据、凭据、数据库和下载的媒体文件都不应提交到版本库。

## 配置

运行 `v2k init`，然后编辑 `./video2knowledge-data/config.json`。完整示例见 [`config.example.json`](config.example.json)，所有设置的说明见 [`docs/configuration.md`](docs/configuration.md)。

至少需要设置本地 `bili-dl` 代码目录的绝对路径：

```json
{
  "bili_dl_dir": "/absolute/path/to/video2knowledge/vendor/bili-dl"
}
```

数据目录内部的路径可以使用相对路径。`v2k init` 会为知识库、媒体目录、数据库和 Cookie 文件写入可移植的相对路径。

## 登录哔哩哔哩

如需访问充电专属内容，请使用 `bili-dl` 的二维码扫描登录：

```bash
v2k login
```

使用哔哩哔哩手机客户端扫描二维码并确认登录。该命令会将 `bili-dl` 凭据保存在其专用数据目录中，并以 `0600` 权限写入 Netscape 格式的 Cookie 文件。Cookie 内容不会被打印。也可以使用备用流程：

```bash
v2k qr-login
```

## 使用方法

启动网页界面：

```bash
v2k serve
```

打开 <http://127.0.0.1:8765>，粘贴哔哩哔哩视频链接或搜索视频。仅在需要刷新本地副本时启用 **Force re-download cached video（强制重新下载缓存视频）**。

**Runtime Settings（运行时设置）** 面板可分别配置下载路径和 Markdown 导出路径、选择摘要后端（默认为 Codex CLI），以及启动、监控或停止本地 MLX Audio 服务。

已完成的队列项目会显示生成文件和源媒体的路径。你可以只从队列中移除已结束的任务并保留本地文件，也可以在明确确认后连同相关本地文件一起删除。每个生成的文件还可以使用 macOS 默认应用打开，或直接在访达中显示。文件操作按钮会在鼠标悬停时展开，并在指针和键盘焦点都离开当前文件区域后收起。

通过命令行搜索或处理视频链接：

```bash
v2k search "机器学习"
v2k process "https://www.bilibili.com/video/BV..."
v2k process "https://www.bilibili.com/video/BV..." --force-refresh
```

将 Markdown 转换为同步语音：

```bash
v2k speak notes.md --title "知识音频" --author "作者"
```

Apple Music 会导入带有普通内嵌歌词的 M4A 文件。由于 Apple Music 没有稳定公开的同步歌词导入格式，精确的时间同步信息会保存在同名的 LRC 和 JSON 文件中。

## 数据目录结构

```text
./video2knowledge-data/
├── config.json
├── bilibili-cookies.txt
├── library.db
├── media/
└── library/
    └── 创作者_内容标题_视频ID/
        ├── 创作者_内容标题_视频ID.md
        ├── 创作者_内容标题_视频ID.lrc
        └── 创作者_内容标题_视频ID.json
```

Markdown 是内容的唯一事实来源。目录名和文件名统一使用 `创作者_内容标题_视频ID` 格式，并会针对 macOS 和 Windows 进行字符清理。

## 架构

应用通过小型接口将视频来源、语音引擎、内容增强后端、存储和导出器彼此分离。模块结构和扩展点见 [`docs/architecture.md`](docs/architecture.md)。

## 开发

```bash
uv sync --extra bilibili --extra audio --extra dev
pytest
ruff check .
ruff format --check .
python -m build
```

贡献约定见 [`CONTRIBUTING.md`](CONTRIBUTING.md)，凭据处理和漏洞报告方式见 [`SECURITY.md`](SECURITY.md)。

## 已知限制

- 哔哩哔哩的风控系统可能会拦截公开搜索请求。
- 对充电内容的识别依赖元数据提示；登录账号是否可以下载某个视频，最终以哔哩哔哩的判定为准。
- 当前网页界面在本地主机上运行且没有用户账号，不适合暴露到公网。
- 任务在内存中串行排队；服务重启后不会恢复中断的任务。

## 许可证

项目尚未选择开源许可证。发布仓库前请添加 `LICENSE` 文件；在此之前，项目适用常规版权限制。

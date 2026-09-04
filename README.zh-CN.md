# Video2Knowledge

简体中文 | [English](README.md)

Video2Knowledge 是一套本地优先的处理流程，可将哔哩哔哩视频整理成个人可搜索的知识库。它最多并发下载三个视频，并将每个已完成的下载立即送入 MLX Audio 转录和大语言模型内容增强流水线，随后生成 Markdown、LRC 和 JSON 时间轴文件。它还可以将 Markdown 转换回同步语音，并导出兼容 Apple Music 的 M4A 文件。

> **项目状态：** Alpha。核心流程已可在 Apple 芯片 Mac 上运行，但 API 和配置方式在首个稳定版本发布前仍可能发生变化。

## Feature：已实现功能

### 视频来源与下载

- ✅ 接收哔哩哔哩视频链接，或在本地网页界面中搜索视频和创作者。
- ✅ 使用 [`bili-dl`](https://github.com/war-ning/bili-dl) 下载需要登录或充电专属的内容；未配置 `bili-dl` 时回退到 `yt-dlp`。
- ✅ 支持按创作者批量导入视频，最多并发下载三个视频，并独立流水线化转录与大语言模型内容增强。
- ✅ 若同一视频的媒体、转录、摘要和导出文件均完整存在，默认直接复用全部结果；也支持明确指定强制刷新整个处理流程。
- ✅ 将每个源音频及其转录产物保存在独立完整的视频资料包中，方便单独移动、备份和删除。

### 模型与接口

- ✅ 通过接口隔离视频来源、语音引擎和大语言模型内容增强后端，可独立替换各类实现。
- ✅ 通过兼容 OpenAI API 的 MLX Audio 服务在本地完成转录。
- ✅ 生成核心摘要、延伸洞察、建议和后续问题。
- ✅ 支持 Codex CLI 以及 Ollama 等兼容 OpenAI API 的大语言模型后端。
- ✅ 处理前检查所需运行时服务，并允许在网页界面中启动、监控和停止本地 MLX Audio 服务。

### 语音与媒体

- ✅ 将可编辑 Markdown 笔记保留在视频资料包根目录，并把源音频、同步歌词 LRC 和机器可读的 JSON 时间轴统一放入 `assets/`。
- ✅ 将 Markdown 转换为语音，并可选封装为适用于 Apple Music 的 AAC/M4A 文件。

### 知识与任务管理

- ✅ 按创作者和合集组织知识库，并在导出的知识文档中保留合集上下文。
- ✅ 在 SQLite 中持久化下载历史和请求进度，支持按创作者、合集、状态和创建日期多选筛选队列，
  合集选项会跟随所选创作者动态变化，并将合集和独立视频归入带头像的可折叠创作者层级；旧历史
  记录缺失的创作者头像会自动补全。
- ✅ 支持暂停和恢复排队任务、单个或批量重启失败任务，以及清理过期的终态任务记录。
- ✅ 提供交互式队列文件操作，可打开或在访达中显示生成文件，并可选择删除关联的本地数据。

Video2Knowledge 不会绕过平台授权、充电内容的访问控制或 DRM。请仅下载和保留你有权使用的内容。

## TODO：待办事项

### 视频来源与下载

- [ ] 提升哔哩哔哩公开搜索触发风控时的可恢复性。
- [ ] 支持更多视频来源。

### 模型与接口

- [ ] 增加可配置的非 MLX 语音后端。
- [ ] 在首个非 Alpha 版本前稳定公开配置与 API。

### 语音与媒体

- [ ] 支持多人访谈类语音的转录、说话者识别与观点提取。
- [ ] 扩展语音合成与媒体导出的配置能力。

### 知识与任务管理

- [ ] 服务重启后自动恢复被中断的处理中任务。
- [ ] 在支持非本机网页部署前加入身份认证和权限控制。
- [ ] 在首个非 Alpha 版本前确定开源许可证。

以上事项表示当前规划，不代表承诺的发布日期。已交付的功能和修复可按版本及 commit 在
[`CHANGELOG.zh-CN.md`](CHANGELOG.zh-CN.md) 中查看。

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

数据目录内部的路径可以使用相对路径。`v2k init` 会为资料包知识库、数据库和 Cookie 文件写入可移植的相对路径。

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

打开 <http://127.0.0.1:8765>，粘贴哔哩哔哩视频链接或搜索视频。仅在需要重新下载并再次执行转录、摘要和导出时启用 **Force refresh download and all processing（强制刷新下载和全部处理）**。

**Runtime Settings（运行时设置）** 面板可配置统一的知识资料包路径、选择摘要后端（默认为 Codex CLI），以及启动、监控或停止本地 MLX Audio 服务。

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
└── library/
    └── 创作者_内容标题_视频ID/
        ├── 创作者_内容标题_视频ID.md
        └── assets/
            ├── 创作者_内容标题_视频ID.m4a
            ├── 创作者_内容标题_视频ID.lrc
            ├── 创作者_内容标题_视频ID.json
            └── 创作者_内容标题_视频ID.metadata.json
```

Markdown 是用户可编辑的知识文档，JSON 则保留生成时的转录时间轴，用于重新生成媒体相关产物。应用启动时会把旧 `media_dir` 配置和分散文件迁移进资料包。目录名和文件名统一使用 `创作者_内容标题_视频ID` 格式，并会针对 macOS 和 Windows 进行字符清理。重建缺失的媒体相关产物时不会覆盖已有 Markdown 笔记。

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

## Changelog：变更记录

版本及 commit 级别的功能、Bug 修复、性能优化、文档和构建变更见
[`CHANGELOG.zh-CN.md`](CHANGELOG.zh-CN.md)。

## 已知限制

- 哔哩哔哩的风控系统可能会拦截公开搜索请求。
- 对充电内容的识别依赖元数据提示；登录账号是否可以下载某个视频，最终以哔哩哔哩的判定为准。
- 当前网页界面在本地主机上运行且没有用户账号，不适合暴露到公网。
- 活跃任务及其流水线阶段在内存中协调；服务重启后不会恢复中断的任务。

## 许可证

项目尚未选择开源许可证。发布仓库前请添加 `LICENSE` 文件；在此之前，项目适用常规版权限制。

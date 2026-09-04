# Video2Knowledge

[简体中文](README.zh-CN.md) | English

Video2Knowledge is a local-first pipeline that turns Bilibili videos into a personal,
searchable knowledge library. It downloads up to three videos concurrently, pipelines each
completed download into MLX Audio transcription and LLM enrichment, and writes
Markdown, LRC, and JSON timeline files. It can also turn Markdown back into synchronized
speech and an Apple Music-compatible M4A file.

> **Project status:** alpha. The core workflow works on Apple Silicon, but APIs and
> configuration may still change before the first stable release.

## Implemented features

### Video sources and downloads

- ✅ Accepts a Bilibili video URL or searches videos and creators in the local web UI.
- ✅ Uses [`bili-dl`](https://github.com/war-ning/bili-dl) for authenticated and
  charging-content downloads; falls back to `yt-dlp` when `bili-dl` is not configured.
- ✅ Imports videos in creator-level batches with up to three concurrent downloads while
  independently pipelining transcription and LLM enrichment.
- ✅ Reuses complete media, transcription, summary, and export results by default and supports
  an explicit force-refresh option.
- ✅ Stores each source audio file with its transcript artifacts inside a self-contained video
  bundle that can be moved, backed up, or deleted independently.

### Models and interfaces

- ✅ Separates video providers, speech engines, and LLM enrichment backends behind interfaces
  so implementations can be replaced independently.
- ✅ Transcribes locally through an MLX Audio OpenAI-compatible server.
- ✅ Generates core summaries, further insights, suggestions, and follow-up questions.
- ✅ Supports Codex CLI and OpenAI-compatible LLM backends such as Ollama.
- ✅ Checks required runtime services before processing and lets the web UI start, monitor,
  and stop the local MLX Audio service.

### Speech and media

- ✅ Keeps the editable Markdown note at the video-bundle root and places source audio,
  synchronized LRC, and machine-readable JSON timelines together under `assets/`.
- ✅ Converts Markdown to speech and optionally packages it as AAC/M4A for Apple Music.

### Knowledge and task management

- ✅ Organizes the knowledge library by creator and collection while preserving collection
  context in exported documents.
- ✅ Persists download history and request progress in SQLite with multi-select queue filters
  for creator, collection, status, and created date; collection choices follow the selected
  creators. Collections and individual videos are grouped under collapsible creator rows with
  avatars, including automatically backfilled avatars for legacy history records.
- ✅ Supports pausing and resuming queued work, restarting failed jobs individually or in
  batches, and cleaning up stale terminal records.
- ✅ Provides interactive queue file controls for opening or revealing generated files and
  optionally removing their associated local data.

Video2Knowledge does not bypass platform authorization, charging-content access controls,
or DRM. Download and retain only content you are permitted to use.

## TODO

### Video sources and downloads

- [ ] Improve Bilibili search resilience when public requests trigger risk controls.
- [ ] Add support for more video providers.

### Models and interfaces

- [ ] Add configurable non-MLX speech backends.
- [ ] Stabilize the public configuration and API surface for the first non-alpha release.

### Speech and media

- [ ] Support multi-speaker interview transcription, speaker identification, and viewpoint
  extraction.
- [ ] Expand speech synthesis and media export configuration.

### Knowledge and task management

- [ ] Restore interrupted in-progress jobs automatically after the service restarts.
- [ ] Add authentication and authorization before supporting non-local web deployment.
- [ ] Select a license before the first non-alpha release.

These items describe the current roadmap rather than committed release dates. See
[`CHANGELOG.md`](CHANGELOG.md) for the features and fixes already delivered by version and
commit.

## Requirements

- macOS on Apple Silicon
- Python 3.11 or 3.12
- [Git](https://git-scm.com/)
- [FFmpeg](https://ffmpeg.org/) for Apple Music M4A export
- A running [MLX Audio](https://github.com/Blaizzy/mlx-audio) server for transcription
  and speech synthesis
- An authenticated Codex CLI for the default LLM backend, or an OpenAI-compatible local
  endpoint such as Ollama

## Installation

### Recommended: uv

```bash
git clone <your-repository-url> video2knowledge
cd video2knowledge
git clone https://github.com/war-ning/bili-dl vendor/bili-dl

uv sync --extra bilibili --extra audio --extra dev
source .venv/bin/activate
v2k init
```

### Conda and pip

```bash
git clone <your-repository-url> video2knowledge
cd video2knowledge
git clone https://github.com/war-ning/bili-dl vendor/bili-dl

conda create -n video2knowledge python=3.12
conda activate video2knowledge
python -m pip install -e ".[bilibili,audio,dev]"
v2k init
```

Install the MLX Audio server in the same environment with `pip install -e ".[mlx]"`, or
run it from a separate environment. The first start downloads the configured models:

```bash
mlx_audio.server --host 127.0.0.1 --port 8000
```

The default data directory is `./video2knowledge-data` under the directory where `v2k` is
started. Set `V2K_DATA_DIR` before running commands to use another location. Runtime data,
credentials, databases, and downloaded media must not be committed.

## Configuration

Run `v2k init`, then edit `./video2knowledge-data/config.json`. A complete example is
available in [`config.example.json`](config.example.json), and every setting is documented
in [`docs/configuration.md`](docs/configuration.md).

At minimum, set the absolute path to the local `bili-dl` checkout:

```json
{
  "bili_dl_dir": "/absolute/path/to/video2knowledge/vendor/bili-dl"
}
```

Paths inside the data directory may be relative. `v2k init` writes portable relative paths
for the bundle library, database, and cookie file.

## Bilibili login

Use the `bili-dl` QR scanner for charging content:

```bash
v2k login
```

Scan the QR code with the Bilibili mobile app and confirm the login. The command stores
`bili-dl` credentials in its own data directory and writes a Netscape cookie file with
`0600` permissions. Cookie values are never printed. A fallback flow is also available:

```bash
v2k qr-login
```

## Usage

Start the web interface:

```bash
v2k serve
```

Open <http://127.0.0.1:8765>, paste a Bilibili URL, or search for a video. Enable
Use **Force refresh download and all processing** only when the media, transcription,
summary, and exports must all be regenerated. Otherwise, a complete existing result for the
same video and language is reused.
The **Runtime Settings** panel configures the unified knowledge-bundle path, selects the
summary backend (Codex CLI by default), and starts, monitors, or stops the local MLX Audio
service.
Completed queue entries show their generated and source-media paths. Terminal jobs can be
removed from the queue while keeping local files, or removed together with their associated
local files after an explicit confirmation. Each generated file can also be opened with its
default macOS application or revealed directly in Finder. File controls expand on hover and
collapse only after the pointer and keyboard focus have left their current file section.

Process a URL from the command line:

```bash
v2k search "machine learning"
v2k process "https://www.bilibili.com/video/BV..."
v2k process "https://www.bilibili.com/video/BV..." --force-refresh
```

Convert Markdown into synchronized speech:

```bash
v2k speak notes.md --title "Knowledge Audio" --author "Author"
```

Apple Music imports the generated M4A with plain embedded lyrics. Precise synchronization
remains in the same-name LRC and JSON files because Apple Music has no stable public format
for importing synchronized lyrics.

## Data layout

```text
./video2knowledge-data/
├── config.json
├── bilibili-cookies.txt
├── library.db
└── library/
    └── creator_content-title_video-id/
        ├── creator_content-title_video-id.md
        └── assets/
            ├── creator_content-title_video-id.m4a
            ├── creator_content-title_video-id.lrc
            ├── creator_content-title_video-id.json
            └── creator_content-title_video-id.metadata.json
```

Markdown is the user-editable knowledge document, while JSON retains the generated transcript
timeline used to rebuild media-side artifacts. Legacy `media_dir` configurations and split
outputs are migrated into bundles when the application starts. Directory and file names share
the `creator_content-title_video-id` convention and are sanitized for macOS and Windows.
Rebuilding missing media-side assets does not overwrite an existing Markdown note.

## Architecture

The application separates video providers, speech engines, enrichment backends, storage,
and exporters behind small interfaces. See [`docs/architecture.md`](docs/architecture.md)
for the module map and extension points.

## Development

```bash
uv sync --extra bilibili --extra audio --extra dev
pytest
ruff check .
ruff format --check .
python -m build
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for contribution conventions and
[`SECURITY.md`](SECURITY.md) for handling credentials and reporting vulnerabilities.

## Changelog

See [`CHANGELOG.md`](CHANGELOG.md) for version-level and commit-level feature, bug-fix,
performance, documentation, and build history.

## Known limitations

- Bilibili may block public search requests through its risk-control system.
- Charging-content detection relies on metadata hints; Bilibili remains the authority on
  whether the logged-in account may download a video.
- The GUI currently runs on localhost without user accounts and is not intended for public
  network exposure.
- Active jobs and their pipeline stages are coordinated in memory; restarting the service does
  not resume interrupted jobs.

## License

No open-source license has been selected yet. Add a `LICENSE` file before publishing the
repository; until then, normal copyright restrictions apply.

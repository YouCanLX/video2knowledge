# Video2Knowledge

Video2Knowledge is a local-first pipeline that turns Bilibili videos into a personal,
searchable knowledge library. It downloads one video at a time, transcribes audio with
Whisper Large V3 Turbo through MLX Audio, enriches the transcript with an LLM, and writes
Markdown, LRC, and JSON timeline files. It can also turn Markdown back into synchronized
speech and an Apple Music-compatible M4A file.

> **Project status:** alpha. The core workflow works on Apple Silicon, but APIs and
> configuration may still change before the first stable release.

## What it does

- Accepts a Bilibili video URL or searches videos and creators in the local web UI.
- Uses [`bili-dl`](https://github.com/war-ning/bili-dl) for authenticated and
  charging-content downloads; falls back to `yt-dlp` when `bili-dl` is not configured.
- Reuses downloaded media by default and supports an explicit force-refresh option.
- Transcribes locally through an MLX Audio OpenAI-compatible server.
- Generates core summaries, further insights, suggestions, and follow-up questions.
- Stores readable Markdown plus synchronized LRC and machine-readable JSON timelines.
- Converts Markdown to speech and optionally packages it as AAC/M4A for Apple Music.
- Keeps downloads serial so accounts without Bilibili premium never start parallel jobs.

Video2Knowledge does not bypass platform authorization, charging-content access controls,
or DRM. Download and retain only content you are permitted to use.

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
for the library, media directory, database, and cookie file.

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
**Force re-download cached video** only when the local copy must be refreshed.
The **Runtime Settings** panel independently configures download and Markdown export paths,
selects the summary backend (Codex CLI by default), and starts, monitors, or stops the local
MLX Audio service.
Completed queue entries show their generated and source-media paths. Terminal jobs can be
removed from the queue while keeping local files, or removed together with their associated
local files after an explicit confirmation.

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
├── media/
└── library/
    └── creator_content-title_video-id/
        ├── creator_content-title_video-id.md
        ├── creator_content-title_video-id.lrc
        └── creator_content-title_video-id.json
```

Markdown is the source of truth. Directory and file names share the
`creator_content-title_video-id` convention and are sanitized for macOS and Windows.

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

## Known limitations

- Bilibili may block public search requests through its risk-control system.
- Charging-content detection relies on metadata hints; Bilibili remains the authority on
  whether the logged-in account may download a video.
- The GUI currently runs on localhost without user accounts and is not intended for public
  network exposure.
- Jobs are serialized in memory; restarting the service does not resume interrupted jobs.

## License

No open-source license has been selected yet. Add a `LICENSE` file before publishing the
repository; until then, normal copyright restrictions apply.

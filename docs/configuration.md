# Configuration

Video2Knowledge reads `config.json` from its data directory. The default is
`./video2knowledge-data` under the directory where the command is started; set
`V2K_DATA_DIR` to override it. Relative paths in the JSON file are resolved from that data
directory, which keeps configurations portable.

Run `v2k init` to create a complete configuration, or copy `config.example.json`.

## Paths

| Setting | Default | Purpose |
| --- | --- | --- |
| `library_dir` | `library` | Self-contained video bundles with Markdown and `assets/` |
| `database_path` | `library.db` | SQLite job and document index |
| `bili_dl_dir` | `null` | Absolute path to the local `bili-dl` checkout |
| `cookie_file` | `null` | Netscape cookie file used by Bilibili adapters |

When `bili_dl_dir` is unset, public video downloads use `yt-dlp`. Configure `bili-dl` and
run `v2k login` for charging content.

## MLX Audio

| Setting | Default | Purpose |
| --- | --- | --- |
| `mlx_base_url` | `http://127.0.0.1:8000` | MLX Audio server address |
| `mlx_audio_command` | `mlx_audio.server --host 127.0.0.1 --port 8000` | Command used by the GUI to start the server |
| `mlx_stt_model` | `mlx-community/whisper-large-v3-turbo-asr-fp16` | Speech-to-text model |
| `mlx_tts_model` | `mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit` | Text-to-speech model |
| `mlx_tts_voice` | `Vivian` | Voice sent to the speech endpoint |

Video2Knowledge sends compressed source media through PyAV and uploads mono 16 kHz WAV to
the server. Install the `audio` package extra to enable compressed-audio decoding.

The GUI can start and stop a process launched with `mlx_audio_command`, monitor its HTTP
endpoint, and show the recent process log. It never stops an MLX Audio server that was
started outside Video2Knowledge. Stop a managed process before changing its command or URL.

## LLM enrichment

`llm_backend` accepts `codex_cli` or `openai_compatible`.

### Codex CLI

| Setting | Default | Purpose |
| --- | --- | --- |
| `codex_cli_path` | `codex` | Codex executable name or path |
| `codex_model` | empty | Optional model override; empty uses the CLI default |
| `codex_timeout_seconds` | `900` | Maximum enrichment time |

The Codex backend runs non-interactively in a temporary directory with a read-only sandbox,
an ephemeral session, and a JSON Schema for the response. Account usage and inference
location follow the installed Codex CLI configuration.

### OpenAI-compatible endpoint

| Setting | Default | Purpose |
| --- | --- | --- |
| `llm_base_url` | `http://127.0.0.1:11434/v1` | Chat-completions API root |
| `llm_model` | `qwen3:8b` | Model sent to the endpoint |

If enrichment fails, the pipeline preserves the transcript and writes a fallback summary.
The GUI exposes both backends and defaults to Codex CLI.

## GUI runtime settings

The **Runtime Settings** panel changes the unified video-bundle directory. Relative paths
resolve from the active data directory; absolute paths remain absolute. Paths inside the data
directory are displayed in their portable relative form, such as `library`. Changes apply to
new jobs and are persisted in `config.json`. On startup, a legacy `media_dir` setting is used
once to locate split source media, migrate it into each video's `assets/` directory, and is
omitted the next time the configuration is saved.

## Security

Never commit a real `config.json`, cookie file, QR image, SQLite database, downloaded media,
or generated library. The repository ignore rules cover the default locations, but custom
paths outside those locations remain the user's responsibility.

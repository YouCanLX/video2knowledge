# Architecture

Video2Knowledge follows a ports-and-adapters structure. The pipeline depends on protocols,
not on Bilibili, MLX Audio, or a specific LLM implementation.

```text
CLI / FastAPI web app
        │
        ▼
ApplicationServices ── configuration + dependency assembly
        │
        ▼
Pipeline ───────────── serial orchestration and progress
   │       │       │
   ▼       ▼       ▼
Video     STT/TTS  TextEnricher       (protocols in ports.py)
   │       │       │
   ▼       ▼       ▼
bili-dl   MLX      Codex CLI or       (adapters)
yt-dlp    Audio    OpenAI-compatible API
        │
        ▼
SQLite repository + Markdown/LRC/JSON exporters
```

## Module map

| Module | Responsibility |
| --- | --- |
| `config.py` | Data-directory discovery and portable JSON configuration |
| `services.py` | Shared dependency construction for CLI and web entry points |
| `ports.py` | Provider, STT, TTS, and enrichment contracts |
| `pipeline.py` | Download-cache selection and processing orchestration |
| `repository.py` | SQLite job and knowledge-document index |
| `exporters.py` | Markdown, LRC, JSON, and Markdown parsing |
| `apple_music.py` | FFmpeg-based AAC/M4A packaging |
| `naming.py` | Cross-platform library directory and file naming |
| `adapters/bilibili.py` | Public Bilibili metadata/search and `yt-dlp` download |
| `adapters/bili_dl.py` | Authenticated native `bili-dl` integration |
| `adapters/mlx_audio.py` | MLX Audio HTTP client and local decoding |
| `adapters/llm.py` | Codex CLI and OpenAI-compatible enrichment backends |

## Extension points

To add another platform, implement `VideoProvider` and select it in `build_services`.
To add another speech or LLM engine, implement the corresponding protocol and keep model-
specific behavior inside an adapter. Export formats should consume `KnowledgeDocument`
rather than adapter-specific data.

## Processing lifecycle

1. Resolve canonical video metadata.
2. Reuse media matching the source ID unless force refresh is enabled.
3. Transcribe the audio into timestamped segments.
4. Enrich the transcript; preserve it even when enrichment fails.
5. Optionally synthesize speech and rebuild timestamps from actual audio durations.
6. Write the output bundle and update the SQLite document index.

The web application uses a single in-memory worker to prevent concurrent downloads. This is
an intentional constraint for the current Bilibili account model, not a scaling mechanism.

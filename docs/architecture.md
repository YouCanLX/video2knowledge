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
Pipeline ───────────── staged concurrency and progress
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
| `pipeline.py` | Bundle-local media reuse and processing orchestration |
| `repository.py` | SQLite job and knowledge-document index |
| `exporters.py` | Markdown, LRC, JSON, and Markdown parsing |
| `apple_music.py` | FFmpeg-based AAC/M4A packaging |
| `light_player.py` | Lossless M4A lyric-metadata updates from same-name LRC sidecars |
| `naming.py` | Cross-platform library directory and file naming |
| `storage.py` | Migration of legacy split media and generated artifacts into bundles |
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
2. Reuse source media from the video's `assets/` directory unless force refresh is enabled.
3. Enter the single-slot local speech stage and transcribe the audio into timestamped segments.
4. Enrich the transcript in a separately bounded stage; preserve it even when enrichment fails.
5. Optionally synthesize speech and rebuild timestamps from actual audio durations.
6. Keep Markdown at the bundle root, write media and timeline assets under `assets/`, and
   update the SQLite document index.

The web application runs jobs as an in-memory pipeline. Up to three downloads and three LLM
enrichments may run concurrently, while local MLX transcription and synthesis share one slot
to avoid competing for unified memory. Per-source locks prevent duplicate submissions from
writing the same bundle paths concurrently.

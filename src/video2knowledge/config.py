from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_STT_MODEL = "mlx-community/whisper-large-v3-turbo-asr-fp16"
DEFAULT_TTS_MODEL = "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit"
DEFAULT_MLX_AUDIO_COMMAND = "mlx_audio.server --host 127.0.0.1 --port 8000"
BILIBILI_DOWNLOAD_CONCURRENCY = 3
DATA_DIR_NAME = "video2knowledge-data"
CONFIG_FILE_NAME = "config.json"


def default_data_dir() -> Path:
    """Return the configured data directory or one under the current project directory."""
    configured = os.getenv("V2K_DATA_DIR")
    return Path(configured).expanduser() if configured else Path.cwd() / DATA_DIR_NAME


def _resolve_path(root: Path, value: object, default: str) -> Path:
    path = Path(str(value or default)).expanduser()
    return (path if path.is_absolute() else root / path).resolve()


def _portable_path(path: Path | None, root: Path) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


class SpeechMediaOptions(BaseModel):
    """Validated options shared by JSON configuration and runtime settings."""

    model_config = ConfigDict(strict=True, str_strip_whitespace=True, allow_inf_nan=False)

    mlx_tts_model: str = Field(default=DEFAULT_TTS_MODEL, min_length=1)
    mlx_tts_voice: str = Field(default="Vivian", min_length=1)
    mlx_tts_speed: float = Field(default=1.0, ge=0.25, le=4.0)
    mlx_tts_timeout_seconds: float | None = Field(default=None, gt=0)
    apple_music_enabled: bool = True
    media_audio_bitrate_kbps: int = Field(default=192, ge=32, le=320)
    media_sample_rate: Literal[8000, 16000, 22050, 24000, 32000, 44100, 48000] | None = None
    media_channels: Literal[1, 2] | None = None
    media_lyrics_mode: Literal["plain", "synced", "none"] = "plain"


@dataclass(slots=True)
class Settings:
    data_dir: Path
    library_dir: Path
    database_path: Path
    legacy_media_dir: Path | None = None
    bili_dl_dir: Path | None = None
    cookie_file: Path | None = None
    mlx_base_url: str = "http://127.0.0.1:8000"
    mlx_audio_command: str = DEFAULT_MLX_AUDIO_COMMAND
    mlx_stt_model: str = DEFAULT_STT_MODEL
    mlx_tts_model: str = DEFAULT_TTS_MODEL
    mlx_tts_voice: str = "Vivian"
    mlx_tts_speed: float = 1.0
    mlx_tts_timeout_seconds: float | None = None
    apple_music_enabled: bool = True
    media_audio_bitrate_kbps: int = 192
    media_sample_rate: int | None = None
    media_channels: int | None = None
    media_lyrics_mode: str = "plain"
    llm_backend: str = "codex_cli"
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_model: str = "qwen3:8b"
    codex_cli_path: str = "codex"
    codex_model: str = ""
    codex_timeout_seconds: float = 900

    def speech_media_options(self) -> SpeechMediaOptions:
        return SpeechMediaOptions.model_validate(
            {name: getattr(self, name) for name in SpeechMediaOptions.model_fields}
        )

    @classmethod
    def load(cls, data_dir: Path | None = None) -> Settings:
        root = (data_dir or default_data_dir()).expanduser().resolve()
        raw: dict[str, object] = {}
        path = root / CONFIG_FILE_NAME
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError(f"Configuration must be a JSON object: {path}")
        options = SpeechMediaOptions.model_validate(
            {name: raw[name] for name in SpeechMediaOptions.model_fields if name in raw}
        )
        return cls(
            **options.model_dump(),
            data_dir=root,
            library_dir=_resolve_path(root, raw.get("library_dir"), "library"),
            database_path=_resolve_path(root, raw.get("database_path"), "library.db"),
            legacy_media_dir=(
                _resolve_path(root, raw.get("media_dir"), "media")
                if raw.get("media_dir") or (root / "media").exists()
                else None
            ),
            bili_dl_dir=(
                _resolve_path(root, raw["bili_dl_dir"], ".") if raw.get("bili_dl_dir") else None
            ),
            cookie_file=(
                _resolve_path(root, raw["cookie_file"], "bilibili-cookies.txt")
                if raw.get("cookie_file")
                else None
            ),
            mlx_base_url=str(raw.get("mlx_base_url", "http://127.0.0.1:8000")),
            mlx_audio_command=str(raw.get("mlx_audio_command", DEFAULT_MLX_AUDIO_COMMAND)),
            mlx_stt_model=str(raw.get("mlx_stt_model", DEFAULT_STT_MODEL)),
            llm_backend=str(raw.get("llm_backend", "codex_cli")),
            llm_base_url=str(raw.get("llm_base_url", "http://127.0.0.1:11434/v1")),
            llm_model=str(raw.get("llm_model", "qwen3:8b")),
            codex_cli_path=str(raw.get("codex_cli_path", "codex")),
            codex_model=str(raw.get("codex_model", "")),
            codex_timeout_seconds=float(raw.get("codex_timeout_seconds", 900)),
        )

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.library_dir):
            path.mkdir(parents=True, exist_ok=True)

    def save(self) -> None:
        options = self.speech_media_options()
        self.ensure_dirs()
        payload = {
            **options.model_dump(),
            "library_dir": _portable_path(self.library_dir, self.data_dir),
            "database_path": _portable_path(self.database_path, self.data_dir),
            "bili_dl_dir": _portable_path(self.bili_dl_dir, self.data_dir),
            "cookie_file": _portable_path(self.cookie_file, self.data_dir),
            "mlx_base_url": self.mlx_base_url,
            "mlx_audio_command": self.mlx_audio_command,
            "mlx_stt_model": self.mlx_stt_model,
            "llm_backend": self.llm_backend,
            "llm_base_url": self.llm_base_url,
            "llm_model": self.llm_model,
            "codex_cli_path": self.codex_cli_path,
            "codex_model": self.codex_model,
            "codex_timeout_seconds": self.codex_timeout_seconds,
        }
        (self.data_dir / CONFIG_FILE_NAME).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

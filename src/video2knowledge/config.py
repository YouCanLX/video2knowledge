from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_STT_MODEL = "mlx-community/whisper-large-v3-turbo-asr-fp16"
DEFAULT_TTS_MODEL = "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit"
DEFAULT_MLX_AUDIO_COMMAND = "mlx_audio.server --host 127.0.0.1 --port 8000"
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


@dataclass(slots=True)
class Settings:
    data_dir: Path
    library_dir: Path
    media_dir: Path
    database_path: Path
    bili_dl_dir: Path | None = None
    cookie_file: Path | None = None
    mlx_base_url: str = "http://127.0.0.1:8000"
    mlx_audio_command: str = DEFAULT_MLX_AUDIO_COMMAND
    mlx_stt_model: str = DEFAULT_STT_MODEL
    mlx_tts_model: str = DEFAULT_TTS_MODEL
    mlx_tts_voice: str = "Vivian"
    llm_backend: str = "codex_cli"
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_model: str = "qwen3:8b"
    codex_cli_path: str = "codex"
    codex_model: str = ""
    codex_timeout_seconds: float = 900

    @classmethod
    def load(cls, data_dir: Path | None = None) -> Settings:
        root = (data_dir or default_data_dir()).expanduser().resolve()
        raw: dict[str, object] = {}
        path = root / CONFIG_FILE_NAME
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError(f"Configuration must be a JSON object: {path}")
        return cls(
            data_dir=root,
            library_dir=_resolve_path(root, raw.get("library_dir"), "library"),
            media_dir=_resolve_path(root, raw.get("media_dir"), "media"),
            database_path=_resolve_path(root, raw.get("database_path"), "library.db"),
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
            mlx_tts_model=str(raw.get("mlx_tts_model", DEFAULT_TTS_MODEL)),
            mlx_tts_voice=str(raw.get("mlx_tts_voice", "Vivian")),
            llm_backend=str(raw.get("llm_backend", "codex_cli")),
            llm_base_url=str(raw.get("llm_base_url", "http://127.0.0.1:11434/v1")),
            llm_model=str(raw.get("llm_model", "qwen3:8b")),
            codex_cli_path=str(raw.get("codex_cli_path", "codex")),
            codex_model=str(raw.get("codex_model", "")),
            codex_timeout_seconds=float(raw.get("codex_timeout_seconds", 900)),
        )

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.library_dir, self.media_dir):
            path.mkdir(parents=True, exist_ok=True)

    def save(self) -> None:
        self.ensure_dirs()
        payload = {
            "library_dir": _portable_path(self.library_dir, self.data_dir),
            "media_dir": _portable_path(self.media_dir, self.data_dir),
            "database_path": _portable_path(self.database_path, self.data_dir),
            "bili_dl_dir": _portable_path(self.bili_dl_dir, self.data_dir),
            "cookie_file": _portable_path(self.cookie_file, self.data_dir),
            "mlx_base_url": self.mlx_base_url,
            "mlx_audio_command": self.mlx_audio_command,
            "mlx_stt_model": self.mlx_stt_model,
            "mlx_tts_model": self.mlx_tts_model,
            "mlx_tts_voice": self.mlx_tts_voice,
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

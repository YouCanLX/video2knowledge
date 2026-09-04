from __future__ import annotations

from dataclasses import dataclass

from .adapters.bili_dl import BiliDlProvider
from .adapters.bilibili import BilibiliProvider
from .adapters.llm import create_enricher
from .adapters.mlx_audio import MlxAudioClient
from .config import Settings
from .pipeline import Pipeline
from .ports import VideoProvider
from .repository import LibraryRepository
from .storage import migrate_legacy_bundles, supplement_legacy_media


@dataclass(slots=True)
class ApplicationServices:
    """Runtime dependencies shared by the CLI and web application."""

    provider: VideoProvider
    audio: MlxAudioClient
    repository: LibraryRepository
    pipeline: Pipeline


def build_services(settings: Settings) -> ApplicationServices:
    """Build the configured adapters and application pipeline."""
    settings.ensure_dirs()
    provider: VideoProvider = (
        BiliDlProvider(settings.bili_dl_dir, settings.cookie_file)
        if settings.bili_dl_dir
        else BilibiliProvider(cookie_file=settings.cookie_file)
    )
    if isinstance(provider, BiliDlProvider):
        provider.set_download_dir(settings.library_dir / ".staging")
    audio = MlxAudioClient(
        base_url=settings.mlx_base_url,
        stt_model=settings.mlx_stt_model,
        tts_model=settings.mlx_tts_model,
        voice=settings.mlx_tts_voice,
    )
    repository = LibraryRepository(settings.database_path)
    migrate_legacy_bundles(settings, repository)
    supplement_legacy_media(settings, repository)
    pipeline = Pipeline(
        provider=provider,
        stt=audio,
        enricher=create_enricher(settings),
        tts=audio,
        repository=repository,
        library_dir=settings.library_dir,
    )
    return ApplicationServices(provider, audio, repository, pipeline)

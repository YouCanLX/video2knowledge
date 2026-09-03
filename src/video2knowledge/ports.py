from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .models import Enrichment, TranscriptSegment, VideoItem


class VideoProvider(Protocol):
    """Contract implemented by video-platform adapters."""

    async def search(self, query: str, page: int = 1) -> list[VideoItem]: ...
    async def search_creators(self, query: str, page: int = 1) -> list[dict[str, str | int]]: ...
    async def get_creator(self, creator_id: int) -> dict[str, str | int]: ...
    async def get_creator_collections(
        self, creator_id: int, page: int = 1, page_size: int = 8
    ) -> dict: ...
    async def get_creator_videos(
        self, creator_id: int, page: int = 1, page_size: int = 12
    ) -> dict: ...
    async def get_collection_videos(
        self,
        creator_id: int,
        collection_kind: str,
        collection_id: int,
        page: int = 1,
        page_size: int = 12,
    ) -> dict: ...
    async def resolve(self, source_id: str) -> VideoItem: ...
    async def download_audio(
        self, item: VideoItem, output_dir: Path, force_refresh: bool = False
    ) -> Path: ...
    async def login(self) -> str: ...


class SpeechToText(Protocol):
    def transcribe(
        self, audio_path: Path, language: str | None = None
    ) -> list[TranscriptSegment]: ...


class TextToSpeech(Protocol):
    def synthesize(
        self, segments: list[TranscriptSegment], output_path: Path, language: str
    ) -> Path: ...


class TextEnricher(Protocol):
    async def enrich(self, title: str, text: str, language: str) -> Enrichment: ...

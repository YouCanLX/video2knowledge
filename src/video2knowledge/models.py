from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class JobStatus(StrEnum):
    QUEUED = "queued"
    PAUSING = "pausing"
    PAUSED = "paused"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    ENRICHING = "enriching"
    SYNTHESIZING = "synthesizing"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass(slots=True)
class VideoItem:
    platform: str
    source_id: str
    title: str
    url: str
    author: str = ""
    author_id: str = ""
    description: str = ""
    cover_url: str = ""
    duration: float = 0.0
    published_at: str = ""
    tags: list[str] = field(default_factory=list)
    is_charging: bool = False
    collection_kind: str = ""
    collection_id: int = 0
    collection_title: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TranscriptSegment:
    start: float
    end: float
    text: str
    speaker: str | None = None

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError("invalid transcript time range")
        self.text = self.text.strip()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Enrichment:
    summary: list[str] = field(default_factory=list)
    insights: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class KnowledgeDocument:
    video: VideoItem
    segments: list[TranscriptSegment]
    enrichment: Enrichment = field(default_factory=Enrichment)
    language: str = "zh-CN"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    audio_path: Path | None = None

    @property
    def plain_text(self) -> str:
        return "\n".join(segment.text for segment in self.segments)

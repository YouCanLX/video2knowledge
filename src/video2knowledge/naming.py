from __future__ import annotations

import re
import unicodedata

from .models import VideoItem


def safe_component(value: str, fallback: str) -> str:
    """Return a readable component that is safe on macOS and Windows."""
    value = unicodedata.normalize("NFC", value).strip()
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", value)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"-{2,}", "-", value)
    return value.strip(" .-_") or fallback


def _truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip(" .-_")


def library_stem(item: VideoItem, max_bytes: int = 220) -> str:
    """Build the shared `creator_title_video-id` directory and file stem."""
    author = safe_component(item.author, "UnknownCreator")
    title = safe_component(item.title, "UntitledContent")
    source_id = safe_component(item.source_id, "NoVideoID")
    suffix = f"_{source_id}"
    prefix_budget = max(1, max_bytes - len(suffix.encode("utf-8")))
    prefix = _truncate_utf8(f"{author}_{title}", prefix_budget)
    return f"{prefix}{suffix}"

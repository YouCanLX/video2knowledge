from __future__ import annotations

import re
import unicodedata
from pathlib import Path

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
    """Build the stable `creator_title_video-id` library directory name."""
    author = safe_component(item.author, "UnknownCreator")
    title = safe_component(item.title, "UntitledContent")
    source_id = safe_component(item.source_id, "NoVideoID")
    suffix = f"_{source_id}"
    prefix_budget = max(1, max_bytes - len(suffix.encode("utf-8")))
    prefix = _truncate_utf8(f"{author}_{title}", prefix_budget)
    return f"{prefix}{suffix}"


def library_filename_stem(item: VideoItem, max_bytes: int = 220) -> str:
    """Build a file stem, inserting collection between creator and video title."""
    author = safe_component(item.author, "UnknownCreator")
    title = safe_component(item.title, "UntitledContent")
    source_id = safe_component(item.source_id, "NoVideoID")
    components = [author]
    if item.collection_title or item.collection_id:
        collection = item.collection_title or f"Collection-{item.collection_id}"
        components.append(safe_component(collection, "Collection"))
    components.append(title)
    suffix = f"_{source_id}"
    prefix_budget = max(1, max_bytes - len(suffix.encode("utf-8")))
    prefix = _truncate_utf8("_".join(components), prefix_budget)
    return f"{prefix}{suffix}"


def library_relative_directory(item: VideoItem, max_component_bytes: int = 220) -> Path:
    """Build the author/collection/output-directory hierarchy for a video."""
    author = _truncate_utf8(
        safe_component(item.author, "UnknownCreator"), max_component_bytes
    )
    leaf = library_filename_stem(item, max_bytes=max_component_bytes)
    if item.collection_title or item.collection_id:
        collection = item.collection_title or f"Collection-{item.collection_id}"
        collection = _truncate_utf8(
            safe_component(collection, "Collection"), max_component_bytes
        )
        return Path(author) / collection / leaf
    return Path(author) / leaf

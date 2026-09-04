from __future__ import annotations

import shutil
from contextlib import suppress
from pathlib import Path

from .config import Settings
from .models import VideoItem
from .naming import library_filename_stem, library_relative_directory
from .repository import LibraryRepository


def _video_item(payload: dict) -> VideoItem:
    fields = VideoItem.__dataclass_fields__
    return VideoItem(**{key: value for key, value in payload.items() if key in fields})


def _inside(path: Path, directory: Path | None) -> bool:
    if directory is None:
        return False
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def migrate_legacy_bundles(settings: Settings, repository: LibraryRepository) -> int:
    """Move legacy split outputs into self-contained per-video bundle directories."""
    migrations: list[tuple[str, str, Path, Path]] = []
    for entry in repository.list_download_history():
        item = _video_item(entry["source"])
        package_dir = settings.library_dir / library_relative_directory(item)
        assets_dir = package_dir / "assets"
        stem = library_filename_stem(item)
        destinations = {
            "lyrics": assets_dir / f"{stem}.lrc",
            "timeline": assets_dir / f"{stem}.json",
            "metadata": assets_dir / f"{stem}.metadata.json",
        }
        for key in ("source_media", "audio"):
            value = entry["outputs"].get(key)
            if value:
                suffix = Path(value).suffix.casefold() or ".media"
                marker = "-tts" if key == "audio" else ""
                destinations[key] = assets_dir / f"{stem}{marker}{suffix}"

        for key, destination in destinations.items():
            value = entry["outputs"].get(key)
            if not value:
                continue
            source = Path(value).expanduser()
            if source.resolve() == destination.resolve() or not source.is_file():
                continue
            if not (_inside(source, settings.legacy_media_dir) or _inside(source, package_dir)):
                continue
            migrations.append((item.source_id, key, source, destination))

    copied_sources: set[Path] = set()
    replacements: dict[str, dict[str, str]] = {}
    for source_id, key, source, destination in migrations:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(source, destination)
        copied_sources.add(source)
        replacements.setdefault(source_id, {})[key] = str(destination.resolve())

    for source_id, output_replacements in replacements.items():
        repository.replace_output_paths(source_id, output_replacements)

    for source in copied_sources:
        source.unlink()
        parent = source.parent
        while settings.legacy_media_dir and _inside(parent, settings.legacy_media_dir):
            with suppress(OSError):
                parent.rmdir()
            if parent == settings.legacy_media_dir:
                break
            parent = parent.parent
    return len(copied_sources)

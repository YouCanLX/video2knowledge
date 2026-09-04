from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from .config import Settings
from .models import VideoItem
from .naming import library_filename_stem, library_relative_directory
from .repository import LibraryRepository

VIDEO_ID_PATTERN = re.compile(r"(?i)BV[0-9A-Za-z]{10}")
LEGACY_MEDIA_SUFFIXES = {
    ".aac",
    ".flac",
    ".m4a",
    ".mka",
    ".mp3",
    ".mp4",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
}
MetadataReader = Callable[[Path], str]


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


def _normalized(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in value if character.isalnum())


def _candidate_items(settings: Settings, repository: LibraryRepository) -> list[VideoItem]:
    items = {
        str(entry["source"]["source_id"]).casefold(): _video_item(entry["source"])
        for entry in repository.list_download_history()
    }
    for path in settings.library_dir.rglob("*.metadata.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            item = _video_item(payload.get("video") or {})
        except (OSError, TypeError, ValueError):
            continue
        if item.source_id:
            items.setdefault(item.source_id.casefold(), item)
    return list(items.values())


def _unique_scored_match(
    value: str, items: list[VideoItem], *, metadata: bool = False
) -> VideoItem | None:
    scores: list[tuple[int, VideoItem]] = []
    for item in items:
        source_id = _normalized(item.source_id)
        title = _normalized(item.title)
        author = _normalized(item.author)
        exact_stem = _normalized(library_filename_stem(item))
        score = 0
        strong_match = False
        if metadata and source_id and source_id in value:
            score += 100_000
            strong_match = True
        if not metadata and exact_stem and exact_stem == value:
            score += 50_000
            strong_match = True
        if len(title) >= 4 and title in value:
            score += len(title) * 2
            strong_match = True
        if len(author) >= 3 and author in value:
            score += len(author)
        if score and strong_match:
            scores.append((score, item))
    scores.sort(key=lambda pair: pair[0], reverse=True)
    if not scores or (len(scores) > 1 and scores[0][0] == scores[1][0]):
        return None
    return scores[0][1]


def _embedded_metadata(path: Path) -> str:
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format_tags",
                    "-of",
                    "json",
                    str(path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0:
                return result.stdout
        except (OSError, subprocess.SubprocessError):
            pass
    if sys.platform == "darwin" and Path("/usr/bin/mdls").is_file():
        fields = (
            "kMDItemTitle",
            "kMDItemAuthors",
            "kMDItemAlbum",
            "kMDItemComment",
            "kMDItemWhereFroms",
        )
        command = ["/usr/bin/mdls", "-raw"]
        for field in fields:
            command.extend(("-name", field))
        try:
            result = subprocess.run(
                [*command, str(path.resolve())],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0:
                return result.stdout
        except (OSError, subprocess.SubprocessError):
            pass
    return ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _same_file_content(first: Path, second: Path) -> bool:
    return first.stat().st_size == second.stat().st_size and _sha256(first) == _sha256(second)


def _quarantine_file(source: Path, legacy_dir: Path, quarantine_dir: Path) -> None:
    destination = quarantine_dir / source.relative_to(legacy_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and _same_file_content(source, destination):
        source.unlink()
        return
    counter = 1
    while destination.exists():
        destination = destination.with_name(f"{destination.stem}-{counter}{destination.suffix}")
        counter += 1
    shutil.move(str(source), str(destination))


def _remove_empty_legacy_tree(directory: Path) -> bool:
    for metadata_file in directory.rglob(".DS_Store"):
        metadata_file.unlink()
    directories = sorted(
        (path for path in directory.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for path in directories:
        with suppress(OSError):
            path.rmdir()
    with suppress(OSError):
        directory.rmdir()
    return not directory.exists()


def supplement_legacy_media(
    settings: Settings,
    repository: LibraryRepository,
    metadata_reader: MetadataReader = _embedded_metadata,
) -> dict[str, int | bool]:
    """Match unindexed legacy media, quarantine unknown files, and retire the old root."""
    legacy_dir = settings.legacy_media_dir
    result: dict[str, int | bool] = {
        "matched_by_id": 0,
        "matched_by_filename": 0,
        "matched_by_metadata": 0,
        "identical_duplicates": 0,
        "quarantined": 0,
        "legacy_dir_removed": False,
    }
    if not legacy_dir or not legacy_dir.is_dir():
        result["legacy_dir_removed"] = True
        return result

    items = _candidate_items(settings, repository)
    by_id = {item.source_id.casefold(): item for item in items}
    quarantine_dir = settings.library_dir / ".unmatched-media"
    media_files = [
        path
        for path in legacy_dir.rglob("*")
        if path.is_file() and path.suffix.casefold() in LEGACY_MEDIA_SUFFIXES
    ]
    for source in media_files:
        relative_text = str(source.relative_to(legacy_dir))
        found_ids = {
            match.group(0).casefold() for match in VIDEO_ID_PATTERN.finditer(relative_text)
        } & by_id.keys()
        item = by_id[next(iter(found_ids))] if len(found_ids) == 1 else None
        method = "matched_by_id"
        if item is None:
            item = _unique_scored_match(_normalized(source.stem), items)
            method = "matched_by_filename"
        if item is None:
            item = _unique_scored_match(_normalized(metadata_reader(source)), items, metadata=True)
            method = "matched_by_metadata"

        if item is None:
            _quarantine_file(source, legacy_dir, quarantine_dir)
            result["quarantined"] = int(result["quarantined"]) + 1
            continue

        assets_dir = settings.library_dir / library_relative_directory(item) / "assets"
        destination = assets_dir / f"{library_filename_stem(item)}{source.suffix.casefold()}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if not _same_file_content(source, destination):
                _quarantine_file(source, legacy_dir, quarantine_dir)
                result["quarantined"] = int(result["quarantined"]) + 1
                continue
            source.unlink()
            result["identical_duplicates"] = int(result["identical_duplicates"]) + 1
        else:
            shutil.move(str(source), str(destination))
        repository.replace_output_paths(
            item.source_id, {"source_media": str(destination.resolve())}
        )
        result[method] = int(result[method]) + 1

    result["legacy_dir_removed"] = _remove_empty_legacy_tree(legacy_dir)
    return result


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

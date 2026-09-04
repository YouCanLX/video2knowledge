from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from mutagen.mp4 import MP4

LRC_TIMESTAMP = re.compile(r"^\[\d+:[0-5]\d(?:\.\d{1,3})?\]", re.MULTILINE)
MP4_LYRICS_TAG = "\xa9lyr"


@dataclass(slots=True)
class LightPlayerExportResult:
    updated: int = 0
    unchanged: int = 0
    missing_lrc: int = 0
    invalid_lrc: int = 0
    failed: int = 0


def embed_lrc_in_m4a(m4a_path: Path, lrc_path: Path | None = None) -> bool:
    """Embed synchronized LRC text in an M4A lyrics tag without decoding its audio."""
    m4a_path = m4a_path.expanduser().resolve()
    lrc_path = (lrc_path or m4a_path.with_suffix(".lrc")).expanduser().resolve()
    if m4a_path.suffix.casefold() != ".m4a":
        raise ValueError(f"Light Player export only supports M4A files: {m4a_path}")
    if not m4a_path.is_file():
        raise FileNotFoundError(m4a_path)
    if not lrc_path.is_file():
        raise FileNotFoundError(lrc_path)
    lyrics = lrc_path.read_text(encoding="utf-8")
    if not lyrics.strip() or not LRC_TIMESTAMP.search(lyrics):
        raise ValueError(f"The LRC file has no synchronized lyric lines: {lrc_path}")

    current = MP4(m4a_path)
    if current.tags and current.tags.get(MP4_LYRICS_TAG) == [lyrics]:
        return False

    with TemporaryDirectory(prefix=".v2k-light-player-", dir=m4a_path.parent) as temporary:
        candidate = Path(temporary) / m4a_path.name
        shutil.copy2(m4a_path, candidate)
        audio = MP4(candidate)
        if audio.tags is None:
            audio.add_tags()
        audio.tags[MP4_LYRICS_TAG] = [lyrics]
        audio.save()
        verified = MP4(candidate)
        if not verified.tags or verified.tags.get(MP4_LYRICS_TAG) != [lyrics]:
            raise RuntimeError(f"Could not verify embedded lyrics: {m4a_path}")
        os.replace(candidate, m4a_path)
    return True


def export_light_player(library_dir: Path) -> LightPlayerExportResult:
    """Embed every bundle-local same-name LRC in its M4A for Light Player."""
    result = LightPlayerExportResult()
    media_files = (
        path
        for path in library_dir.expanduser().resolve().rglob("*")
        if path.is_file() and path.suffix.casefold() == ".m4a"
    )
    for m4a_path in sorted(media_files):
        if m4a_path.parent.name != "assets":
            continue
        lrc_path = m4a_path.with_suffix(".lrc")
        if not lrc_path.is_file():
            result.missing_lrc += 1
            continue
        try:
            changed = embed_lrc_in_m4a(m4a_path, lrc_path)
        except (UnicodeError, ValueError):
            result.invalid_lrc += 1
            continue
        except Exception:  # noqa: BLE001 - one invalid media file must not stop the batch
            result.failed += 1
            continue
        if changed:
            result.updated += 1
        else:
            result.unchanged += 1
    return result

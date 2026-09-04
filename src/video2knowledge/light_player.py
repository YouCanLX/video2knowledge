from __future__ import annotations

import json
import os
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

import httpx
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


@dataclass(slots=True)
class LightPlayerPlaylistSyncResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    matched_songs: int = 0
    unmatched_songs: int = 0
    invalid_metadata: int = 0


@dataclass(frozen=True, slots=True)
class LightPlayerPlaylistGroup:
    name: str
    media_paths: tuple[Path, ...]


class LightPlayerTransferClient:
    """Client for the HTTP API exposed by Light Player's song-transfer screen."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30,
        transport: httpx.BaseTransport | None = None,
    ):
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Light Player URL must be an HTTP or HTTPS URL")
        self.client = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            timeout=timeout,
            transport=transport,
        )

    def __enter__(self) -> LightPlayerTransferClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.client.close()

    def _request(self, method: str, path: str, **kwargs: object) -> object:
        response = self.client.request(method, path, **kwargs)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("code") != 200:
            message = payload.get("message") if isinstance(payload, dict) else "invalid response"
            raise RuntimeError(f"Light Player request failed: {message}")
        return payload.get("data")

    def list_files(self) -> list[dict[str, str]]:
        files: list[dict[str, str]] = []
        pending = [""]
        visited: set[str] = set()
        while pending:
            directory = pending.pop()
            if directory in visited:
                continue
            visited.add(directory)
            data = self._request("GET", "list", params={"path": directory})
            if not isinstance(data, dict) or not isinstance(data.get("list"), list):
                raise RuntimeError("Light Player returned an invalid file listing")
            for raw in data["list"]:
                if not isinstance(raw, dict):
                    continue
                item_type = str(raw.get("type", ""))
                item_path = str(raw.get("path", ""))
                if item_type == "directory" and item_path:
                    pending.append(item_path)
                elif item_type == "file" and item_path:
                    files.append(
                        {
                            "type": "file",
                            "path": item_path,
                            "name": str(raw.get("name") or Path(item_path).name),
                        }
                    )
        return files

    def get_playlists(self) -> dict[str, str]:
        data = self._request("GET", "getPlaylist")
        if not isinstance(data, list):
            raise RuntimeError("Light Player returned an invalid playlist listing")
        playlists: dict[str, str] = {}
        for raw in data:
            if isinstance(raw, dict) and raw.get("name") and raw.get("id"):
                playlists[str(raw["name"])] = str(raw["id"])
        return playlists

    def create_playlist(self, name: str) -> None:
        self._request("POST", "createPlaylist", json={"name": name})

    def add_to_playlist(self, playlist_id: str, items: list[dict[str, str]]) -> None:
        self._request(
            "POST",
            "addToPlaylist",
            json={"playlistId": playlist_id, "items": items},
        )


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


def collect_light_player_playlist_groups(
    library_dir: Path,
) -> tuple[list[LightPlayerPlaylistGroup], int]:
    """Group bundle M4A files by creator and optional collection metadata."""
    library_dir = library_dir.expanduser().resolve()
    grouped: dict[str, list[Path]] = defaultdict(list)
    invalid_metadata = 0
    media_files = sorted(
        path
        for path in library_dir.rglob("*")
        if path.is_file() and path.parent.name == "assets" and path.suffix.casefold() == ".m4a"
    )
    for media_path in media_files:
        creator = ""
        collection = ""
        metadata_paths = [media_path.with_suffix(".metadata.json")]
        metadata_paths.extend(
            path
            for path in sorted(media_path.parent.glob("*.metadata.json"))
            if path not in metadata_paths
        )
        for metadata_path in metadata_paths:
            if not metadata_path.is_file():
                continue
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
                video = payload["video"]
                creator = str(video.get("author") or "").strip()
                collection = str(video.get("collection_title") or "").strip()
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                KeyError,
                TypeError,
                AttributeError,
            ):
                continue
            if creator:
                break
        if not creator:
            try:
                bundle_parts = media_path.parent.parent.relative_to(library_dir).parts
            except ValueError:
                bundle_parts = ()
            if len(bundle_parts) >= 2 and not bundle_parts[0].startswith("."):
                creator = bundle_parts[0]
                collection = bundle_parts[-2] if len(bundle_parts) >= 3 else ""
        if not creator:
            invalid_metadata += 1
            continue
        playlist_name = f"{creator} - {collection}" if collection else creator
        grouped[playlist_name].append(media_path)
    groups = [
        LightPlayerPlaylistGroup(name, tuple(sorted(set(media_paths))))
        for name, media_paths in sorted(grouped.items())
    ]
    return groups, invalid_metadata


def _common_suffix_score(local_path: Path, remote_path: str) -> int:
    local_parts = [part.casefold() for part in local_path.parts]
    remote_parts = [part.casefold() for part in Path(remote_path).parts]
    score = 0
    for local_part, remote_part in zip(reversed(local_parts), reversed(remote_parts), strict=False):
        if local_part != remote_part:
            break
        score += 1
    return score


def _match_remote_item(
    local_path: Path, remote_by_name: dict[str, list[dict[str, str]]]
) -> dict[str, str] | None:
    candidates = remote_by_name.get(local_path.name.casefold(), [])
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        return None
    ranked = sorted(
        ((_common_suffix_score(local_path, item["path"]), item) for item in candidates),
        key=lambda pair: pair[0],
        reverse=True,
    )
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return None
    return ranked[0][1]


def sync_light_player_playlists(
    library_dir: Path,
    light_player_url: str,
    *,
    timeout: float = 30,
    transport: httpx.BaseTransport | None = None,
) -> LightPlayerPlaylistSyncResult:
    """Create/update creator and collection playlists through Light Player's transfer API."""
    groups, invalid_metadata = collect_light_player_playlist_groups(library_dir)
    result = LightPlayerPlaylistSyncResult(invalid_metadata=invalid_metadata)
    with LightPlayerTransferClient(
        light_player_url, timeout=timeout, transport=transport
    ) as client:
        remote_files = client.list_files()
        remote_by_name: dict[str, list[dict[str, str]]] = defaultdict(list)
        for item in remote_files:
            remote_by_name[item["name"].casefold()].append(item)

        matched_groups: dict[str, list[dict[str, str]]] = {}
        for group in groups:
            items_by_path: dict[str, dict[str, str]] = {}
            for media_path in group.media_paths:
                item = _match_remote_item(media_path, remote_by_name)
                if item is None:
                    result.unmatched_songs += 1
                    continue
                items_by_path[item["path"]] = {"type": "file", "path": item["path"]}
                result.matched_songs += 1
            if items_by_path:
                matched_groups[group.name] = list(items_by_path.values())
            else:
                result.skipped += 1

        if result.unmatched_songs or result.invalid_metadata:
            return result

        playlists = client.get_playlists()
        missing_names = [name for name in matched_groups if name not in playlists]
        for name in missing_names:
            client.create_playlist(name)
            result.created += 1
        if missing_names:
            playlists = client.get_playlists()

        for name, items in matched_groups.items():
            playlist_id = playlists.get(name)
            if not playlist_id:
                raise RuntimeError(f"Light Player did not return the created playlist: {name}")
            client.add_to_playlist(playlist_id, items)
            result.updated += 1
    return result

import json
from pathlib import Path

import httpx
import pytest

from video2knowledge import light_player


class FakeMP4:
    tags_by_path: dict[Path, dict[str, list[str]]] = {}

    def __init__(self, path: Path):
        self.path = Path(path)
        stored = self.tags_by_path.get(self.path)
        self.tags = None if stored is None else {key: list(value) for key, value in stored.items()}

    def add_tags(self):
        self.tags = {}

    def save(self):
        assert self.tags is not None
        self.tags_by_path[self.path] = {key: list(value) for key, value in self.tags.items()}


@pytest.fixture(autouse=True)
def reset_fake_mp4():
    FakeMP4.tags_by_path.clear()


def write_pair(directory: Path, stem: str = "video") -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    m4a = directory / f"{stem}.m4a"
    lrc = directory / f"{stem}.lrc"
    m4a.write_bytes(b"synthetic-m4a-audio-payload")
    lrc.write_text("[00:01.25]First line\n[01:02.50]Second line\n", encoding="utf-8")
    return m4a, lrc


def write_bundle_metadata(
    library: Path,
    stem: str,
    creator: str,
    collection: str = "",
    *,
    with_media: bool = True,
) -> Path:
    assets = library / stem / "assets"
    assets.mkdir(parents=True)
    metadata = assets / f"{stem}.metadata.json"
    metadata.write_text(
        json.dumps({"video": {"author": creator, "collection_title": collection}}),
        encoding="utf-8",
    )
    if with_media:
        (assets / f"{stem}.m4a").write_bytes(b"synthetic")
    return metadata


def test_embed_lrc_keeps_sidecar_and_replaces_only_m4a_copy(tmp_path, monkeypatch):
    m4a, lrc = write_pair(tmp_path / "assets")
    metadata = m4a.with_suffix(".metadata.json")
    metadata.write_text('{"source": "synthetic"}\n', encoding="utf-8")
    original_audio = m4a.read_bytes()
    original_lrc = lrc.read_bytes()
    original_metadata = metadata.read_bytes()
    monkeypatch.setattr(light_player, "MP4", FakeMP4)

    assert light_player.embed_lrc_in_m4a(m4a) is True

    assert m4a.read_bytes() == original_audio
    assert lrc.read_bytes() == original_lrc
    assert metadata.read_bytes() == original_metadata
    assert not list(m4a.parent.glob(".v2k-light-player-*"))


def test_embed_lrc_skips_matching_existing_lyrics(tmp_path, monkeypatch):
    m4a, lrc = write_pair(tmp_path / "assets")
    lyrics = lrc.read_text(encoding="utf-8")
    FakeMP4.tags_by_path[m4a.resolve()] = {light_player.MP4_LYRICS_TAG: [lyrics]}
    monkeypatch.setattr(light_player, "MP4", FakeMP4)

    assert light_player.embed_lrc_in_m4a(m4a, lrc) is False


def test_embed_lrc_rejects_text_without_timestamps(tmp_path, monkeypatch):
    m4a, lrc = write_pair(tmp_path / "assets")
    lrc.write_text("No timestamps here\n", encoding="utf-8")
    monkeypatch.setattr(light_player, "MP4", FakeMP4)

    with pytest.raises(ValueError, match="no synchronized lyric lines"):
        light_player.embed_lrc_in_m4a(m4a, lrc)


def test_embed_lrc_keeps_original_when_verification_fails(tmp_path, monkeypatch):
    class UnpersistedMP4(FakeMP4):
        def save(self):
            pass

    m4a, lrc = write_pair(tmp_path / "assets")
    original = m4a.read_bytes()
    monkeypatch.setattr(light_player, "MP4", UnpersistedMP4)

    with pytest.raises(RuntimeError, match="Could not verify"):
        light_player.embed_lrc_in_m4a(m4a, lrc)

    assert m4a.read_bytes() == original
    assert lrc.is_file()
    assert not list(m4a.parent.glob(".v2k-light-player-*"))


def test_export_light_player_reports_each_outcome(tmp_path, monkeypatch):
    assets = tmp_path / "bundle" / "assets"
    updated, _ = write_pair(assets, "updated")
    unchanged, _ = write_pair(assets, "unchanged")
    invalid, _ = write_pair(assets, "invalid")
    failed, _ = write_pair(assets, "failed")
    write_pair(tmp_path / "not-a-bundle", "ignored")
    (assets / "missing.m4a").write_bytes(b"synthetic")

    def fake_embed(m4a_path: Path, _lrc_path: Path) -> bool:
        if m4a_path == invalid:
            raise ValueError("invalid LRC")
        if m4a_path == failed:
            raise RuntimeError("invalid media")
        return m4a_path == updated

    monkeypatch.setattr(light_player, "embed_lrc_in_m4a", fake_embed)

    result = light_player.export_light_player(tmp_path)

    assert result == light_player.LightPlayerExportResult(
        updated=1,
        unchanged=1,
        missing_lrc=1,
        invalid_lrc=1,
        failed=1,
    )
    assert unchanged.is_file()


def test_collect_playlist_groups_combines_creator_and_collection(tmp_path):
    write_bundle_metadata(tmp_path, "course-one", "Creator", "Course")
    write_bundle_metadata(tmp_path, "course-two", "Creator", "Course")
    write_bundle_metadata(tmp_path, "solo", "Creator")
    write_bundle_metadata(tmp_path, "invalid", "")
    write_bundle_metadata(tmp_path, "missing", "Creator", "Other", with_media=False)
    migrated_assets = tmp_path / "Path Creator" / "Path Collection" / "legacy" / "assets"
    migrated_assets.mkdir(parents=True)
    (migrated_assets / "legacy.m4a").write_bytes(b"synthetic")
    creator_only_assets = tmp_path / "Path Only" / "legacy" / "assets"
    creator_only_assets.mkdir(parents=True)
    (creator_only_assets / "legacy-solo.m4a").write_bytes(b"synthetic")

    groups, invalid_metadata = light_player.collect_light_player_playlist_groups(tmp_path)

    assert [(group.name, len(group.media_paths)) for group in groups] == [
        ("Creator", 1),
        ("Creator - Course", 2),
        ("Path Creator - Path Collection", 1),
        ("Path Only", 1),
    ]
    assert invalid_metadata == 1


def test_sync_playlists_creates_missing_groups_and_updates_existing(tmp_path):
    write_bundle_metadata(tmp_path, "course", "Creator", "Course")
    write_bundle_metadata(tmp_path, "solo", "Creator")
    playlists = [{"id": "solo-id", "name": "Creator"}]
    additions: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/list":
            directory = request.url.params.get("path", "")
            listing = (
                [{"type": "directory", "path": "imported", "name": "imported"}]
                if not directory
                else [
                    {"type": "file", "path": "imported/course.m4a", "name": "course.m4a"},
                    {"type": "file", "path": "imported/solo.m4a", "name": "solo.m4a"},
                ]
            )
            return httpx.Response(200, json={"code": 200, "data": {"list": listing}})
        if request.url.path == "/getPlaylist":
            return httpx.Response(200, json={"code": 200, "data": playlists})
        if request.url.path == "/createPlaylist":
            body = json.loads(request.content)
            playlists.append({"id": "course-id", "name": body["name"]})
            return httpx.Response(200, json={"code": 200, "data": None})
        if request.url.path == "/addToPlaylist":
            additions.append(json.loads(request.content))
            return httpx.Response(200, json={"code": 200, "data": None})
        raise AssertionError(f"Unexpected request: {request.url}")

    result = light_player.sync_light_player_playlists(
        tmp_path,
        "http://127.0.0.1:12345",
        transport=httpx.MockTransport(handler),
    )

    assert result == light_player.LightPlayerPlaylistSyncResult(
        created=1,
        updated=2,
        matched_songs=2,
    )
    assert additions == [
        {
            "playlistId": "solo-id",
            "items": [{"type": "file", "path": "imported/solo.m4a"}],
        },
        {
            "playlistId": "course-id",
            "items": [{"type": "file", "path": "imported/course.m4a"}],
        },
    ]


def test_sync_playlists_makes_no_changes_when_a_song_is_unmatched(tmp_path):
    write_bundle_metadata(tmp_path, "matched", "Creator")
    write_bundle_metadata(tmp_path, "unmatched", "Other Creator")
    mutation_requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/list":
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "data": {
                        "list": [
                            {
                                "type": "file",
                                "path": "matched.m4a",
                                "name": "matched.m4a",
                            }
                        ]
                    },
                },
            )
        mutation_requests.append(request.url.path)
        return httpx.Response(200, json={"code": 200, "data": []})

    result = light_player.sync_light_player_playlists(
        tmp_path,
        "http://127.0.0.1:12345",
        transport=httpx.MockTransport(handler),
    )

    assert result.matched_songs == 1
    assert result.unmatched_songs == 1
    assert result.skipped == 1
    assert result.created == 0
    assert result.updated == 0
    assert mutation_requests == []

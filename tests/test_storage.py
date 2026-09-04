import json

from video2knowledge.config import Settings
from video2knowledge.models import JobStatus, VideoItem
from video2knowledge.naming import library_filename_stem, library_relative_directory
from video2knowledge.repository import LibraryRepository
from video2knowledge.storage import migrate_legacy_bundles, supplement_legacy_media


def test_legacy_media_and_generated_assets_move_into_video_bundle(tmp_path):
    (tmp_path / "config.json").write_text(
        json.dumps({"library_dir": "library", "media_dir": "media"}), encoding="utf-8"
    )
    settings = Settings.load(tmp_path)
    repository = LibraryRepository(settings.database_path)
    shared_media = tmp_path / "media" / ".assets" / "ab" / "shared.m4a"
    shared_media.parent.mkdir(parents=True)
    shared_media.write_bytes(b"shared audio")

    records = []
    for source_id, title in (("BV1ONE", "One"), ("BV1TWO", "Two")):
        item = VideoItem("bilibili", source_id, title, "https://example.test", "Author")
        package_dir = settings.library_dir / library_relative_directory(item)
        package_dir.mkdir(parents=True)
        stem = library_filename_stem(item)
        markdown = package_dir / f"{stem}.md"
        lyrics = package_dir / f"{stem}.lrc"
        timeline = package_dir / f"{stem}.json"
        metadata = package_dir / f"{stem}.metadata.json"
        markdown.write_text("# Notes\n", encoding="utf-8")
        lyrics.write_text("[00:00.00]Text\n", encoding="utf-8")
        timeline.write_text("[]", encoding="utf-8")
        metadata.write_text("{}", encoding="utf-8")
        outputs = {
            "markdown": str(markdown),
            "lyrics": str(lyrics),
            "timeline": str(timeline),
            "metadata": str(metadata),
            "source_media": str(shared_media),
        }
        job_id = repository.create_job(item)
        repository.update_job(job_id, JobStatus.COMPLETE, 1, outputs=outputs)
        repository.save_document(item, outputs)
        records.append((item, job_id, markdown))

    moved = migrate_legacy_bundles(settings, repository)

    assert moved == 7
    assert not shared_media.exists()
    for item, job_id, markdown in records:
        package_dir = settings.library_dir / library_relative_directory(item)
        assets_dir = package_dir / "assets"
        stem = library_filename_stem(item)
        assert markdown.exists()
        assert (assets_dir / f"{stem}.m4a").read_bytes() == b"shared audio"
        assert (assets_dir / f"{stem}.lrc").is_file()
        assert (assets_dir / f"{stem}.json").is_file()
        assert (assets_dir / f"{stem}.metadata.json").is_file()
        outputs = repository.get_job(job_id)["outputs"]
        assert outputs["markdown"] == str(markdown)
        assert outputs["source_media"] == str((assets_dir / f"{stem}.m4a").resolve())


def test_supplemental_migration_matches_media_and_quarantines_unknown_files(tmp_path):
    (tmp_path / "config.json").write_text(
        json.dumps({"library_dir": "library", "media_dir": "media"}), encoding="utf-8"
    )
    settings = Settings.load(tmp_path)
    repository = LibraryRepository(settings.database_path)
    items = [
        VideoItem("bilibili", "BV1ABC2DEF34", "ID Match", "https://example.test", "Author"),
        VideoItem(
            "bilibili",
            "SRC-FILENAME",
            "Unique Filename Course",
            "https://example.test",
            "Author",
        ),
        VideoItem(
            "bilibili",
            "SRC-METADATA",
            "Unique Metadata Course",
            "https://example.test",
            "Author",
        ),
    ]
    legacy_files = [
        tmp_path / "media" / "download_BV1ABC2DEF34.m4a",
        tmp_path / "media" / "Unique Filename Course.m4a",
        tmp_path / "media" / "opaque.m4a",
    ]
    for item, media in zip(items, legacy_files, strict=True):
        media.parent.mkdir(parents=True, exist_ok=True)
        media.write_bytes(item.source_id.encode())
        job_id = repository.create_job(item)
        repository.update_job(job_id, JobStatus.COMPLETE, 1, outputs={"source_media": str(media)})

    id_destination = (
        settings.library_dir
        / library_relative_directory(items[0])
        / "assets"
        / f"{library_filename_stem(items[0])}.m4a"
    )
    id_destination.parent.mkdir(parents=True)
    id_destination.write_bytes(items[0].source_id.encode())
    unknown = tmp_path / "media" / "unknown.m4a"
    unknown.write_bytes(b"unknown")
    (tmp_path / "media" / ".DS_Store").write_bytes(b"metadata")
    existing_quarantine = settings.library_dir / ".unmatched-media" / "unknown.m4a"
    existing_quarantine.parent.mkdir(parents=True)
    existing_quarantine.write_bytes(b"existing")

    result = supplement_legacy_media(
        settings,
        repository,
        metadata_reader=lambda path: "Unique Metadata Course" if path.name == "opaque.m4a" else "",
    )

    assert result == {
        "matched_by_id": 1,
        "matched_by_filename": 1,
        "matched_by_metadata": 1,
        "identical_duplicates": 1,
        "quarantined": 1,
        "legacy_dir_removed": True,
    }
    assert not (tmp_path / "media").exists()
    assert existing_quarantine.read_bytes() == b"existing"
    assert existing_quarantine.with_name("unknown-1.m4a").read_bytes() == b"unknown"
    for item in items:
        destination = (
            settings.library_dir
            / library_relative_directory(item)
            / "assets"
            / f"{library_filename_stem(item)}.m4a"
        )
        assert destination.is_file()
        assert repository.get_download_history(item.source_id)["outputs"]["source_media"] == str(
            destination.resolve()
        )

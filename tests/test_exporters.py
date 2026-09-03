import json
from pathlib import Path

from video2knowledge.exporters import (
    format_clock,
    format_lrc_time,
    format_video_created_at,
    parse_markdown_text,
    render_lrc,
    render_markdown,
    write_bundle,
)
from video2knowledge.models import Enrichment, KnowledgeDocument, TranscriptSegment, VideoItem
from video2knowledge.naming import (
    library_filename_stem,
    library_relative_directory,
    library_stem,
)


def document():
    video = VideoItem(
        "bilibili",
        "BV1test",
        "Test Title",
        "https://example.test",
        "Author",
        published_at="1735689600",
        tags=["AI"],
    )
    return KnowledgeDocument(
        video,
        [
            TranscriptSegment(1.25, 3.5, "First sentence"),
            TranscriptSegment(64, 68, "Second sentence", "S1"),
        ],
        Enrichment(summary=["Key point", "Second point"], questions=["Why?"]),
    )


def test_time_formats():
    assert format_clock(3661.234) == "01:01:01.234"
    assert format_lrc_time(64.12) == "01:04.12"
    assert format_video_created_at("1735689600") == "2025-01-01T00:00:00+00:00"


def test_render_outputs_include_timeline_and_enrichment():
    doc = document()
    markdown = render_markdown(doc)
    lyrics = render_lrc(
        doc.segments,
        doc.video.title,
        doc.video.author,
        format_video_created_at(doc.video.published_at),
    )
    assert "## Core Summary" in markdown
    assert "background-color:#fff7d6;color:#4a3b00" in markdown
    assert "border-left:5px solid #d9a900" in markdown
    assert "list-style-type:disc" in markdown
    assert '<li style="margin:0.35em 0;padding-left:0.2em">Key point</li>' in markdown
    assert '<li style="margin:0.35em 0;padding-left:0.2em">Second point</li>' in markdown
    assert "\n- Key point\n" not in markdown
    assert 'video_created_at: "2025-01-01T00:00:00+00:00"' in markdown
    assert "Video created: **2025-01-01T00:00:00+00:00**" in markdown
    assert "`00:00:01.250`" in markdown
    assert "[date:2025-01-01T00:00:00+00:00]" in lyrics
    assert "[01:04.00]Second sentence" in lyrics


def test_render_markdown_escapes_enrichment_list_content():
    doc = document()
    unsafe = "First & <claim> \"quoted\" 'single' </li><li>injected"
    doc.enrichment.summary = [unsafe]
    doc.enrichment.insights = [unsafe]
    doc.enrichment.suggestions = [unsafe]
    doc.enrichment.questions = [unsafe]

    markdown = render_markdown(doc)

    escaped = (
        "First &amp; &lt;claim&gt; &quot;quoted&quot; &#x27;single&#x27; "
        "&lt;/li&gt;&lt;li&gt;injected"
    )
    assert markdown.count("<ul ") == 4
    assert markdown.count("<li ") == 4
    assert markdown.count(f">{escaped}</li>") == 4
    assert unsafe not in markdown


def test_write_bundle_includes_video_creation_metadata(tmp_path):
    outputs = write_bundle(document(), tmp_path)
    metadata = json.loads(outputs["metadata"].read_text(encoding="utf-8"))

    assert metadata["video_created_at"] == "2025-01-01T00:00:00+00:00"
    assert metadata["video"]["published_at"] == "1735689600"
    timeline = json.loads(outputs["timeline"].read_text(encoding="utf-8"))
    assert timeline[0]["text"] == "First sentence"


def test_parse_markdown_for_speech():
    source = (
        "---\ntitle: Test\n---\n# Heading\n\n- **Key** [Link](https://example.com)\n<div>Tip</div>"
    )
    assert parse_markdown_text(source) == ["Heading", "Key Link", "Tip"]


def test_library_stem_contains_author_title_and_video_id():
    assert library_stem(document().video) == "Author_Test Title_BV1test"


def test_collection_is_added_to_filename_stem():
    item = document().video
    item.collection_id = 12
    item.collection_title = "Trading/Course"

    assert library_stem(item) == "Author_Test Title_BV1test"
    assert library_filename_stem(item) == "Author_Trading-Course_Test Title_BV1test"


def test_library_directory_uses_author_and_collection_hierarchy():
    item = document().video
    item.collection_id = 12
    item.collection_title = "Trading/Course"

    assert library_relative_directory(item) == (
        Path("Author") / "Trading-Course" / "Author_Trading-Course_Test Title_BV1test"
    )


def test_library_directory_without_collection_uses_author_hierarchy():
    assert library_relative_directory(document().video) == Path("Author/Author_Test Title_BV1test")


def test_bundle_uses_collection_filename_inside_unchanged_directory(tmp_path):
    doc = document()
    doc.video.collection_id = 12
    doc.video.collection_title = "Trading Course"
    directory = tmp_path / library_stem(doc.video)

    outputs = write_bundle(doc, directory)

    assert directory.name == "Author_Test Title_BV1test"
    assert outputs["markdown"].name == "Author_Trading Course_Test Title_BV1test.md"
    assert all(path.parent == directory for path in outputs.values())


def test_library_stem_replaces_path_characters_and_limits_utf8_bytes():
    item = VideoItem(
        "bilibili", "BV/1", "Title:" + "Long" * 100, "https://example.test", "Creator/Name"
    )
    stem = library_stem(item)
    assert stem.startswith("Creator-Name_Title-")
    assert stem.endswith("_BV-1")
    assert len(stem.encode("utf-8")) <= 220

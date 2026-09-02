from video2knowledge.exporters import (
    format_clock,
    format_lrc_time,
    parse_markdown_text,
    render_lrc,
    render_markdown,
)
from video2knowledge.models import Enrichment, KnowledgeDocument, TranscriptSegment, VideoItem
from video2knowledge.naming import library_stem


def document():
    video = VideoItem(
        "bilibili", "BV1test", "Test Title", "https://example.test", "Author", tags=["AI"]
    )
    return KnowledgeDocument(
        video,
        [
            TranscriptSegment(1.25, 3.5, "First sentence"),
            TranscriptSegment(64, 68, "Second sentence", "S1"),
        ],
        Enrichment(summary=["Key point"], questions=["Why?"]),
    )


def test_time_formats():
    assert format_clock(3661.234) == "01:01:01.234"
    assert format_lrc_time(64.12) == "01:04.12"


def test_render_outputs_include_timeline_and_enrichment():
    doc = document()
    markdown = render_markdown(doc)
    lyrics = render_lrc(doc.segments, doc.video.title, doc.video.author)
    assert "## Core Summary" in markdown
    assert "`00:00:01.250`" in markdown
    assert "[01:04.00]Second sentence" in lyrics


def test_parse_markdown_for_speech():
    source = (
        "---\ntitle: Test\n---\n# Heading\n\n- **Key** [Link](https://example.com)\n<div>Tip</div>"
    )
    assert parse_markdown_text(source) == ["Heading", "Key Link", "Tip"]


def test_library_stem_contains_author_title_and_video_id():
    assert library_stem(document().video) == "Author_Test Title_BV1test"


def test_library_stem_replaces_path_characters_and_limits_utf8_bytes():
    item = VideoItem(
        "bilibili", "BV/1", "Title:" + "Long" * 100, "https://example.test", "Creator/Name"
    )
    stem = library_stem(item)
    assert stem.startswith("Creator-Name_Title-")
    assert stem.endswith("_BV-1")
    assert len(stem.encode("utf-8")) <= 220

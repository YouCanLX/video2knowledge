from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from html import escape
from pathlib import Path

from .models import KnowledgeDocument, TranscriptSegment
from .naming import library_filename_stem


def escape_html_list_item(value: str) -> str:
    """Escape enrichment text before placing it inside an HTML list item."""
    return escape(str(value), quote=True)


def format_clock(seconds: float) -> str:
    total_ms = max(0, round(seconds * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def format_lrc_time(seconds: float) -> str:
    total_cs = max(0, round(seconds * 100))
    minutes, rem = divmod(total_cs, 6000)
    secs, centis = divmod(rem, 100)
    return f"{minutes:02d}:{secs:02d}.{centis:02d}"


def format_video_created_at(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return datetime.fromtimestamp(float(raw), UTC).isoformat(timespec="seconds")
    except (OverflowError, ValueError):
        pass
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.isoformat(timespec="seconds")


def render_lrc(
    segments: list[TranscriptSegment],
    title: str = "",
    author: str = "",
    video_created_at: str = "",
) -> str:
    lines = [f"[ti:{title}]", f"[ar:{author}]", "[by:video2knowledge]"]
    if video_created_at:
        lines.append(f"[date:{video_created_at}]")
    lines.extend(f"[{format_lrc_time(s.start)}]{s.text}" for s in segments if s.text)
    return "\n".join(lines) + "\n"


def render_markdown(document: KnowledgeDocument) -> str:
    v = document.video
    tags = " ".join(f"`{tag}`" for tag in v.tags)
    video_created_at = format_video_created_at(v.published_at)
    parts = [
        "---",
        f'title: "{v.title.replace(chr(34), chr(39))}"',
        f"source: {v.url}",
        f"platform: {v.platform}",
        f"source_id: {v.source_id}",
        f"author: {v.author}",
        *([f'video_created_at: "{video_created_at}"'] if video_created_at else []),
        f"language: {document.language}",
        f"created_at: {document.created_at}",
        "---",
        "",
        f"# {v.title}",
        "",
        (
            f"> Source: [{v.platform}]({v.url}) | Author: **{v.author or 'Unknown'}**"
            + (f" | Video created: **{video_created_at}**" if video_created_at else "")
        ),
        "",
    ]
    if tags:
        parts += [f"Tags: {tags}", ""]
    sections = [
        ("Core Summary", document.enrichment.summary, "#fff7d6", "#4a3b00", "#d9a900"),
        ("Further Insights", document.enrichment.insights, "#eaf4ff", "#173a5e", "#4b8ccb"),
        (
            "Actionable Suggestions",
            document.enrichment.suggestions,
            "#eaf8f0",
            "#174a2d",
            "#45a36a",
        ),
        (
            "Questions to Explore",
            document.enrichment.questions,
            "#f7ecfa",
            "#52245d",
            "#a45ab3",
        ),
    ]
    for heading, values, background, foreground, accent in sections:
        if values:
            card_style = (
                f"background-color:{background};color:{foreground};"
                f"border:1px solid {accent};border-left:5px solid {accent};"
                "padding:14px 18px;border-radius:10px;line-height:1.75;"
                "box-shadow:0 2px 8px rgba(0,0,0,0.10)"
            )
            parts += [
                f"## {heading}",
                "",
                f'<div style="{card_style}">',
                (
                    '<ul style="margin:0;padding-left:1.45em;'
                    'list-style-type:disc;list-style-position:outside">'
                ),
            ]
            parts.extend(
                f'<li style="margin:0.35em 0;padding-left:0.2em">'
                f"{escape_html_list_item(value)}</li>"
                for value in values
            )
            parts += ["</ul>", "</div>", ""]
    parts += ["## Full Transcript with Timeline", ""]
    for segment in document.segments:
        speaker = f"**{segment.speaker}** " if segment.speaker else ""
        parts.append(f"- [`{format_clock(segment.start)}`] {speaker}{segment.text}")
    return "\n".join(parts).rstrip() + "\n"


def parse_markdown_text(markdown_text: str) -> list[str]:
    """Extract speakable paragraphs while skipping metadata and raw HTML."""
    text = re.sub(r"\A---\n.*?\n---\n", "", markdown_text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    lines: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"^#{1,6}\s+", "", raw.strip())
        line = re.sub(r"^[-*>]\s*", "", line)
        line = re.sub(r"\[([^]]+)]\([^)]+\)", r"\1", line)
        line = re.sub(r"[`*_~]", "", line).strip()
        if line:
            lines.append(line)
    return lines


def write_bundle(document: KnowledgeDocument, directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    slug = library_filename_stem(document.video)
    md_path, lrc_path, json_path, metadata_path = (
        directory / f"{slug}{suffix}"
        for suffix in (".md", ".lrc", ".json", ".metadata.json")
    )
    video_created_at = format_video_created_at(document.video.published_at)
    md_path.write_text(render_markdown(document), encoding="utf-8")
    lrc_path.write_text(
        render_lrc(
            document.segments,
            document.video.title,
            document.video.author,
            video_created_at,
        ),
        encoding="utf-8",
    )
    json_path.write_text(
        json.dumps([s.to_dict() for s in document.segments], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    metadata_path.write_text(
        json.dumps(
            {
                "video": document.video.to_dict(),
                "video_created_at": video_created_at,
                "library_created_at": document.created_at,
                "language": document.language,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "markdown": md_path,
        "lyrics": lrc_path,
        "timeline": json_path,
        "metadata": metadata_path,
    }

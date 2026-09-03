from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .exporters import render_lrc
from .models import KnowledgeDocument
from .naming import library_filename_stem


def export_apple_music(
    document: KnowledgeDocument, wav_path: Path, output_dir: Path
) -> dict[str, Path]:
    """Create an Apple Music-importable AAC file plus synchronized LRC sidecar."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("Apple Music export requires ffmpeg")
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = library_filename_stem(document.video)
    m4a, lrc = output_dir / f"{stem}.m4a", output_dir / f"{stem}.lrc"
    plain_lyrics = "\n".join(segment.text for segment in document.segments)
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(wav_path),
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-metadata",
        f"title={document.video.title}",
        "-metadata",
        f"artist={document.video.author}",
        "-metadata",
        f"lyrics={plain_lyrics}",
        "-metadata",
        f"language={document.language}",
        str(m4a),
    ]
    subprocess.run(command, check=True, capture_output=True)
    lrc.write_text(
        render_lrc(document.segments, document.video.title, document.video.author), encoding="utf-8"
    )
    return {"apple_music": m4a, "lyrics": lrc}

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .config import SpeechMediaOptions
from .exporters import render_lrc
from .models import KnowledgeDocument
from .naming import library_filename_stem


def export_apple_music(
    document: KnowledgeDocument,
    wav_path: Path,
    output_dir: Path,
    *,
    options: SpeechMediaOptions | None = None,
) -> dict[str, Path]:
    """Create an Apple Music-importable AAC file plus synchronized LRC sidecar."""
    options = options or SpeechMediaOptions()
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("Apple Music export requires ffmpeg")
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = library_filename_stem(document.video)
    m4a, lrc = output_dir / f"{stem}.m4a", output_dir / f"{stem}.lrc"
    lyrics = render_lrc(document.segments, document.video.title, document.video.author)
    embedded_lyrics = (
        lyrics
        if options.media_lyrics_mode == "synced"
        else "\n".join(segment.text for segment in document.segments)
    )
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(wav_path),
        "-map",
        "0:a:0",
        "-vn",
        "-map_metadata",
        "-1",
        "-c:a",
        "aac",
        "-b:a",
        f"{options.media_audio_bitrate_kbps}k",
        "-metadata",
        f"title={document.video.title}",
        "-metadata",
        f"artist={document.video.author}",
        "-metadata",
        f"language={document.language}",
    ]
    if options.media_lyrics_mode != "none":
        command += ["-metadata", f"lyrics={embedded_lyrics}"]
    if options.media_sample_rate is not None:
        command += ["-ar", str(options.media_sample_rate)]
    if options.media_channels is not None:
        command += ["-ac", str(options.media_channels)]
    command.append(str(m4a))
    subprocess.run(command, check=True, capture_output=True)
    lrc.write_text(
        render_lrc(document.segments, document.video.title, document.video.author), encoding="utf-8"
    )
    return {"apple_music": m4a, "lyrics": lrc}

import subprocess

import pytest

import video2knowledge.apple_music as module
from video2knowledge.config import SpeechMediaOptions
from video2knowledge.models import KnowledgeDocument, TranscriptSegment, VideoItem


@pytest.mark.parametrize("mode", ["plain", "synced", "none"])
def test_configurable_m4a_export(tmp_path, monkeypatch, mode):
    calls = []
    monkeypatch.setattr(module.shutil, "which", lambda _: "ffmpeg")
    monkeypatch.setattr(module.subprocess, "run", lambda command, **kw: calls.append((command, kw)))
    document = KnowledgeDocument(
        VideoItem("markdown", "synthetic", "Lesson", "https://example.com", "Creator"),
        [TranscriptSegment(0, 1, "First"), TranscriptSegment(1, 3, "Second")],
    )
    outputs = module.export_apple_music(
        document,
        tmp_path / "speech.wav",
        tmp_path,
        options=SpeechMediaOptions(
            media_audio_bitrate_kbps=128,
            media_sample_rate=24000,
            media_channels=1,
            media_lyrics_mode=mode,
        ),
    )
    command, kwargs = calls[0]
    assert kwargs == {"check": True, "capture_output": True}
    assert command[command.index("-b:a") + 1] == "128k"
    assert command[command.index("-ar") + 1] == "24000"
    assert command[command.index("-ac") + 1] == "1"
    assert command[command.index("-map_metadata") + 1] == "-1"
    lyrics = outputs["lyrics"].read_text()
    assert "[00:01.00]Second" in lyrics
    embedded = [arg for arg in command if arg.startswith("lyrics=")]
    assert (
        embedded
        == ({"plain": ["lyrics=First\nSecond"], "synced": [f"lyrics={lyrics}"], "none": []}[mode])
    )


def test_default_export_and_encoder_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(module.shutil, "which", lambda _: "ffmpeg")
    document = KnowledgeDocument(VideoItem("markdown", "synthetic", "Lesson", ""), [])

    def fail(command, **kwargs):
        assert command[command.index("-b:a") + 1] == "192k"
        assert "-ar" not in command and "-ac" not in command
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(module.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        module.export_apple_music(document, tmp_path / "speech.wav", tmp_path)
    assert not list(tmp_path.glob("*.lrc"))

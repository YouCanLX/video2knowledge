from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import video2knowledge.cli as module
from video2knowledge.config import Settings


@pytest.mark.parametrize(
    ("configured", "flags", "expected"),
    [
        (False, [], False),
        (False, ["--apple-music"], True),
        (True, ["--no-apple-music"], False),
        (True, [], True),
    ],
)
def test_speak_overrides_are_temporary(tmp_path, monkeypatch, configured, flags, expected):
    monkeypatch.setenv("V2K_DATA_DIR", str(tmp_path))
    settings = Settings.load(tmp_path)
    settings.apple_music_enabled = configured
    settings.save()
    note = tmp_path / "note.md"
    note.write_text("# Synthetic note\n\nExample text.")
    captured = []
    exports = []

    class Audio:
        def synthesize(self, segments, path, language):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic audio")
            for index, segment in enumerate(segments):
                segment.start, segment.end = index, index + 1
            return path

    def build(settings):
        captured.append(settings.speech_media_options())
        return SimpleNamespace(audio=Audio())

    def export(document, wav, directory, *, options):
        exports.append(options)
        assert wav.exists()
        assert list(directory.glob("*.json"))
        return {}

    monkeypatch.setattr(module, "build_services", build)
    monkeypatch.setattr(module, "export_apple_music", export)
    result = CliRunner().invoke(
        module.app,
        [
            "speak",
            str(note),
            "--voice",
            "SyntheticVoice",
            "--speed",
            "1.5",
            "--audio-bitrate-kbps",
            "128",
            "--sample-rate",
            "24000",
            "--channels",
            "1",
            "--lyrics-mode",
            "synced",
            *flags,
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured[0].mlx_tts_voice == "SyntheticVoice"
    assert captured[0].mlx_tts_speed == 1.5
    assert captured[0].media_audio_bitrate_kbps == 128
    assert captured[0].media_sample_rate == 24000
    assert captured[0].media_channels == 1
    assert captured[0].media_lyrics_mode == "synced"
    assert bool(exports) is expected
    assert Settings.load(tmp_path).speech_media_options() == settings.speech_media_options()


def test_speak_rejects_invalid_override_before_building_services(tmp_path, monkeypatch):
    monkeypatch.setenv("V2K_DATA_DIR", str(tmp_path))

    def unexpected(_):
        pytest.fail("Invalid options must fail before service initialization")

    monkeypatch.setattr(module, "build_services", unexpected)
    result = CliRunner().invoke(module.app, ["speak", str(tmp_path / "note.md"), "--speed", "0"])
    assert result.exit_code == 2
    assert "mlx_tts_speed" in result.output

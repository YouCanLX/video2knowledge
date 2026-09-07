import json

import pytest

from video2knowledge.config import DEFAULT_MLX_AUDIO_COMMAND, Settings, default_data_dir


def test_settings_resolve_relative_paths_from_data_directory(tmp_path):
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "library_dir": "knowledge",
                "media_dir": "downloads",
                "database_path": "state/library.db",
                "cookie_file": "secrets/bilibili-cookies.txt",
                "mlx_base_url": "http://127.0.0.1:9000",
                "mlx_audio_command": "python -m mlx_audio.server --port 9000",
            }
        ),
        encoding="utf-8",
    )

    settings = Settings.load(tmp_path)

    assert settings.library_dir == (tmp_path / "knowledge").resolve()
    assert settings.legacy_media_dir == (tmp_path / "downloads").resolve()
    assert settings.database_path == (tmp_path / "state/library.db").resolve()
    assert settings.cookie_file == (tmp_path / "secrets/bilibili-cookies.txt").resolve()
    assert settings.mlx_base_url == "http://127.0.0.1:9000"
    assert settings.mlx_audio_command == "python -m mlx_audio.server --port 9000"


def test_settings_save_portable_paths(tmp_path):
    settings = Settings.load(tmp_path)
    settings.cookie_file = tmp_path / "bilibili-cookies.txt"

    settings.save()

    payload = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert payload["library_dir"] == "library"
    assert "media_dir" not in payload
    assert payload["database_path"] == "library.db"
    assert payload["cookie_file"] == "bilibili-cookies.txt"
    assert payload["mlx_audio_command"] == DEFAULT_MLX_AUDIO_COMMAND
    assert "data_dir" not in payload


def test_default_data_dir_uses_environment_override(monkeypatch, tmp_path):
    monkeypatch.setenv("V2K_DATA_DIR", str(tmp_path))
    assert default_data_dir() == tmp_path


def test_default_data_dir_uses_current_project_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("V2K_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert default_data_dir() == tmp_path / "video2knowledge-data"


def test_settings_reject_non_object_configuration(tmp_path):
    (tmp_path / "config.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        Settings.load(tmp_path)


def test_speech_media_options_round_trip(tmp_path):
    settings = Settings.load(tmp_path)
    assert settings.mlx_tts_speed == 1
    assert settings.mlx_tts_timeout_seconds is None
    assert settings.apple_music_enabled is True
    settings.mlx_tts_voice = "SyntheticVoice"
    settings.mlx_tts_speed = 1.5
    settings.mlx_tts_timeout_seconds = 120
    settings.apple_music_enabled = False
    settings.media_audio_bitrate_kbps = 128
    settings.media_sample_rate = 24000
    settings.media_channels = 1
    settings.media_lyrics_mode = "synced"
    settings.save()
    assert Settings.load(tmp_path).speech_media_options() == settings.speech_media_options()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mlx_tts_voice", "  "),
        ("mlx_tts_model", ""),
        ("mlx_tts_speed", 0),
        ("mlx_tts_speed", 5),
        ("mlx_tts_speed", float("nan")),
        ("mlx_tts_timeout_seconds", -1),
        ("mlx_tts_timeout_seconds", float("inf")),
        ("apple_music_enabled", "false"),
        ("media_audio_bitrate_kbps", 0),
        ("media_audio_bitrate_kbps", 128.5),
        ("media_sample_rate", 12345),
        ("media_channels", 3),
        ("media_lyrics_mode", "invalid"),
    ],
)
def test_invalid_speech_media_config_is_rejected(tmp_path, field, value):
    (tmp_path / "config.json").write_text(json.dumps({field: value}), encoding="utf-8")
    with pytest.raises(ValueError, match=field):
        Settings.load(tmp_path)

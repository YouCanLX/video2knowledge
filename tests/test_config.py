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
    assert settings.media_dir == (tmp_path / "downloads").resolve()
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
    assert payload["media_dir"] == "media"
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

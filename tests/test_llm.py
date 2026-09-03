import asyncio
import os

import pytest

import video2knowledge.adapters.llm as llm_module
from video2knowledge.adapters.llm import (
    CodexCliEnricher,
    _parse_enrichment,
    _resolve_codex_executable,
)


def test_codex_cli_enricher_uses_structured_stdout(tmp_path):
    executable = tmp_path / "fake-codex"
    executable.write_text(
        "#!/bin/sh\n"
        "cat >/dev/null\n"
        'printf \'%s\\n\' \'{"summary":["Summary"],"insights":["Insight"],'
        '"suggestions":["Suggestion"],"questions":["Question"]}\'\n',
        encoding="utf-8",
    )
    os.chmod(executable, 0o755)

    result = asyncio.run(
        CodexCliEnricher(str(executable), timeout_seconds=5).enrich("Title", "Body", "en")
    )

    assert result.summary == ["Summary"]
    assert result.insights == ["Insight"]
    assert result.suggestions == ["Suggestion"]
    assert result.questions == ["Question"]


def test_parse_enrichment_rejects_non_array_fields():
    with pytest.raises(ValueError, match="summary"):
        _parse_enrichment('{"summary":"invalid","insights":[],"suggestions":[],"questions":[]}')


def test_codex_cli_falls_back_to_macos_app_bundle(tmp_path, monkeypatch):
    executable = tmp_path / "codex"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    os.chmod(executable, 0o755)
    monkeypatch.setattr(llm_module.shutil, "which", lambda _value: None)
    monkeypatch.setattr(llm_module, "MACOS_CODEX_CANDIDATES", (str(executable),))

    assert _resolve_codex_executable("codex") == str(executable)


def test_custom_missing_codex_path_does_not_use_bundle_fallback(monkeypatch):
    monkeypatch.setattr(llm_module.shutil, "which", lambda _value: None)

    assert _resolve_codex_executable("missing-custom-codex") is None

import asyncio
import os

import pytest

from video2knowledge.adapters.llm import CodexCliEnricher, _parse_enrichment


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

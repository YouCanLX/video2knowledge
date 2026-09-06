from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

import httpx

from ..models import Enrichment
from ..ports import TextEnricher

if TYPE_CHECKING:
    from ..config import Settings

ENRICHMENT_FIELDS = ("summary", "insights", "suggestions", "questions", "tags")
MACOS_CODEX_CANDIDATES = (
    "/Applications/ChatGPT.app/Contents/Resources/codex",
    "/Applications/Codex.app/Contents/Resources/codex",
    "~/Applications/ChatGPT.app/Contents/Resources/codex",
    "~/Applications/Codex.app/Contents/Resources/codex",
)
ENRICHMENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        **{field: {"type": "array", "items": {"type": "string"}} for field in ENRICHMENT_FIELDS},
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 6,
        },
    },
    "required": list(ENRICHMENT_FIELDS),
}
TAG_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 6,
        }
    },
    "required": ["tags"],
}


def _build_prompt(title: str, text: str, language: str) -> str:
    return f"""You are an editor for a personal knowledge library.
Summarize only the transcript below. Do not read files, call tools, or browse the web.
The output must satisfy the supplied JSON Schema. Every field is an array of strings:
- summary: 3-7 core takeaways
- insights: further deductions, clearly distinguished from source claims
- suggestions: actionable suggestions
- questions: questions worth exploring
- tags: 3-6 short, complete, reusable topic concepts; use canonical domain terms rather than
  sentences or fragments copied from the title
Write in {language}. Clearly distinguish source claims from deductions.
Never invent facts absent from the transcript.
Title: {title}

Transcript:
{text[:50000]}"""


def _build_tag_prompt(title: str, text: str, language: str) -> str:
    return f"""Create 3-6 topic tags for this Markdown document using only its content.
Write short, complete, reusable concept names in {language}: 2-8 Chinese characters or 1-3
English words. Prefer established domain terms and use the same canonical wording for the same
concept across documents. Use noun phrases, not sentences, questions, claims, or truncated title
and heading fragments. Exclude #, author, collection, platform, generic labels, IDs, standalone
numbers, and hexadecimal color values. Do not invent absent topics.
Return only a JSON object with one `tags` array.
Title: {title}

Document:
{text[:50000]}"""


def _parse_enrichment(content: str) -> Enrichment:
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0]
    data = json.loads(content)
    if not isinstance(data, dict):
        raise TypeError("LLM enrichment must be a JSON object")
    values: dict[str, list[str]] = {}
    for field in ENRICHMENT_FIELDS:
        field_value = data.get(field)
        if not isinstance(field_value, list) or not all(
            isinstance(value, str) for value in field_value
        ):
            raise ValueError(f"LLM enrichment field {field} must be an array of strings")
        values[field] = field_value
    if not 3 <= len(values["tags"]) <= 6:
        raise ValueError("LLM enrichment tags must contain 3-6 strings")
    return Enrichment(**values)


def _parse_tags(content: str) -> list[str]:
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0]
    data = json.loads(content)
    tags = data.get("tags") if isinstance(data, dict) else None
    if (
        not isinstance(tags, list)
        or not 3 <= len(tags) <= 6
        or not all(isinstance(tag, str) and tag.strip() for tag in tags)
    ):
        raise ValueError("LLM tags must contain 3-6 non-empty strings")
    return tags


def _resolve_codex_executable(configured: str) -> str | None:
    """Resolve Codex from PATH or the standard macOS application bundles."""
    executable = shutil.which(configured)
    if executable or configured != "codex":
        return executable
    for candidate in MACOS_CODEX_CANDIDATES:
        path = Path(candidate).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


class OpenAICompatibleEnricher:
    def __init__(self, base_url: str, model: str):
        self.base_url, self.model = base_url.rstrip("/"), model

    async def enrich(self, title: str, text: str, language: str) -> Enrichment:
        prompt = _build_prompt(title, text, language)
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                },
            )
        response.raise_for_status()
        return _parse_enrichment(response.json()["choices"][0]["message"]["content"])

    async def generate_tags(self, title: str, text: str, language: str) -> list[str]:
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "user", "content": _build_tag_prompt(title, text, language)}
                    ],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                },
            )
        response.raise_for_status()
        return _parse_tags(response.json()["choices"][0]["message"]["content"])


class CodexCliEnricher:
    """Generate knowledge enrichment through the locally installed Codex CLI."""

    def __init__(
        self,
        executable: str = "codex",
        model: str = "",
        timeout_seconds: float = 900,
    ):
        self.executable = executable
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def enrich(self, title: str, text: str, language: str) -> Enrichment:
        content = await self._execute(
            _build_prompt(title, text, language), ENRICHMENT_SCHEMA, "enrichment"
        )
        return _parse_enrichment(content)

    async def generate_tags(self, title: str, text: str, language: str) -> list[str]:
        content = await self._execute(
            _build_tag_prompt(title, text, language), TAG_SCHEMA, "tag generation"
        )
        return _parse_tags(content)

    async def _execute(self, prompt: str, schema: dict, operation: str) -> str:
        executable = _resolve_codex_executable(self.executable)
        if not executable:
            raise RuntimeError(f"Codex CLI was not found: {self.executable}")

        with TemporaryDirectory(prefix="v2k-codex-") as tmp:
            workdir = Path(tmp)
            schema_path = workdir / "enrichment.schema.json"
            schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
            command = [
                executable,
                "exec",
                "--ephemeral",
                "--ignore-user-config",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--color",
                "never",
                "--output-schema",
                str(schema_path),
            ]
            if self.model:
                command.extend(("--model", self.model))
            command.append("-")
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=workdir,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(prompt.encode()),
                    timeout=self.timeout_seconds,
                )
            except TimeoutError as exc:
                process.kill()
                await process.communicate()
                raise RuntimeError(
                    f"Codex CLI {operation} exceeded {self.timeout_seconds:g} seconds"
                ) from exc
            if process.returncode:
                detail = stderr.decode(errors="replace").strip()[-2000:]
                raise RuntimeError(
                    f"Codex CLI {operation} failed with exit code {process.returncode}: {detail}"
                )
            return stdout.decode()


def create_enricher(settings: Settings) -> TextEnricher:
    if settings.llm_backend == "codex_cli":
        return CodexCliEnricher(
            settings.codex_cli_path,
            settings.codex_model,
            settings.codex_timeout_seconds,
        )
    if settings.llm_backend == "openai_compatible":
        return OpenAICompatibleEnricher(settings.llm_base_url, settings.llm_model)
    raise ValueError(f"Unknown LLM backend: {settings.llm_backend}")


class NoopEnricher:
    async def enrich(self, title: str, text: str, language: str) -> Enrichment:
        return Enrichment(
            summary=["No local LLM is configured; the full transcript was preserved."]
        )

    async def generate_tags(self, title: str, text: str, language: str) -> list[str]:
        return []

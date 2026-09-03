# Contributing

Thank you for improving Video2Knowledge. The project is currently an alpha and favors small,
reviewable changes that preserve local-first behavior and platform authorization boundaries.

## Development setup

```bash
uv sync --extra bilibili --extra audio --extra dev
source .venv/bin/activate
```

Do not use real credentials or downloaded media in tests. Tests should use temporary
directories and fake adapters.

## Before opening a pull request

```bash
pytest
ruff check .
ruff format --check .
python -m build
```

Keep these conventions:

- Use `snake_case` for modules, functions, variables, and configuration keys.
- Use `PascalCase` for classes and protocols.
- Keep platform and model-specific code under `adapters/`.
- Depend on contracts from `ports.py` in orchestration code.
- Preserve transcripts when optional enrichment fails.
- Add tests for behavior changes and update user-facing documentation.
- Add user-visible features, fixes, and breaking changes to `CHANGELOG.md` and
  `CHANGELOG.zh-CN.md`, including the commit hash once it is known.
- Keep source code, messages, and documentation in English.

## Commit messages

Use an imperative subject that describes one logical change, for example:

```text
Add cached-media reuse to the processing pipeline
```

Do not commit cookies, QR codes, account identifiers, SQLite databases, media, generated
knowledge-library files, virtual environments, or vendored dependencies.

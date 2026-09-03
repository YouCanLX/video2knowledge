# Agent Guide

This file applies to the entire repository. Agents must follow it together with the project
documentation and any higher-priority instructions.

## Project context

- Video2Knowledge is a local-first Python 3.11+ application with a `src/` layout.
- The CLI and FastAPI web application share dependencies assembled in `services.py`.
- Keep provider, speech, and LLM-specific behavior in `src/video2knowledge/adapters/` and
  depend on the protocols in `ports.py` from orchestration code.
- Runtime credentials, databases, downloaded media, generated knowledge files, virtual
  environments, and vendored dependencies must not be committed.
- Keep `README.md` and `README.zh-CN.md` aligned. Keep `CHANGELOG.md` and
  `CHANGELOG.zh-CN.md` aligned without mixing languages within either file.

## Implementation workflow

1. Inspect `git status`, the relevant code, tests, documentation, and recent Git history
   before changing files. Preserve unrelated work already present in the worktree.
2. Implement one cohesive feature or fix at a time. Include its tests and directly related
   documentation in the same logical unit of work.
3. Keep platform and model integrations behind the existing ports-and-adapters boundaries.
   Preserve transcripts when optional enrichment fails, and retain the serial-download
   behavior unless the task explicitly changes that product constraint.
4. Add or update tests for behavior changes. Prefer focused tests while iterating, then run
   the broadest practical validation before committing:

   ```bash
   pytest
   ruff check .
   ruff format --check .
   python -m build
   ```

   If a command cannot run because of an environment limitation, report the exact limitation
   and still run all unaffected checks.
5. Update the appropriate README feature/TODO sections and both changelogs for user-visible
   changes. A feature commit cannot contain its own final hash; add the hash in the next
   documentation or release-maintenance commit once it is known.

## Privacy and sensitive-information review

Before every commit, inspect all added and modified content, including tests, fixtures,
documentation, generated files, and the staged diff.

- Look for personal names, email addresses, usernames, account or creator identifiers,
  private URLs, local absolute paths, device names, tokens, API keys, passwords, cookies,
  QR-login data, database contents, and downloaded or generated user content.
- If any personal or secret value is present, replace it with an obviously synthetic
  placeholder or move it to ignored runtime configuration before committing.
- Never print secret values while investigating them. Check names and metadata first, and
  inspect secret-bearing files only when strictly necessary.
- Use temporary directories and fake adapters in tests. Do not use real credentials, account
  identifiers, media, or library data as fixtures.

## Commit policy

- Automatically create a commit after a cohesive requested feature or fix is implemented,
  validated, documented as needed, and reviewed for sensitive information.
- Review every pre-existing uncommitted change before staging. Group implementation and its
  tests together, but split independent features, fixes, refactors, and documentation work
  into separate commits. If all changes serve one cohesive purpose, commit them together.
- Stage explicit paths rather than all files blindly. Inspect `git diff --cached --check` and
  `git diff --cached` before each commit.
- Use concise Conventional Commit subjects consistent with repository history, such as
  `feat: group download history by creator`, `fix: normalize transcript timestamps`, or
  `docs: add agent workflow guidance`.
- Do not amend, squash, rebase, reset, discard, or overwrite existing commits or user changes
  unless the user explicitly requests it.
- Leave the worktree clean at handoff whenever all remaining changes are in scope and ready.

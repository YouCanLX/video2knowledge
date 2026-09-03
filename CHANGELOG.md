# Changelog

English | [Simplified Chinese](CHANGELOG.zh-CN.md)

This file records user-visible features, fixes, and maintenance work by project version and
Git commit. The project has not published a release tag yet, so the history below belongs to
the in-development `0.1.0` alpha version.

## [0.1.0] - In development

### 2026-09-04

| Type | Change | Commit |
| --- | --- | --- |
| Improvement | Update collection filter choices to match the selected creators. | `2c5382f` |
| Performance | Pipeline up to three concurrent downloads into serialized local transcription and concurrent LLM enrichment. | `a57d95e` |
| Feature | Support multi-select queue filters for creator, collection, status, and created year, month, and day. | `24fc18e` |
| UI | Show creator avatars for collections and videos in download history. | `d03907a` |
| Feature | Group download-history collections and individual videos under collapsible creator rows. | `cadce82` |
| Feature | Deduplicate downloaded media by SHA-256 content hash while retaining source references. | `d26e58a` |
| Feature | Reuse complete media, transcription, enrichment, and export results unless force refresh is requested. | `99c86ee` |
| Bug fix | Allow stale non-terminal job records left by previous sessions to be cleaned up safely. | `3597413` |
| Bug fix | Normalize timestamps returned by MLX transcription. | `024bfca` |

### 2026-09-03

| Type | Change | Commit |
| --- | --- | --- |
| Performance | Poll runtime services only while their status is needed. | `f18a400` |
| Feature | Check required runtime services before starting processing. | `cac3a61` |
| Maintenance | Normalize Python formatting across the codebase. | `04fafc6` |
| Feature | Add batch restart controls and movable progress cards. | `99b71d1` |
| Feature | Restart failed jobs in batches. | `0c6f0ba` |
| Feature | Reorganize the download history interface. | `dc35a59` |
| Feature | Restart an individual failed processing job. | `c1b4a20` |
| Bug fix | Escape list content rendered into enrichment HTML. | `da95aa7` |
| Feature | Pause and resume processing jobs. | `3e7fcab` |
| Bug fix | Render enrichment sections as bullet lists. | `523989b` |
| Feature | Persist download history and submitted-request tracking. | `f8e3e23` |
| Feature | Show processing progress for submitted requests. | `ea28f57` |
| Feature | Filter queue history by job status. | `18bb445` |
| Feature | Organize the knowledge library by creator and collection. | `bc4f419` |
| Bug fix | Locate Codex CLI installations inside macOS application bundles. | `8226b9c` |
| Feature | Improve queue-history management controls. | `c86646f` |
| Feature | Preserve collection context in exported knowledge documents. | `2aae613` |
| Build | Support newer PyAV releases. | `d4fcf04` |
| Build | Add environment setup and service scripts. | `8ff2768` |
| Feature | Import videos in creator-level batches. | `716a1d2` |
| Documentation | Add the Simplified Chinese README. | `ea4abc1` |
| UI | Improve Markdown card contrast. | `d391618` |
| Feature | Add interactive controls for generated files in the queue. | `3b2fc8f` |
| Feature | Build the core Video2Knowledge processing agent and local web workflow. | `2ee622f` |

### 2026-09-02

| Type | Change | Commit |
| --- | --- | --- |
| Project | Create the initial project structure and baseline documentation. | `76d9f69` |

## Maintenance policy

- Add every user-visible feature, bug fix, performance change, and breaking change under
  the target version when its commit is merged.
- Keep commit hashes for traceability; use a release date instead of “In development” when
  the version is tagged.
- Move future work to the README TODO list rather than documenting it as delivered here.
- Keep this file synchronized with `CHANGELOG.zh-CN.md`.

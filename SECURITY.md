# Security Policy

## Supported versions

Video2Knowledge is currently an alpha. Security fixes are applied to the latest revision on
the default branch.

## Reporting a vulnerability

Do not disclose credential leaks or exploitable vulnerabilities in a public issue. Once the
repository is public, use GitHub's private vulnerability reporting or a security advisory.
Include reproduction steps, affected versions, and the expected impact, but never attach a
real Bilibili cookie, QR code, or private transcript.

## Local security model

- The web interface binds to `127.0.0.1` by default and is not designed for public exposure.
- Bilibili cookies are stored in the configured data directory with `0600` permissions.
- The Codex CLI enrichment adapter runs in a temporary directory with a read-only sandbox.
- Video2Knowledge does not read browser profiles or browser cookie databases.
- Users are responsible for filesystem permissions on custom data paths and backups.

Rotate Bilibili credentials immediately if a cookie file is accidentally shared or committed.

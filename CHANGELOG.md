# Changelog

All notable changes to **mcp-apple-mail** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- **HTML replies/compositions no longer paste the body twice** (a rendered
  copy plus a second copy of the raw `<p>`/`<b>` source). `reply_to_email`,
  `compose_email`, and `forward_email` placed the raw HTML *source* on the
  clipboard under `NSPasteboardTypeHTML`; for any HTML that wasn't a complete
  document, Mail rendered it AND surfaced the literal markup, so the message
  appeared twice. The body is now converted to an `NSAttributedString` and
  written back as RTF (a single unambiguous rich-text flavor) plus a
  *rendered* plain-text fallback. `create_rich_email_draft` was unaffected
  (it already builds a proper multipart/alternative `.eml`).

### Added
- **Release workflow now builds and attaches the `.mcpb` bundle** to the GitHub
  Release automatically on each tag (verifies the bundle contains the
  `apple_mail_mcp` package and doesn't leak `venv/`/`__pycache__`).
- **`scripts/extract_changelog.py`** — pulls the current version's section from
  this file to use as the GitHub Release body.

## [3.1.7] - 2026-06-12

First 3.x release actually published to PyPI. Versions 3.0.0–3.1.6 were tagged
in git but never uploaded, so PyPI remained stuck on the broken 2.2.0 wheel and
`uvx mcp-apple-mail` kept failing with `ModuleNotFoundError: No module named
'apple_mail_mcp'`. This release ships the (already-correct) `plugin/` packaging
to PyPI and adds automation so a release can never again be built-but-not-shipped.

### Fixed
- **PyPI now serves a working wheel** that contains the `apple_mail_mcp/`
  package. Resolves the user-facing failure reported in #42 and #57.

### Added
- **Release automation via PyPI Trusted Publishing** (`.github/workflows/release.yml`).
  Pushing a `vX.Y.Z` tag builds, verifies, and publishes via OIDC — no API
  tokens stored. The build fails closed if the tag doesn't match the version or
  the wheel is missing the package.
- **CI packaging guard** (`.github/workflows/ci.yml`) — every push/PR builds the
  wheel and runs `verify_wheel.py`, plus the test suite on Python 3.10–3.13.
- **`scripts/verify_wheel.py`** — pre-publish artifact guard. Inspects a wheel
  for the `apple_mail_mcp/` package and payload size, then does a clean-venv
  install + import + entry-point check. Catches the 2.2.0-style "dist-info only"
  regression before it ships.
- **This `CHANGELOG.md`** (previously linked from `pyproject.toml` but missing)
  and **`RELEASING.md`** documenting the release flow and one-time PyPI setup.

### Notes
- The README's `uvx mcp-apple-mail` package name is correct — `mcp-apple-mail`
  is this project's PyPI distribution. (The similarly named `apple-mail-mcp` on
  PyPI is an unrelated package by a different author.) Issue #57's suggested
  rename would have pointed users at the wrong package, so it was not applied.

## [3.0.0] – [3.1.6] - 2026-03-27 → 2026-06-09 (git tags only, never on PyPI)

These versions were released as GitHub tags/MCPB bundles but were never uploaded
to PyPI. Highlights from this line, now reaching PyPI users via 3.1.7:

### Fixed
- Corrected `pyproject.toml` for the `plugin/` package layout so the wheel
  includes the `apple_mail_mcp/` package (the root fix for the 2.2.0 bug).
- Stop a Mail relaunch loop; prevent orphaned `osascript` from pinning Mail's
  main thread; poll for Mail focus before pasting to avoid silent empty sends.
- Attach files after the HTML paste so `Cmd+A` doesn't clobber them; scope
  `reply_to_email` attachment inserts to the reply message.
- Produce working Apple Mail deep links from search results; strip CDATA
  wrappers from body content; support localized inbox names (FR/DE/ES/IT/PT/NL/JA).
- Respect account default sender and allow `from_address` override.

### Added
- `synchronize_account` and `list_account_addresses` tools; `mail_link` in
  default search output.
- Version drift guard (`scripts/check_versions.py`) and `server.json` for MCP
  Registry validation.
- Plugin/marketplace distribution layout (`plugin/`), `/email-management` slash
  command.

### Changed
- Consolidated tools: 10 search tools → 2 (`search_emails` + `get_email_thread`);
  merged bulk operations into `manage.py`; trimmed verbose tool responses.

## [2.2.0] - 2026-03-27 (broken on PyPI — superseded by 3.1.7)

> **Do not use.** This wheel shipped only the dist-info and console-script entry
> point, not the `apple_mail_mcp/` package, so the server crashes on startup
> with `ModuleNotFoundError`. Fixed in 3.1.7. (Reported in #42, #57.)

[3.1.7]: https://github.com/patrickfreyer/apple-mail-mcp/releases/tag/v3.1.7
[2.2.0]: https://github.com/patrickfreyer/apple-mail-mcp/releases/tag/v2.2.0

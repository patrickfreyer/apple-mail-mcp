# Changelog

All notable changes to **mcp-apple-mail** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- `--read-only` now blocks delivery instead of removing the composing tools.
  `compose_email` and `reply_to_email` stay registered and refuse `mode="send"`
  themselves; only `forward_email`, which has no non-sending mode, is still
  removed. Previously the flag took away the entire compose surface, and with
  it the only tools that accept `attachments` — leaving no supported way to
  attach a file to a draft in read-only mode.

### Fixed
- Editing a draft no longer costs it its signature. `manage_drafts(action="update")`
  rebuilt the message from `content of theDraft` — Mail's *plain-text* rendering,
  in which the signature is already reduced to unformatted text — and then set
  `message signature` to `missing value` so that flattened copy would not be
  doubled. The result had no `X-Apple-Mail-Signature` header, Mail's compose
  window reported "Signature: None", and the signature had lost its table, image
  and colours. The rebuild now reuses the stored HTML instead (via the raw
  message source), cuts the baked-in signature block out of it, and leaves
  `message signature` alone so Mail attaches the live one again. When the HTML
  cannot be recovered the old plain-text rebuild is used and the return value
  says so instead of pretending nothing was lost.
- Repeated draft edits no longer nest Mail's share wrapper. macOS 15+ Mail wraps
  every AppleScript-supplied body in
  `<div class="Apple-Mail-URLShareWrapperClass"><blockquote type="cite">`; feeding
  a stored body back through the composer therefore added a layer on every edit
  (measured two layers deep on a draft edited twice). The reuse path now peels
  the existing layers off first. The wrapper itself is Mail's and cannot be
  suppressed — see "Known Mail.app limitations" in the README.
- `--read-only` had no effect on `manage_drafts(action="send")`. `compose.py`
  did `from apple_mail_mcp.server import READ_ONLY`, which binds the value
  `False` at import time, while `__main__` sets `server.READ_ONLY` afterwards.
  The guard therefore never fired. The module now reads the flag through the
  `server` module at call time.
- Removed the redundant `plugin/commands/email-management.md` slash command.
  It shadowed `plugin/skills/email-management/` under the same
  `apple-mail:email-management` listing key, so every session showed two
  near-duplicate entries with different descriptions (#82). Claude Code
  invokes skills directly as slash commands, so `/email-management` still
  works via the skill alone.
- `create_rich_email_draft`'s `save_as_draft` no longer claims or silently
  retries a save that can never succeed. Mail opens a `.eml` as a read-only
  message viewer, not a compose object, so the AppleScript `every outgoing
  message whose subject is ...` query can never match it — the old retry
  loop always returned `False` after ~5s of polling (#83). The tool now
  skips the futile retry and reports plainly that `save_as_draft` isn't
  supported for this workflow, pointing to `compose_email(mode="draft")` or
  `manage_drafts` for a real, sendable HTML draft.

## [3.2.0] - 2026-07-04

### Added
- **`get_email_source`** — new tool exposing an email's raw RFC 822 source
  (full headers + MIME body) for debugging threading, authentication results,
  and encoding issues (#66). Supports a `headers_only` mode and a configurable
  byte cap with an explicit truncation marker so huge messages can't flood the
  context. Uses Mail's `message id` property and resolves localized inbox
  names via `build_mailbox_ref`.
- **`list_inbox_emails` now surfaces `message_id`, `internet_message_id` and a
  `mail_link`** in both its JSON and text output, matching `search_emails`
  (#76) — inbox listings can be cited as Apple Mail deep links
  (`message://…`) and targeted by id without a second lookup.
  Backward-compatible with older 5-field records.

### Fixed
- **Stored XSS in the inbox dashboard** (#77). Attacker-controlled email
  subjects/senders containing `</script>` could break out of the dashboard's
  embedded JSON `<script>` block and inject arbitrary HTML. JSON injected into
  the template now escapes `<`, `>`, `&`, and U+2028/U+2029; remaining
  unescaped template interpolations in the account cards were also fixed.
- **Umlauts, ß, and emoji no longer garble when pasting HTML bodies into
  Mail** (#79). The Cocoa HTML→RTF importer auto-detected the charset and
  defaulted to Latin-1, double-decoding UTF-8 bytes into mojibake
  ("Grüße" → "GrÃ¼ÃŸe") on both the plain and HTML compose paths. The
  importer is now pinned to UTF-8 via `NSCharacterEncodingDocumentAttribute`.

## [3.1.8] - 2026-06-23

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

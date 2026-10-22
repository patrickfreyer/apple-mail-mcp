# Changelog

All notable changes to **mcp-apple-mail** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security
- The write-path denylist now also checks the path as requested, not only its
  symlink target. A symlink inside a protected folder (e.g.
  `/opt/homebrew/bin/python3`) resolves outside it, so writing through it was
  allowed (#125 by @proscar87, follow-up to #103).
- Hardened the file-path guard for file-writing tools (#103, follow-up to #19).
  The old denylist missed shell startup files, so a prompt-injected
  `save_email_attachment(save_path="~/.zshrc")` could plant an attacker-supplied
  attachment that ran on the next shell. `save_email_attachment`,
  `export_emails` and `create_rich_email_draft`'s `output_path` (previously
  unchecked) now refuse every dotfile and dot-folder directly in `$HOME`
  (`~/.zshrc`, `~/.ssh`, `~/.gitconfig`, `~/.config`, `~/.netrc`, ...),
  `.git/hooks`, `.git/config` and `.envrc` anywhere, autostart and persistence
  locations (`~/Library/LaunchAgents`, `/Library/LaunchDaemons`,
  `~/Library/Application Support`, `~/Library/Preferences`, ...) and `PATH`
  folders (`~/bin`, `/usr/local/bin`, `/opt/homebrew/bin`). Everything else
  stays writable, including paths outside `$HOME` such as the temp dir.
- Attachment paths for `compose_email` and `reply_to_email` may now be any
  readable file (previously `$HOME` only) except secrets: `~/.ssh`, `~/.gnupg`,
  `~/.aws`, `~/.netrc`, git/cloud credentials, `.env` files,
  `~/Library/Keychains` and browser profiles and cookie stores.
- New opt-in restriction: `APPLE_MAIL_MCP_WRITE_DIRS` and
  `APPLE_MAIL_MCP_ATTACH_DIRS` (colon-separated), or the repeatable
  `--write-dir` / `--attach-dir` flags, confine writes or attachments to the
  listed folders; the denylist still applies inside them.
- All checks live in one shared module (`apple_mail_mcp/paths.py`) instead of
  three copies, resolve `..` and symlinks before checking, and compare
  case-insensitively to match APFS (`~/.ZSHRC` is `~/.zshrc`).

### Fixed
- `list_inbox_emails` in text output and `get_mailbox_unread_counts(summary_only=True)`
  ignored `account` and returned every account; they now filter by it
  (#126 by @proscar87).
- `search_emails` on a mailbox over the whose-clause limit now stops its
  bounded index scan at the first message outside a `date_from` window
  (newest-first) or `date_to` window (oldest-first), instead of reading the
  full 4000-message cap. A one-week search of a 6,000-message mailbox no
  longer holds the automation lock for minutes (#133 by
  @joel-alturaeducation, related to #87 and #132).
- The Claude Code plugin manifests (`plugin/.claude-plugin/plugin.json`,
  `.claude-plugin/marketplace.json`) were stuck at 3.1.2, so `claude plugin
  update` reported installs as current. They are now at 3.2.1 and
  `scripts/check_versions.py` and `RELEASING.md` cover them (#127 by
  @proscar87).
- `move_email` no longer treats a negative `older_than_days` as a filter (it
  added no date condition, so the call moved everything), and `manage_trash`
  rejects an unrecognised `action` instead of falling through to
  `move_to_trash` (#124 by @proscar87).
- `reply_to_email` now restores the user's clipboard. The restore step sat
  after the script's `return`, so it never ran and every reply (send, draft
  or open) left the reply body on the clipboard. The error path now restores
  it too, as does `forward_email`'s error path when a `message` was pasted
  (#106).

## [3.2.1] - 2026-10-15

### Fixed
- The server failed to start on any fresh install since the `mcp` SDK 2.0
  release (`ModuleNotFoundError: No module named 'mcp.server.fastmcp'`, #97).
  `server.py` imported `FastMCP` from the SDK's bundled v1 module instead of
  from the declared `fastmcp` dependency, so once `fastmcp` 4.x pulled in
  `mcp` 2.x the import path vanished. Now imports `from fastmcp import
  FastMCP`. `--read-only` also called `FastMCP.remove_tool()`, which is
  deprecated in fastmcp 3.x and removed in 4.x; it now goes through
  `local_provider.remove_tool()`, which both support.
- `search_emails` no longer hangs Mail or returns nothing on very large
  mailboxes such as a Gmail INBOX (#41, #87). Above 5,000 messages the full
  `whose` scan is skipped in favour of a bounded index scan (newest first for
  `date_desc`), capped at 4,000 messages per call; when the cap is reached
  the response says so (`scan_limited` in JSON, a NOTE line in text) instead
  of silently returning less. Body-text search on large mailboxes is bounded
  too.
- Reply and forward drafts render in the intended sans-serif font instead of
  Mail's small serif default (#100, #101). The reply/forward HTML now carries
  an explicit font style rather than `font: inherit`.
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

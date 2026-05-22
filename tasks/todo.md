# Rolling backlog — apple-mail-mcp

This is the cross-session source of truth for "what's next" on this plugin. In-conversation tracking happens via the TaskCreate task list; this file is what survives between sessions. Add items as they come up. Check things off and delete them when done so the list stays scannable.

**Convention:** group by phase / PR target. Each item is a single line with enough context that a future session can pick it up cold. Reference file paths and line numbers when known. If an item grew into a real plan, drop a link to the workstream folder under `tasks/<dated-workstream>/`.

---

## In flight

_(empty — 3.1.5 release-ready; awaiting user direction on commit/tag/publish.)_

---

## PR 3.1.6 — conservative dedup + hygiene (next up)

From the 3.1.5 audit. Conservative scope only.

- [ ] **Move `SENSITIVE_DIRS` blocklist into `core.py`** — duplicated between `tools/compose.py` (~lines 517–526) and `tools/analytics.py` (~lines 423, 430). Add `core.SENSITIVE_DIRS` constant and `core.validate_save_path(path) -> Optional[str]` helper.
- [ ] **Consolidate `_split_addresses`** in `compose.py` — three near-identical implementations across `compose_email` / `reply_to_email` / `forward_email` (lines 22–26, 270–271, 363–374). Move to a single module-level helper.
- [ ] **Extract CC/BCC recipient-loop builder** in `compose.py` — four copies (lines 659–674, 986–991, 1131–1146, plus `_send_html_email`). One helper returning `(cc_script, bcc_script, safe_cc, safe_bcc)`.
- [ ] **`start_mcp.sh` — require Python 3.10+** — currently checks `python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,7) else 1)"`. Bump to 3.10 and verify `fastmcp` imports successfully (not just that venv dir exists). Fixes a confusing failure mode for users on 3.7–3.9.
- [ ] **Align `fastmcp` pin** — `plugin/requirements.txt` says `==3.1.0`, `pyproject.toml` says `>=3.1.0`. Align both to `>=3.1.0,<4`.
- [ ] **Replace `except: pass` swallows** in `analytics.py` (line ~334, ~620), `smart_inbox.py` (~227, ~334, ~573), `manage.py` (~227), `compose.py` (~72). Collect failed subjects/accounts into an `errors` list returned in the response.
- [ ] **Route compose.py direct `subprocess.run` osascript calls through `run_applescript()`** — `_send_html_email` and the reply/forward fast paths bypass timeout/error standardization. Two call sites; preserve `use framework` directives.
- [ ] **Add `keywords` + `category` to `plugin/.claude-plugin/plugin.json`** for marketplace discoverability. Mirror the keywords from `pyproject.toml`.

## PR 3.1.6 — validator follow-ups (small)

- [ ] **Add CI guard for manifest drift** — `tools/validate_manifests.sh` that asserts: (a) versions match across 5 files, (b) tool count claim matches `@mcp.tool` grep, (c) mcpb `tools[]` array entries match the registered tool names. Run as pre-commit.
- [ ] **Top-level marketplace `metadata.version`** — either remove it (it's optional) or document in CLAUDE.md that "1.0.0" describes the marketplace manifest itself and isn't tied to the plugin version. Currently it just looks like a forgotten release.
- [ ] **`apple-mail-mcpb/manifest.json` `dxt_version`** — currently `0.1`. Latest mcpb spec is `0.2`. Verify against the `apple-mail-mcpb/build-mcpb.sh` mcpb CLI and bump if validation passes.

---

## Future skills (paused until hardening complete)

Skills only — no new commands (Claude Code auto-converts at install time). Convention is locked in `CLAUDE.md` § Skill authoring convention; copy `plugin/skills/email-management/SKILL.md` as the template.

- [ ] **`email-drafting`** skill — composition workflows: rich HTML drafts, replies that gather thread context, multi-recipient sends. Reference tools: `create_rich_email_draft`, `compose_email`, `reply_to_email`, `forward_email`, `manage_drafts`.
- [ ] **`inbox-triage`** skill — one-off triage runs over a fixed time window. Reference tools: `get_needs_response`, `get_awaiting_reply`, `update_email_status`, `move_email`.
- [ ] **`email-attachments`** skill — attachment-focused workflows. Reference tools: `list_email_attachments`, `save_email_attachment`, `search_emails(has_attachments=True)`.

Each new skill must pass `plugin-dev:skill-reviewer` on the frontmatter before merging.

---

## Future architecture explorations (deferred / open questions)

Things that would be real wins but aren't scoped yet.

- [ ] **Hybrid SQLite read-path** — Mail.app keeps an Envelope Index at `~/Library/Mail/V*/MailData/Envelope Index`. For read-only operations (search, list, statistics) we could query that directly and skip Apple Events entirely. Order-of-magnitude faster on large mailboxes. Risk: schema isn't documented and changes between macOS releases.
- [ ] **`plugin/venv/` location reconsideration** — validator confirmed current placement is fine, but: (a) `start_mcp.sh` should verify the venv has `fastmcp` importable (not just that the directory exists), (b) consider documenting the ~108 MB footprint in README's install section.
- [ ] **`plugin-dev:plugin-validator` periodic gate** — run as a pre-commit or CI step on every change to `plugin.json`, `marketplace.json`, `manifest.json`, or `tools/*.py`. Catches the kind of count-drift we hit in 3.1.5.
- [ ] **`server.json` ↔ PyPI publishing** — `server.json` is set up for MCP registry submission but we never submit. If we do, gate on version bump.
- [ ] **Consider merging `core.inbox_mailbox_script()` and `core.build_mailbox_ref()`** — near-identical INBOX-fallback logic. Conservative dedup skipped this because the touch area is too large; revisit if a third caller appears.

---

## Maintenance reminders

- After any change to `tools/*.py`: run `.venv/bin/pytest tests/ -q`. Target stays ≥ 97 passing.
- After any change to manifests, command/skill frontmatter, or directory layout: run `plugin-dev:plugin-validator`. Blocking-on-pass before declaring done.
- After any change to a skill body or `description`: run `plugin-dev:skill-reviewer` specifically on the frontmatter.
- After bumping a version: run `grep -rn "3\.1\." pyproject.toml server.json plugin/.claude-plugin/plugin.json .claude-plugin/marketplace.json apple-mail-mcpb/manifest.json` and confirm five hits at the new version.

---

## Done (recent — keep last 10, prune older)

- [x] 3.1.5: Modernize `smart_inbox.py`, `manage.py`, `analytics.py`, `compose.py` (DEFAULT_MAIL_ACCOUNT, whose+cap, ignoring case, AppleScriptTimeout, timeout param).
- [x] 3.1.5: Delete `LOWERCASE_HANDLER` from `core.py` — last caller migrated.
- [x] 3.1.5: Tests 75 → 97 (added `tests/test_modernization_3_1_5.py`).
- [x] 3.1.5: Rebuild mcpb `tools[]` array from real registry; fix count claim 27 → 26 in three manifests.
- [x] 3.1.5: Version sync to 3.1.5 across all 5 manifests.
- [x] 3.1.5: CLAUDE.md updated with tool-implementation conventions + skills-only rule.
- [x] 3.1.5: README refreshed — tool count 22 → 26, `DEFAULT_MAIL_ACCOUNT` documented, Performance Defaults table added, Safety Limits corrected, Python 3.7+ → 3.10+, stale tool references removed.
- [x] 3.1.4: Rewrite `email-management` skill with sibling-collision-proof description; extract detail to `references/`.
- [x] 3.1.4: Async + per-account parallelism in `search.py` and `inbox.py`; AppleScript-side caps; `recent_days=2.0` default; `DEFAULT_MAIL_ACCOUNT` env var.
- [x] 3.1.4: Skill authoring convention documented in CLAUDE.md.

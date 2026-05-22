# Rolling backlog — apple-mail-mcp

This is the cross-session source of truth for "what's next" on this plugin. In-conversation tracking happens via the TaskCreate task list; this file is what survives between sessions. Add items as they come up. Check things off and delete them when done so the list stays scannable.

**Convention:** group by phase / PR target. Each item is a single line with enough context that a future session can pick it up cold. Reference file paths and line numbers when known. If an item grew into a real plan, drop a link to the workstream folder under `tasks/<dated-workstream>/`.

**Phase plan (concise):** [`phase-plan-3.1.6.md`](phase-plan-3.1.6.md) · **Full audit:** [`plugin-audit-and-action-plan-2026-05-21.md`](plugin-audit-and-action-plan-2026-05-21.md) · **Plan review status:** [`plan-review-status-2026-05-21.md`](plan-review-status-2026-05-21.md)

---

## In flight

- [x] **Make coding-agent live testing first-class** — `docs/AGENT_LIVE_TESTING.md`: setup, permissions, all CLI commands, perf/smoke batteries, post-edit workflow (quick-check → perf-test full).
- [ ] **Keep one shared tool path across agents** — ensure Claude, OpenClaw, mcporter, and local CLI all point at the same repo checkout and server entrypoint so fixes land once and every agent uses the same implementation.

## PR 3.1.6 — live performance fixes from mailbox testing

Observed on 2026-05-21 using `ai.openclaw` via both the repo-owned `.venv/bin/apple-mail` CLI and the generated shared `apple-mail` wrapper. Basic metadata/search/dry-run paths are now fast; remaining risk is concentrated in cross-account dashboards, invalid-account handling, and analysis tools.

- [x] **Fix `inbox_dashboard` timeout** — async per-account recent fetch; `include_preview=False` default; skip `content of aMessage` unless requested.
- [x] **Return clean errors for unknown accounts** — `validate_account_name()` wired across account-scoped tools (manage, analytics, smart_inbox, compose, search, inbox).
- [x] **Optimize `get_inbox_overview` payload and options** — `compact` / `json` modes; toggles for mailboxes, recent preview, suggestions; optional account scoping.
- [x] **Optimize analysis tools** — removed unfiltered `every message of` fallbacks in `smart_inbox.py`; sent scan uses `messages 1 thru N`.
- [x] **Expand repo-owned CLI coverage** — `unread`, `overview`, `needs-response`, `awaiting-reply`, `top-senders`, `statistics`, `move-dry-run`, `trash-dry-run`, `drafts list`; `perf-test`/`quick-check` with `bad_account`, `dashboard_metadata`, `--verbose-sensitive`; smoke-test `invalid_account` + `draft_safe_send_block`. See `docs/AGENT_LIVE_TESTING.md`.
- [ ] **Normalize generated wrapper JSON shape** — some wrapper tools return direct JSON arrays/dicts, while others wrap strings under `content`/`structuredContent.result`. Prefer structured dict/list returns from the Python tools so `mcporter` emits predictable JSON for automation.
- [ ] **Add timing telemetry to tool responses** — optional `include_timing: bool = False` or debug env var (Phase B / `perf-test`; deferred from Phase A — not yet implemented).
- [ ] **Add exact-id action paths for destructive tools** — prefer `message_ids` for `move_email`, `manage_trash`, attachment save/list, and status updates so agents can search first, inspect IDs, then act precisely without rescanning broad filters.
- [ ] **Add redacted benchmark fixtures/tests** — unit-test that performance-oriented AppleScript includes `whose` date/read/sender filters and `items 1 thru N` caps before property extraction. Keep live perf tests opt-in because they require Mail.app.
- [ ] **Investigate hybrid SQLite read path** — **do not start until dashboard/account validation/analysis caps are fixed and benchmarked** (Phases A/B/2). Prototype read-only search/list/statistics against Mail's Envelope Index behind a feature flag; schema is undocumented.

---

## PR 3.1.6 — conservative dedup + hygiene (next up)

From the 3.1.5 audit. Conservative scope only.

- [x] **Move `SENSITIVE_DIRS` blocklist into `core.py`** — `core.SENSITIVE_DIRS` + `validate_save_path()`; compose + analytics use shared helper.
- [ ] **Consolidate `_split_addresses`** in `compose.py` — three near-identical implementations across `compose_email` / `reply_to_email` / `forward_email` (lines 22–26, 270–271, 363–374). Move to a single module-level helper.
- [ ] **Extract CC/BCC recipient-loop builder** in `compose.py` — four copies (lines 659–674, 986–991, 1131–1146, plus `_send_html_email`). One helper returning `(cc_script, bcc_script, safe_cc, safe_bcc)`.
- [ ] **`start_mcp.sh` — require Python 3.10+** — ~~currently checks 3.7~~ **done on branch** (`start_mcp.sh` now gates 3.10+). Remaining: verify `fastmcp` imports successfully after venv create.
- [ ] **Align `fastmcp` pin** — `plugin/requirements.txt` says `==3.1.0`, `pyproject.toml` says `>=3.1.0`. Align both to `>=3.1.0,<4`.
- [ ] **Replace `except: pass` swallows** in `analytics.py` (line ~334, ~620), `smart_inbox.py` (~227, ~334, ~573), `manage.py` (~227), `compose.py` (~72). Collect failed subjects/accounts into an `errors` list returned in the response.
- [ ] **Route compose.py direct `subprocess.run` osascript calls through `run_applescript()`** — `_send_html_email` and the reply/forward fast paths bypass timeout/error standardization. Two call sites; preserve `use framework` directives.
- [ ] **Add `keywords` + `category` to `plugin/.claude-plugin/plugin.json`** for marketplace discoverability. Mirror the keywords from `pyproject.toml`.

## PR 3.1.6 — validator follow-ups (small)

- [x] **Add CI guard for manifest drift** — `tools/validate_manifests.sh` + `tools/validate_manifests.py`; `.github/workflows/ci.yml` (mocked pytest only).
- [x] **Fix stale Python 3.7 references** — `CLAUDE.md` and `apple-mail-mcpb/build-mcpb.sh` embedded README now say 3.10+ (launcher gates 3.10+).
- [x] **Clean audit hotspot table** — removed resolved `move_email --dry-run` ~61s row from audit critical hotspots (live ~0.61s).
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

- [ ] **Hybrid SQLite read-path** — Mail.app keeps an Envelope Index at `~/Library/Mail/V*/MailData/Envelope Index`. **Deferred:** do not implement in 3.1.6 unless AppleScript paths remain too slow after Phases A/B/2 are benchmarked. Feature-flag any spike; schema changes between macOS releases.
- [ ] **`plugin/venv/` location reconsideration** — validator confirmed current placement is fine, but: (a) `start_mcp.sh` should verify the venv has `fastmcp` importable (not just that the directory exists), (b) consider documenting the ~108 MB footprint in README's install section.
- [ ] **`plugin-dev:plugin-validator` periodic gate** — run as a pre-commit or CI step on every change to `plugin.json`, `marketplace.json`, `manifest.json`, or `tools/*.py`. Catches the kind of count-drift we hit in 3.1.5.
- [ ] **`server.json` ↔ PyPI publishing** — `server.json` is set up for MCP registry submission but we never submit. If we do, gate on version bump.
- [ ] **Consider merging `core.inbox_mailbox_script()` and `core.build_mailbox_ref()`** — near-identical INBOX-fallback logic. Conservative dedup skipped this because the touch area is too large; revisit if a third caller appears.

---

## Maintenance reminders

- After any change to `tools/*.py`: run `.venv/bin/pytest tests/ -q`. Target stays ≥ 146 passing.
- After any change to manifests, command/skill frontmatter, or directory layout: run `plugin-dev:plugin-validator`. **If unavailable:** run `rg '^@mcp\.tool' plugin/apple_mail_mcp/tools/*.py | wc -l` (expect 27), version grep across five files, and document the missing validator in the PR. Blocking before declaring done when the agent is available.
- After any change to a skill body or `description`: run `plugin-dev:skill-reviewer` on the frontmatter — same fallback if unavailable.
- After bumping a version: run `grep -rn "3\.1\." pyproject.toml server.json plugin/.claude-plugin/plugin.json .claude-plugin/marketplace.json apple-mail-mcpb/manifest.json` and confirm five hits at the new version.

---

## Done (recent — keep last 10, prune older)

- [x] 3.1.6 Phase 0: mcpb `get_email_by_id` + 27-tool count sync; SKILL.md `confirm_empty=True`; account validation helper.
- [x] 3.1.6 Phase A (core): async `inbox_dashboard`, overview compact/json modes, smart_inbox fallback hardening, `tests/test_phase_a_fixes.py`.
- [x] 3.1.6 Phase B: full agent CLI (`cli.py`), `tests/test_cli.py` + `tests/test_cli_perf.py`, `docs/AGENT_LIVE_TESTING.md` (146 tests total).
- [x] `--draft-safe` flag + repo `apple-mail` CLI + `smoke-test` (already on branch before Phase 0).
- [x] 3.1.5: Delete `LOWERCASE_HANDLER` from `core.py` — last caller migrated.
- [x] 3.1.5: Tests 75 → 97 (added `tests/test_modernization_3_1_5.py`).
- [x] 3.1.5: Rebuild mcpb `tools[]` array from real registry; fix count claim 27 → 26 in three manifests.
- [x] 3.1.5: Version sync to 3.1.5 across all 5 manifests.
- [x] 3.1.5: CLAUDE.md updated with tool-implementation conventions + skills-only rule.
- [x] 3.1.5: README refreshed — tool count 22 → 26, `DEFAULT_MAIL_ACCOUNT` documented, Performance Defaults table added, Safety Limits corrected, Python 3.7+ → 3.10+, stale tool references removed.
- [x] 3.1.4: Rewrite `email-management` skill with sibling-collision-proof description; extract detail to `references/`.
- [x] 3.1.4: Async + per-account parallelism in `search.py` and `inbox.py`; AppleScript-side caps; `recent_days=2.0` default; `DEFAULT_MAIL_ACCOUNT` env var.
- [x] 3.1.4: Skill authoring convention documented in CLAUDE.md.

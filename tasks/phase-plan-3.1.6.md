# Phase Plan — 3.1.6

**Branch:** `improve-speed-and-tools` · **Tests:** 206 passing  
**Full audit:** [`plugin-audit-and-action-plan-2026-05-21.md`](plugin-audit-and-action-plan-2026-05-21.md)  
**Plan review:** [`plan-review-status-2026-05-21.md`](plan-review-status-2026-05-21.md) · [`PLAN_REVIEW_COMMENTS_2026-05-21.md`](../PLAN_REVIEW_COMMENTS_2026-05-21.md)  
**Live testing:** [`CLI_TESTING_REPORT_2026-05-21.md`](../CLI_TESTING_REPORT_2026-05-21.md)  
**Rolling backlog:** [`todo.md`](todo.md)

## Sequence

```
0 (sync, ~2h) → A (live fixes, 2–3d) → 1 (CI, 0.5d) → B (CLI, 1–2d) → 2 (scans, 2–3d) → 3 (MCP) → 4 (hygiene) → 5 (skills, paused)
```

| Ship target | Phases |
|-------------|--------|
| Marketplace honest | 0 + 1 |
| Agent-ready on real Mail | 0 + A + B + 1 |
| Large-mailbox safe | above + 2 |
| Full 3.1.6 | above + 3 + 4 |

**Next PR:** Continue **Phase 3** — annotations done; JSON normalization + Error prefix + compose osascript migration remain. Phase 4 hygiene can proceed in parallel only on independent files (dedup, fastmcp pin).

### Orchestration rule (dependency gates)

**Do not start a phase until the previous phase's exit criteria are met and tests are green.**

| Gate | Must complete before |
|------|----------------------|
| 0 + 1 | A (manifests honest in CI) |
| A + B + 1 | 2 (live paths stable; repo CLI for verification) |
| 2 | 3 (tool shapes/APIs frozen; no bare `every message of`) |
| 3 | 4 (annotations/JSON conventions locked) |
| 4 | 5 (skills paused anyway) |

Within a phase, parallel subagents are OK for **independent files** (e.g. doc hygiene vs one tool module). Do **not** run Phase 3 annotations + Phase 4 dedup + Phase 2 compose hardening concurrently — they touch the same modules and ordering matters.


## Already done (mark in `todo.md`)

- [x] `--draft-safe` flag (`__main__.py`)
- [x] Repo CLI foundation + full safe wrapper suite (`cli.py`)
- [x] `start_mcp.sh` Python 3.10+ gate
- [x] Core agent paths fast (accounts, inbox, search, show, dry-run move/trash)
- [x] 206 unit tests passing
- [x] Phase 0 manifest sync + Phase A core (dashboard, validation on 3 tools, overview modes, smart_inbox caps)

---

## Phase 0 — Manifest sync (~2h)

**Goal:** 27 tools everywhere; validator passes.

**Skills:** `plugin-structure` · `mcp-integration` · `CLAUDE.md` § Versioning  
**Sub-agents:** `generalPurpose` · **`plugin-validator`** ⛔ · `skill-reviewer` (SKILL L51) · `shell` (mcpb build)  
**Verify:** `verification-before-completion`

- [x] Add `get_email_by_id` to `apple-mail-mcpb/manifest.json` `tools[]`
- [x] Set tool count **27** in marketplace, mcpb description, `CLAUDE.md`, README tree, `__init__.py` comments
- [x] Fix `plugin/skills/email-management/SKILL.md` L51: `confirm_empty=True`
- [x] Update `todo.md` — close stale `--draft-safe` / smoke-test / Python 3.7 items
- [x] Run **`plugin-validator`** (blocking)
- [x] Rebuild mcpb (`apple-mail-mcpb/build-mcpb.sh`)

**Done when:** `rg '^@mcp\.tool' plugin/apple_mail_mcp/tools/*.py | wc -l` = 27; mcpb `tools[]` = 27; validator green (or local manifest checks if `plugin-validator` unavailable — document the gap).

---

## Phase A — Live fixes (2–3 days)

**Goal:** Fix what CLI sweep hit on real Mail.app.

**Skills:** `CLAUDE.md` conventions · `python-performance-optimization` · `testing-python` · CLI report  
**Sub-agents:** **`explore`** (preflight) · `generalPurpose` · `review-and-ship` · `verification-before-completion`  
**Verify:** `.venv/bin/apple-mail smoke-test --json`; wrapper `inbox-dashboard` metadata-only &lt; 5s (preferred &lt; 3s)

- [x] **`inbox_dashboard`** — async per-account; `include_preview=False` default; skip `content of aMessage` (`analytics.py`)
- [x] **`validate_account_name()`** in `core.py` → structured `account_not_found`; wired across account-scoped tools (manage, analytics, smart_inbox, compose, search, inbox)
- [x] **Wire validation to remaining account-scoped tools** — explicit-account paths only; short timeout; no fan-out overhead (review #5)
- [x] **`get_inbox_overview`** — `compact` / JSON modes; toggles for mailboxes, previews, suggestions (`inbox.py`)
- [x] **Analysis tools** — remove unfiltered `every message of` fallbacks (`smart_inbox.py`)
- [ ] **`include_timing` telemetry** — deferred to Phase B `perf-test` (not implemented in A)
- [x] Script-shape tests: dashboard cap, account-not-found (`tests/test_phase_a_fixes.py`)

**Done when:** dashboard metadata-only &lt; 5s (stretch &lt; 3s); bad account &lt; 2s with clear error; `get_statistics --days-back 2` &lt; 10s; validation on all explicit-account paths.

---

## Phase 1 — CI guardrails (~0.5 day)

**Goal:** Drift cannot merge.

**Skills:** `plugin-structure` · `todo.md` § validator follow-ups  
**Sub-agents:** **`shell`** · **`plugin-validator`** ⛔ · **`ci-watcher`** / `ci-investigator`  
**Verify:** intentional tool-count break fails CI

- [x] `tools/validate_manifests.sh` + `tools/validate_manifests.py` — versions, tool count, mcpb names vs `@mcp.tool`
- [x] `.github/workflows/ci.yml` — `pytest tests/ -q` + validate script (macOS); **mocked tests only — no live Mail.app**
- [x] Optional pre-commit hook — `tools/pre-commit-validate.sh` (manifest + pytest); documented in `docs/AGENT_LIVE_TESTING.md`

**Done when:** CI green; manifest drift fails the job.

---

## Phase B — Agent CLI (1–2 days)

**Goal:** `.venv/bin/apple-mail` replaces generated wrapper for testing.

**Skills:** **`create-cli`** · `mcp-integration` · `testing-python` · CLI report  
**Sub-agents:** **`explore`** · **`generalPurpose`** · `shell` (live perf run)  
**Verify:** `apple-mail perf-test --json` on real Mail

- [x] **`perf-test` + `quick-check`** — live opt-in gate with redacted default output; thresholds in cli.py; `tests/test_cli_perf.py`. Live on `ai.openclaw`: quick-check **1.9s**, full perf-test **4.2s** (2026-05-21).
- [x] **`perf-test` gaps** — `bad_account` + `dashboard_metadata` cases; `--verbose-sensitive`; `_redact` hides account names/addresses by default
- [x] CLI wrappers: `unread`, `overview`, `needs-response`, `awaiting-reply`, `top-senders`, `statistics`, `move-dry-run`, `trash-dry-run`, `drafts list`
- [x] `docs/AGENT_LIVE_TESTING.md` — all commands, perf flags, smoke checks, post-edit workflow
- [x] Extend `smoke-test`: `invalid_account` + `draft_safe_send_block`

**Done when:** full safe suite runs via repo CLI only. ✅

---

## Phase 2 — Scan-path hardening (2–3 days)

**Goal:** No unbounded mailbox enumeration (24K Exchange safe).

**Skills:** `CLAUDE.md` perf · `id-first-refactor-spec.md` · `python-performance-optimization` · **`testing-python`**  
**Sub-agents:** **`explore`** (grep audit) · parent agent · `reviewing-code` · optional `thermo-nuclear-code-quality-review`  
**Verify:** grep audit; `pytest tests/ -q`

- [x] **`get_email_thread`** — whose + date cap + `timeout` / `recent_days` + tests (`GetEmailThreadTests`)
- [x] **Compose reply/forward** — capped lookup via `_build_found_message_lookup` (`recent_days` default 2.0); draft send/open/delete via `_build_draft_lookup`
- [x] **`manage_drafts` list** — cap `messages 1 thru {DRAFT_LIST_CAP}` on list action
- [x] **`message_ids`** on `move_email`, `manage_trash`, `save_email_attachment`
- [x] Add `timeout` to: `get_email_by_id`, `get_email_thread`, `save_email_attachment`, `get_mailbox_unread_counts`

**Done when:** no bare `every message of` without whose/cap; thread + compose tests pass.

---

## Phase 3 — MCP quality (2–3 days)

**Goal:** Agent-friendly tools (annotations, consistent JSON).

**Skills:** **`mcp-builder`** · `testing-python`  
**Sub-agents:** **`explore`** (annotation matrix) · `generalPurpose` · **`plugin-validator`** if descriptions change  
**Verify:** `/mcp` tool list; wrapper JSON spot-check

- [ ] **Confirm installed `fastmcp` supports intended annotation API** — confirmed MCP SDK `ToolAnnotations` on `@mcp.tool(annotations=...)` ✅
- [x] FastMCP annotations on all 27 tools (read/destructive/idempotent/openWorld) — `READ_ONLY`, `WRITE`, `IDEMPOTENT_WRITE`, `DESTRUCTIVE` constants in `server.py`
- [x] Standardize `Error:` prefix — compose, search, manage (20 strings); tests in `test_phase_a_fixes.py`
- [ ] **JSON normalization in stages** — `get_statistics` ✅, `get_inbox_overview` ✅; next: `inbox_dashboard`, smart_inbox four
- [ ] JSON tools return dict/list, not JSON strings
- [ ] `list_inbox_emails` always `{emails, errors}` in JSON mode
- [ ] Migrate compose osascript bypasses → `run_applescript()` ✅
- [ ] Test: `--read-only` removes send tools from registry — `tests/test_read_only_registry.py` covers annotations + send-tool removal pattern ✅

**Done when:** annotated; wrapper JSON consistent; read-only registry test passes.

---

## Phase 4 — Hygiene (1–2 days)

**Goal:** Dedup + launcher + discoverability.

**Skills:** `CLAUDE.md` · `reviewing-code` · `plugin-structure`  
**Sub-agents:** parent agent · **`plugin-architect`** · **`plugin-validator`** ⛔ · `shell` (mcpb)  
**Verify:** pytest; fresh venv `import fastmcp`

- [x] `SENSITIVE_DIRS` + `validate_save_path()` → `core.py`
- [x] Dedup compose: `_split_addresses` ✅, CC/BCC builder ✅
- [ ] Replace `except: pass` → `errors[]` — inbox overview parse errors ✅; remaining analytics/smart_inbox if any
- [x] Align `fastmcp` pin `>=3.1.0,<4` (requirements + pyproject)
- [x] `start_mcp.sh`: verify `import fastmcp` after venv create
- [ ] Refresh `build-mcpb.sh` README; bump mcpb `dxt_version` if valid
- [x] `keywords` + `category` in `plugin.json`

---

## Phase 5 — Skills & marketplace (paused)

**Goal:** Sibling skills + polish. **Do not start until Phase A + B + 1 complete.**

**Skills:** **`skill-development`** · `CLAUDE.md` § Skill authoring · template `email-management/SKILL.md` · `mcp-builder` (registry)  
**Sub-agents:** **`plugin-architect`** · **`skill-reviewer`** ⛔ per skill · **`plugin-validator`** ⛔ · `explore` (SQLite study, readonly)

- [ ] Deprecate `plugin/commands/email-management.md`
- [ ] Skills: `email-drafting`, `inbox-triage`, `email-attachments` (each → skill-reviewer)
- [ ] Optional `plugin/.mcp.json`
- [ ] MCP registry submit (`server.json`)
- [ ] Hybrid SQLite read-path spike — **only if AppleScript remains too slow after Phases A/B/2 are benchmarked**; undocumented Mail schema; feature-flagged (review #10)

---

## Orchestrator checklist (every phase)

1. Read phase skills (table above)
2. Delegate **`explore`** before unfamiliar edits (A, 2, 3)
3. Implement → `pytest tests/ -q`
4. **`plugin-validator`** after manifest/shell changes ⛔ — if unavailable, run `tools/validate_manifests.sh` + `rg '^@mcp\.tool' plugin/apple_mail_mcp/tools/*.py | wc -l` (expect 27) and note the gap in the PR
5. **`skill-reviewer`** after any `plugin/skills/*/SKILL.md` change ⛔ — same fallback: local frontmatter checklist + document missing reviewer
6. `verification-before-completion` before closing phase

### Parallel batches

**Phase 0:** `generalPurpose` (edits) + `shell` (pytest/grep) → then **`plugin-validator`** + `skill-reviewer`

**Phase A:** **`explore`** (call graph) ∥ `generalPurpose` (account helper) → parent (dashboard) → live smoke + perf check

---

## Quick commands

```bash
.venv/bin/pytest tests/ -q
rg '^@mcp\.tool' plugin/apple_mail_mcp/tools/*.py | wc -l   # expect 27
.venv/bin/apple-mail quick-check --json                      # ~30s post-edit loop
.venv/bin/apple-mail perf-test --account ai.openclaw --json  # full live gate
.venv/bin/apple-mail smoke-test --account ai.openclaw --json
.venv/bin/python plugin/apple_mail_mcp.py --draft-safe --help
```

# Apple Mail MCP Plugin — Audit Report & Action Plan

**Concise checklist:** [`phase-plan-3.1.6.md`](phase-plan-3.1.6.md)

**Date:** 2026-05-21 (updated after live CLI validation)  
**Branch validated:** `improve-speed-and-tools` @ `e4a7670`  
**Scope:** Plugin structure, MCP integration, marketplace readiness, server quality, performance, test coverage, and live Mail.app CLI testing  
**Method:** Initial repo exploration + four parallel specialist reviews + code verification against `tasks/todo.md` and `CLI_TESTING_REPORT_2026-05-21.md`  
**Test baseline:** 113 tests passing (`.venv/bin/pytest tests/ -q`)

---

## Executive Summary

The apple-mail-mcp project is **architecturally sound** and **functionally mature** for a macOS-only Apple Mail bridge. The three-distribution model (PyPI package, Claude Code plugin, Claude Desktop `.mcpb` bundle) is correctly separated, versions are synchronized at **3.1.5**, and the modernization work in 3.1.5 left a strong foundation: AppleScript-side caps, `recent_days` defaults, async per-account fan-out, and 113 unit tests.

**However, the plugin is not yet marketplace-ready** in the strict sense. The primary blocker is **manifest drift**: the live Python server registers **27 tools**, but the Claude Desktop bundle manifest lists **26** and omits `get_email_by_id`. Several user-facing descriptions still claim 26 tools. Beyond metadata sync, there are **performance regressions** in legacy code paths (`get_email_thread`, compose reply/forward lookup), **no CI pipeline**, **no MCP tool annotations**, and **10 of 27 tools** lack meaningful test coverage.

**Overall grade:**

| Area | Grade | Notes |
|------|-------|-------|
| Plugin directory structure | **A-** | Conventional layout; minor legacy command overlap |
| MCP server implementation | **B+** | Strong core; legacy scan paths remain |
| MCP integration (Claude Code) | **A-** | Inline `mcpServers` works; optional `.mcp.json` polish |
| Marketplace wiring | **B** | Correct `source` path; stale tool count in description |
| Claude Desktop bundle (mcpb) | **C+** | Missing tool entry; stale build README |
| Test suite | **B** | 113 passing; gaps on thread, overview, read-only registry |
| CI / automated validation | **F** | No `.github/workflows`; no manifest drift guard |
| Performance (large mailboxes) | **B** | Core agent paths fast on live mailbox; dashboard + analysis tools still slow |
| Live agent CLI readiness | **B+** | Repo CLI + smoke-test solid; perf-test + expanded wrappers missing |

**Revised bottom line after live testing:** The `improve-speed-and-tools` branch has already landed the highest-impact speed wins for day-to-day agent workflows (accounts, inbox, search, show, dry-run move/trash). The remaining pain is **not** uniformly distributed — it clusters in `inbox_dashboard`, invalid-account handling, analysis/statistics tools, and wrapper JSON inconsistency. Manifest sync and CI are still release blockers; performance work should now prioritize what live testing actually measured, not the earlier `move_email` dry-run regression (which no longer reproduces on this branch).

---

## Live CLI Testing Validation (2026-05-21)

Cross-checked [`CLI_TESTING_REPORT_2026-05-21.md`](../CLI_TESTING_REPORT_2026-05-21.md) against the codebase on branch `improve-speed-and-tools`.

### Confirmed working (code + live)

| Workflow | Repo CLI | Generated wrapper | Evidence |
|----------|----------|-------------------|----------|
| List accounts / addresses | ~0.37–0.45s | ~0.59–0.63s | `cli.py` → `list_accounts`, `list_account_addresses` |
| Limited inbox read | ~0.60s | ~0.77s | `list_inbox_emails` with caps + async fan-out |
| No-hit search | ~0.49s | ~0.62s | `search_emails` whose + scan_cap |
| Exact-id read (`show`) | ~0.58s | — | `get_email_by_id` |
| Smoke test | ~0.88s | — | `cli.py:_cmd_smoke_test` (implemented) |
| No-hit dry-run move/trash | — | ~0.61s each | **Fixed** — earlier 61s regression does not reproduce |
| Unread summary | — | ~0.83s | `get_mailbox_unread_counts(summary_only=True)` |
| `--draft-safe` flag | — | — | Present in `__main__.py:48-55`; `mcp-config` defaults to `--draft-safe` |

### Confirmed broken or weak (code root cause verified)

| Issue | Live symptom | Code root cause |
|-------|--------------|-----------------|
| **`inbox_dashboard` timeout** | 40s wrapper timeout | `analytics.py:869-911` — sync cross-account call chain: `get_mailbox_unread_counts(summary_only=True)` + `_get_recent_emails_structured(max_total=20, max_per_account=10)`. Helper at `analytics.py:782-845` reads **`content of aMessage`** for 150-char previews across **every account** in one blocking AppleScript. No async, no `include_preview` toggle, no account scoping. |
| **Unknown account handling** | Wrapper 40s timeout; repo CLI ~12s empty success | `inbox.py:113` — `set anAccount to account "{escaped_account}"` with no pre-flight check against `_list_mail_accounts()` (~0.4s). Mail.app hangs or errors slowly on nonexistent account names. No `account_not_found` structured error anywhere in codebase (grep confirms). |
| **Analysis tools slow** | 6–23s on conservative params | `smart_inbox.py` / `analytics.py` — whose+cap present but still extract many properties; error fallbacks at lines 166-167, 186-187 revert to unfiltered `every message of`. Property extraction dominates wall time even when caps exist. |
| **`get_inbox_overview` payload** | ~10s, ~8.7KB text | `inbox.py:1129-1176` — always returns full formatted overview (unread + mailboxes + suggestions). No compact/JSON/account-scoped modes. Async per-account is already implemented. |
| **Wrapper JSON inconsistency** | Nested `content` / `structuredContent.result` | Tools that return plain strings (e.g. overview text) get wrapped by mcporter; tools returning parsed JSON dicts emit clean arrays. Fix belongs in Python tools (`output_format="json"`) + consistent return types, not the wrapper alone. |

### Important nuance: repo CLI vs generated wrapper

The repo-owned CLI (`plugin/apple_mail_mcp/cli.py`) currently exposes **9 commands**:

`accounts`, `addresses`, `inbox`, `search`, `show`, `mailboxes`, `draft`, `mcp-config`, `smoke-test`

It does **not** yet expose: `inbox-dashboard`, `perf-test`, `overview`, `unread`, analysis tools, or dry-run move/trash. The CLI report's `inbox-dashboard` timeout came from the **generated mcporter wrapper** calling the MCP tool directly — not from a repo CLI subcommand. Expanding the repo CLI (per todo) is the right way to give agents a stable, predictable testing surface.

---

## Todo List Reconciliation (`tasks/todo.md`)

Validated each in-flight item against current code on `improve-speed-and-tools`:

| Todo item | Status | Notes |
|-----------|--------|-------|
| Restore `--draft-safe` | **DONE — todo stale** | Implemented in `__main__.py:48-55`. Live: `--help` shows flag. `mcp-config` emits `--draft-safe` by default. Mark done in todo.md. |
| Repo-owned portable CLI | **PARTIAL** | `pyproject.toml` ships `apple-mail` entry; `cli.py` has 9 commands. Missing: perf-test, overview, unread, analysis wrappers, dry-run helpers. |
| `apple-mail smoke-test` | **DONE** | `cli.py:163-350` — accounts + inbox + no-hit search with redaction. Mark done. |
| `apple-mail perf-test` | **NOT STARTED** | No `perf-test` parser or handler in `cli.py`. Still needed. |
| Agent live-testing docs | **NOT STARTED** | CLI report exists; no dedicated agent setup doc in README yet. |
| One shared tool path | **PARTIAL** | Repo CLI wraps same Python functions; generated wrapper now points at repo plugin per CLI report. Document the canonical config. |
| Fix `inbox_dashboard` timeout | **VALID — P1** | Root cause confirmed in code above. Highest live-testing priority. |
| Unknown account validation | **VALID — P1** | No `validate_account()` helper exists; cheap fix via `_list_mail_accounts()` pre-check. |
| Optimize `get_inbox_overview` | **VALID — P1** | Async exists; needs compact/JSON/toggle params. |
| Optimize analysis tools | **VALID — P1** | Live timings confirm; fallbacks are code-level risk. |
| Expand repo CLI coverage | **VALID — P2** | Aligns with perf-test and agent testing goals. |
| Normalize wrapper JSON | **VALID — P2** | Requires Python-side `output_format="json"` consistency. |
| Timing telemetry | **VALID — P2** | Not implemented; would help debug remaining slow paths. |
| Exact-id action paths | **PARTIAL** | `update_email_status` has `message_ids`; `move_email`/`manage_trash`/`save_email_attachment` do not yet (see `tasks/id-first-refactor-spec.md`). |
| `start_mcp.sh` Python 3.10+ | **DONE — todo stale** | Script already requires 3.10+ (lines 30-31, 46). Remaining gap: verify `import fastmcp` after venv creation. |
| CI manifest drift guard | **VALID — P0/P1** | Still no `.github/workflows` or `validate_manifests.sh`. |
| Conservative dedup + hygiene | **VALID — P2** | Unchanged from original audit. |
| Future skills | **PAUSED** | Correct to defer until hardening complete. |

---

## Repository Architecture (How It Works)

```
apple-mail-mcp/                          # Monorepo root
├── .claude-plugin/marketplace.json      # Marketplace manifest → points at ./plugin
├── pyproject.toml                       # PyPI: mcp-apple-mail (packages plugin/apple_mail_mcp)
├── server.json                          # MCP registry metadata (PyPI stdio transport)
├── plugin/                              # Claude Code plugin root (source of truth for wrapper)
│   ├── .claude-plugin/plugin.json       # Plugin manifest + inline mcpServers
│   ├── start_mcp.sh                     # Lazy venv creator → exec apple_mail_mcp.py
│   ├── apple_mail_mcp.py                # Thin entry shim
│   ├── requirements.txt                 # Plugin runtime pins (fastmcp==3.1.0)
│   ├── commands/email-management.md     # Legacy slash command → skill pointer
│   ├── skills/email-management/         # Primary agent entry point (SKILL.md)
│   └── apple_mail_mcp/                  # Python MCP package
│       ├── __main__.py                  # --read-only, --draft-safe, orphan watcher
│       ├── server.py                    # FastMCP instance, env vars
│       ├── core.py                      # AppleScript bridge (escape, timeout, whose helpers)
│       └── tools/                       # 27 @mcp.tool registrations across 6 modules
└── apple-mail-mcpb/                     # Claude Desktop bundle build
    ├── manifest.json                    # tools[] array + server.mcp_config
    └── build-mcpb.sh                    # Copies plugin/ → .mcpb artifact
```

**Runtime flow:**

1. Claude Code enables plugin → reads `plugin/.claude-plugin/plugin.json`
2. MCP client spawns `/bin/bash ${CLAUDE_PLUGIN_ROOT}/start_mcp.sh`
3. `start_mcp.sh` creates `plugin/venv/` on first run, installs `requirements.txt`
4. Python entry runs `apple_mail_mcp/__main__.py` → imports tool modules → `mcp.run()` (stdio)
5. All Mail.app interaction goes through `core.run_applescript()` with `escape_applescript()` on user strings

**Distribution channels:**

| Channel | Entry | Audience |
|---------|-------|----------|
| Claude Code plugin | `plugin/` via marketplace | Primary target |
| PyPI | `pip install mcp-apple-mail` | Generic MCP clients |
| Claude Desktop | `apple-mail-mcpb/` bundle | Desktop users |
| Local CLI | `apple-mail` console script | Agent smoke/perf testing |

---

## Findings by Area

### 1. Plugin Structure (plugin-structure compliance)

**PASS — Core layout is correct**

- Manifest at `plugin/.claude-plugin/plugin.json` ✓
- Components at plugin root (`commands/`, `skills/`) not nested under `.claude-plugin/` ✓
- Marketplace at repo root `.claude-plugin/marketplace.json` with `"source": "./plugin"` ✓
- Portable paths: `${CLAUDE_PLUGIN_ROOT}/start_mcp.sh` in plugin.json ✓
- `start_mcp.sh` resolves paths via `BASH_SOURCE[0]` ✓

**WARN — Optional / stylistic gaps**

| Item | Severity | Detail |
|------|----------|--------|
| No dedicated `plugin/.mcp.json` | Low | MCP config inline in `plugin.json` is valid; separate file recommended by mcp-integration skill for maintainability |
| No `agents/` or `hooks/` | None | Correctly omitted until needed |
| Legacy command duplicates skill | Medium | `plugin/commands/email-management.md` overlaps `skills/email-management/`; CLAUDE.md policy is skills-only for new entry points |
| `plugin/ui/` not auto-discovered | Low | Dashboard UI is server-internal, not a plugin component |
| `.gitignore` ignores `.mcp.json` | Low | Blocks committed MCP config if Method 1 adopted |

**Skill quality — PASS**

`plugin/skills/email-management/SKILL.md` follows repo conventions:
- Directory name matches frontmatter `name: email-management`
- Rich description with "Do NOT use for…" sibling routing
- ~1,583 words (target 1,500–2,000)
- Performance defaults, decision tree, destructive-op table present

**Skill doc bug:** Line 51 references `confirm=True` for `empty_trash`; actual API is `confirm_empty=True`.

---

### 2. Marketplace & Manifest Validation (plugin-validator)

**PASS — Version sync across 5 release files**

All at `3.1.5`: `pyproject.toml`, `plugin.json`, `marketplace.json` (plugin entry), `server.json`, `apple-mail-mcpb/manifest.json`.

Marketplace `metadata.version` `1.0.0` is intentionally separate (marketplace manifest version).

**FAIL — Tool count and registry drift**

| Source | Claimed | Actual | Status |
|--------|---------|--------|--------|
| Python `@mcp.tool` grep | — | **27** | Ground truth |
| `plugin/.claude-plugin/plugin.json` description | 27 | 27 | ✓ |
| `.claude-plugin/marketplace.json` description | 26 | 27 | ✗ |
| `apple-mail-mcpb/manifest.json` description | 26 | 27 | ✗ |
| `apple-mail-mcpb/manifest.json` `tools[]` array | 26 entries | 27 registered | ✗ |
| `CLAUDE.md` | 26 | 27 | ✗ |
| `README.md` § Tools | 27 | 27 | ✓ |
| `README.md` architecture tree | 26 | 27 | ✗ |
| `plugin/apple_mail_mcp/__init__.py` comments | 24 (5+2+5+5+4+3) | 27 (6+3+5+6+4+3) | ✗ |
| `plugin/skills/email-management/README.md` | 25 | 27 | ✗ |

**Missing from mcpb `tools[]`:** `get_email_by_id` (implemented in `search.py`, documented in README, absent from Desktop bundle manifest).

**Root cause:** `get_email_by_id` was added after the 3.1.5 manifest rebuild that corrected an earlier 27→26 drift (see `tasks/todo.md` Done section). The new tool was not propagated to mcpb/marketplace/docs.

**Other manifest notes:**

- MCP wiring: inline `mcpServers` in `plugin.json` — valid, no separate `.mcp.json` required
- `start_mcp.sh` is `-rw-r--r--` in git (non-executable); works because both configs invoke via `/bin/bash`
- `apple-mail-mcpb/build-mcpb.sh` embedded README is stale ("18 tools"; Python version fixed to 3.10+)
- mcpb `dxt_version: "0.1"` — may need bump to `0.2` per latest spec (verify with mcpb CLI)

---

### 3. MCP Server Quality (mcp-builder / mcp-integration)

**Strengths**

- Clear entry → registration → AppleScript bridge architecture
- `escape_applescript()` applied consistently on user-supplied strings
- `AppleScriptTimeout` with structured error returns on modernized tools
- `@inject_preferences` decorates user-facing tools with env-var context
- Read-only mode removes send tools from registry; draft-safe blocks sends at runtime
- Orphan watcher prevents Mail.app relaunch after client disconnect (SDK #526 workaround)
- Security: dry-run defaults on destructive tools, path validation on exports/attachments

**Gaps vs MCP best practices**

| Gap | Severity | Impact |
|-----|----------|--------|
| Zero FastMCP tool annotations (`readOnlyHint`, `destructiveHint`, etc.) | **High** | Clients cannot distinguish safe reads from destructive ops without parsing docstrings |
| No structured output schemas | **High** | Most tools return ad-hoc strings; JSON shape inconsistent across tools |
| No evaluation suite in CI | **Medium** | mcp-builder eval tooling exists in `.agents/skills/` but not integrated |
| Error prefix inconsistency (`Error:` vs `ERROR:`) | **Medium** | Agent parsing friction |
| Single-account vs multi-account JSON shape mismatch (`list_inbox_emails`) | **Medium** | Bare array vs `{emails, errors}` object |

**Tool inventory (27 tools)**

| Module | Count | Tools |
|--------|------:|-------|
| inbox | 6 | list_inbox_emails, get_mailbox_unread_counts, list_accounts, list_account_addresses, list_mailboxes, get_inbox_overview |
| search | 3 | search_emails, get_email_by_id, get_email_thread |
| compose | 5 | compose_email, reply_to_email, forward_email, create_rich_email_draft, manage_drafts |
| manage | 6 | move_email, save_email_attachment, update_email_status, manage_trash, create_mailbox, synchronize_account |
| analytics | 4 | list_email_attachments, get_statistics, export_emails, inbox_dashboard |
| smart_inbox | 3 | get_awaiting_reply, get_needs_response, get_top_senders |

**Read-only / draft-safe behavior**

- `--read-only`: sets `READ_ONLY`, enables `DRAFT_SAFE`, removes `compose_email`, `reply_to_email`, `forward_email` from registry
- `--draft-safe`: sets `DRAFT_SAFE` only; send tools remain registered but `_send_blocked()` rejects `mode="send"`
- **Note:** `tasks/todo.md` lists restoring `--draft-safe` as in-flight; code in `__main__.py` already supports it — verify live agent configs point at current checkout

**Unmigrated osascript bypasses (compose.py)**

Three `subprocess.run(["osascript", ...])` call sites bypass `run_applescript()`:
- `_send_html_email` (~539)
- `reply_to_email` HTML path (~941)
- `forward_email` with message (~1450)

All use hardcoded 30s timeout; inconsistent error surface for agents.

---

### 4. Performance & Anti-Patterns (python-performance-optimization / CLAUDE.md)

**Modernized tools (templates to follow):** `search_emails`, `list_inbox_emails`, `move_email`, `update_email_status`, `manage_trash`, smart_inbox getters, `get_statistics`, `export_emails`.

**Critical performance hotspots**

| Severity | Location | Issue |
|----------|----------|-------|
| **Critical** | `get_email_thread` | `every message of currentMailbox` — no `whose`, no date cap, no timeout param |
| **Critical** | `reply_to_email`, `forward_email` | Linear inbox scan via `every message of inboxMailbox` |
| **High** | `smart_inbox.py` error fallbacks | On `whose` failure, falls back to unfiltered `every message of` |
| **High** | Live perf (2026-05-21) | `inbox_dashboard` ~40s timeout; `get_statistics` ~23s; `get_needs_response` ~14s |
| **Medium** | `manage_drafts` list | Unbounded `every message of draftsMailbox` |
| **Medium** | `get_mailbox_unread_counts` | Full mailbox tree enumeration, no timeout param |

**Clean anti-patterns:** No `LOWERCASE_HANDLER`, no shell `tr` per message, `ignoring case` used correctly in modernized code.

**Tools missing `timeout` parameter:** `get_mailbox_unread_counts`, `list_accounts`, `list_account_addresses`, `list_mailboxes`, `get_email_by_id`, `get_email_thread`, `save_email_attachment`, `create_mailbox`, `inbox_dashboard`.

---

### 5. Test Coverage

**113 tests across 7 files — all passing**

| Test file | Count | Primary coverage |
|-----------|------:|------------------|
| test_compose_tools.py | 39 | Rich drafts, draft-safe, sender override, escaping |
| test_mail_search_tools.py | 27 | Search caps, pagination, parallel dispatch, timeouts |
| test_modernization_3_1_5.py | 25 | DEFAULT_MAIL_ACCOUNT, whose+cap, timeout handling |
| test_bulk_helpers.py | 12 | escape_applescript, filter builders |
| test_cli.py | 5 | Portable CLI wrapper |
| test_inbox_tools.py | 3 | JSON/text parsing helpers |
| test_orphan_watcher.py | 2 | PPID reparent exit |

**Coverage ratio:** ~17/27 tools have meaningful tests; **10 tools** have none or smoke-only checks.

**Untested / weak coverage:**

| Tool | Risk |
|------|------|
| `get_email_thread` | Unbounded scan; zero tests |
| `get_inbox_overview` | Slow live path; zero tests |
| `get_mailbox_unread_counts` | — |
| `list_account_addresses`, `list_mailboxes` | — |
| `save_email_attachment` | Path validation only |
| `synchronize_account`, `create_mailbox` | — |
| `inbox_dashboard` | UI resource path |
| `--read-only` `remove_tool` integration | No registry-level test |

**No CI:** No `.github/workflows/` directory. No pre-commit hooks for manifest drift. Tests run locally only.

---

## Consolidated Issue Register

### P0 — Blocking (marketplace / bundle honesty)

| # | Issue | Files affected |
|---|-------|----------------|
| 1 | Add `get_email_by_id` to mcpb `tools[]` | `apple-mail-mcpb/manifest.json` |
| 2 | Update tool count to **27** everywhere | `marketplace.json`, mcpb description, `CLAUDE.md`, README tree, `__init__.py` comments |
| 3 | Run plugin-validator after manifest edits | — |

### P1 — High priority (correctness / performance / agent safety)

| # | Issue | Files affected |
|---|-------|----------------|
| 4 | Fix `get_email_thread` unbounded mailbox scan | `search.py` |
| 5 | Fix compose reply/forward inbox lookup scans | `compose.py` |
| 6 | Add FastMCP tool annotations (read/destructive hints) | All `tools/*.py` |
| 7 | Add CI workflow: pytest + manifest drift guard | `.github/workflows/`, `tools/validate_manifests.sh` |
| 8 | Fix smart_inbox error fallbacks to unfiltered scans | `smart_inbox.py` |
| ~~9~~ | ~~Investigate `move_email` dry-run no-hit 61s regression~~ | **RESOLVED** on `improve-speed-and-tools` — live ~0.61s (CLI report) |
| 9 | **`inbox_dashboard` timeout** — metadata-only default, async/per-account, preview toggle | `analytics.py`, `ui/dashboard.py` |
| 10 | **Unknown account pre-validation** — structured `account_not_found` before AppleScript | `core.py` (new helper), `inbox.py`, all account-scoped tools |
| 11 | Fix skill doc bug: `confirm=True` → `confirm_empty=True` | `plugin/skills/email-management/SKILL.md:51` |

### P2 — Medium priority (hygiene / DX / hardening)

| # | Issue | Files affected |
|---|-------|----------------|
| 11 | Migrate 3 compose osascript bypasses through `run_applescript()` | `compose.py` |
| 12 | Add `timeout` param to remaining tools | inbox, search, analytics modules |
| 13 | Replace `except: pass` swallows with `errors[]` lists | analytics, smart_inbox, manage, compose |
| 14 | Consolidate duplicated helpers (SENSITIVE_DIRS, _split_addresses, CC/BCC builder) | compose.py, analytics.py, core.py |
| 15 | Align fastmcp pin: `>=3.1.0,<4` in both requirements.txt and pyproject.toml | Both files |
| 16 | `start_mcp.sh`: verify venv has importable fastmcp after creation | `start_mcp.sh` |
| 17 | Refresh `build-mcpb.sh` embedded README (tool count, Python 3.10+) | `apple-mail-mcpb/build-mcpb.sh` |
| 18 | Add test for `--read-only` tool registry stripping | `tests/` |
| 19 | Add script-shape tests for `get_email_thread` | `tests/test_mail_search_tools.py` |
| 20 | Normalize JSON response shapes (single vs multi-account) | `inbox.py` |
| 21 | Add `keywords` + `category` to plugin.json for marketplace discoverability | `plugin.json` |
| 22 | Deprecate or remove legacy `commands/email-management.md` | `plugin/commands/` |

### P3 — Future / deferred

| # | Item | Notes |
|---|------|-------|
| 23 | Three sibling skills (email-drafting, inbox-triage, email-attachments) | Paused until hardening complete |
| 24 | Hybrid SQLite read-path prototype | Envelope Index for read-only ops |
| 25 | MCP evaluation suite in CI | 10 complex read-only Q&A pairs per mcp-builder guide |
| 26 | Structured output schemas for all tools | Pydantic return types / JSON Schema |
| 27 | Timing telemetry (`include_timing` param) | Per tasks/todo.md |
| 28 | Portable CLI `perf-test` + expanded wrappers | **smoke-test done**; perf-test + overview/analysis/dry-run wrappers still needed |
| 29 | Submit `server.json` to MCP registry | Gate on version bump |
| 30 | Dedicated `plugin/.mcp.json` | Optional structural polish |

---

## Action Plan (Revised — validated against live testing)

The original five-phase plan remains directionally correct, but **sequencing changes** after live CLI validation. The branch already fixed the core agent path performance; the next PR should lead with **live-measured pain points** before theoretical scan-path fixes (`get_email_thread`, compose lookup) that did not appear in the CLI sweep.

### Recommended path: **3.1.6 = sync + live fixes + CI**, then hardening

```
Phase 0 (manifest sync, ~2h)
    ↓
Phase A (live-testing fixes, 2–3 days)  ← NEW: highest user-visible ROI
    ↓
Phase 1 (CI guardrails, half day)
    ↓
Phase B (agent CLI completion, 1–2 days)
    ↓
Phase 2 (legacy scan-path hardening, 2–3 days)
    ↓
Phase 3 (MCP quality) → Phase 4 (docs) → Phase 5 (skills)
```

**Why this order:** Phase 0 is mechanical and unblocks marketplace honesty. Phase A fixes what live testing actually hit (dashboard timeout, bad account UX, slow analysis). Phase 1 prevents drift recurrence. Phase B makes agents self-sufficient without the generated wrapper. Phase 2 addresses large-mailbox edge cases (`get_email_thread`, compose lookup) that unit tests flag but live testing didn't exercise on `ai.openclaw`.

---

## Skills & Sub-agents by Phase

Each phase lists **skills to read before starting** (procedural guidance) and **sub-agents to delegate** (autonomous review/execution). Run validators **after** edits in the same phase, not before.

### Master reference

| Skill (path) | Use when |
|--------------|----------|
| `plugin-dev:plugin-structure` | Manifest paths, component layout, `${CLAUDE_PLUGIN_ROOT}` |
| `plugin-dev:mcp-integration` | MCP wiring, `.mcp.json`, stdio launcher, env vars |
| `plugin-dev:skill-development` | Authoring or editing skills under `plugin/skills/` |
| `plugin-dev:skill-reviewer` | Review skill frontmatter after create/edit (blocking for skills) |
| `plugin-dev:plugin-settings` | Plugin config / `.local.md` patterns (if needed) |
| `.agents/skills/mcp-builder/SKILL.md` | Tool annotations, output schemas, eval suite, MCP best practices |
| `.agents/skills/python-performance-optimization/SKILL.md` | AppleScript cap patterns, async fan-out, profiling slow tools |
| `.agents/skills/testing-python/SKILL.md` | pytest fixtures, script-shape tests, mocking `subprocess.run` |
| `.agents/skills/reviewing-code/SKILL.md` | Pre-merge review of tool/CLI changes |
| `create-cli` (`.claude/skills/create-cli/SKILL.md`) | `apple-mail perf-test` and new CLI subcommands |
| `verification-before-completion` (superpowers) | Before claiming any phase done — run tests + live checks |
| `CLAUDE.md` (repo root) | Tool conventions, version bump checklist, skills-only policy |

| Sub-agent (`Task` type) | Use when |
|-------------------------|----------|
| `plugin-validator` | After manifest, plugin.json, marketplace, mcpb, or tool-count changes — **blocking** |
| `plugin-architect` | Structure decisions, `.mcp.json` split, marketplace layout questions |
| `plugin-dev:skill-reviewer` (via Task or direct) | Skill frontmatter quality — **blocking for skill changes** |
| `explore` | Read-only codebase recon before touching unfamiliar modules |
| `generalPurpose` | Multi-step implementation with tests (account helper, CLI commands) |
| `shell` | Running pytest, building mcpb, git/CI script setup |
| `ci-watcher` / `ci-investigator` | After Phase 1 CI lands — monitor/fix failing checks on PR |
| `review-and-ship` (cursor-team-kit) | End-of-phase review: diff, tests, PR readiness |
| `thermo-nuclear-code-quality-review` | Optional deep audit after Phase 2/3 if diff is large |

---

### Phase 0: Manifest sync — skills & sub-agents

| Role | Resource |
|------|----------|
| **Read first** | `plugin-dev:plugin-structure`, `plugin-dev:mcp-integration`, `CLAUDE.md` § Versioning |
| **Implement** | Parent agent or `generalPurpose` — mechanical manifest edits |
| **Validate (blocking)** | **`plugin-validator`** sub-agent |
| **Skill touch** | `plugin-dev:skill-reviewer` on `plugin/skills/email-management/SKILL.md` (line 51 fix only) |
| **Verify** | `verification-before-completion` — grep tool count, `pytest tests/ -q` |
| **Shell** | `shell` — rebuild mcpb via `apple-mail-mcpb/build-mcpb.sh` |

---

### Phase A: Live-testing fixes — skills & sub-agents

| Role | Resource |
|------|----------|
| **Read first** | `CLAUDE.md` § Tool-implementation conventions, `.agents/skills/python-performance-optimization/SKILL.md`, `CLI_TESTING_REPORT_2026-05-21.md` |
| **Explore** | **`explore`** — map `inbox_dashboard`, `_get_recent_emails_structured`, account-scoped entry points before edit |
| **Implement** | Parent agent or **`generalPurpose`** — dashboard refactor, `validate_account_name`, overview compact modes, smart_inbox fallbacks |
| **Performance review** | **`generalPurpose`** or parent — re-run live timings against Phase A exit criteria |
| **Tests** | `.agents/skills/testing-python/SKILL.md` — script-shape tests for dashboard cap, account-not-found |
| **Code review** | `.agents/skills/reviewing-code/SKILL.md` or **`review-and-ship`** |
| **Validate manifests** | Only if tool signatures change → **`plugin-validator`** |
| **Verify (blocking)** | `verification-before-completion` + live: `.venv/bin/apple-mail smoke-test --json`; wrapper `inbox-dashboard` under 10s |

---

### Phase 1: CI guardrails — skills & sub-agents

| Role | Resource |
|------|----------|
| **Read first** | `plugin-dev:plugin-structure`, `tasks/todo.md` § validator follow-ups |
| **Implement** | **`shell`** — author `tools/validate_manifests.sh`, `.github/workflows/ci.yml` |
| **Validate script** | **`plugin-validator`** — confirm script checks match validator rules |
| **Monitor PR** | **`ci-watcher`** after push — report pass/fail with check links |
| **Fix failures** | **`ci-investigator`** if a specific check fails |
| **Verify** | `verification-before-completion` — break tool count intentionally, confirm CI fails |

---

### Phase B: Agent CLI completion — skills & sub-agents

| Role | Resource |
|------|----------|
| **Read first** | **`create-cli`**, `plugin-dev:mcp-integration`, `CLI_TESTING_REPORT_2026-05-21.md` § Recommended Next Work |
| **Explore** | **`explore`** — inventory existing `cli.py` commands vs todo wrapper list |
| **Implement** | **`generalPurpose`** — `perf-test`, new subcommands, extend `smoke-test` |
| **CLI UX review** | `create-cli` checklist — thresholds, redaction, exit codes, `--json` |
| **Tests** | `.agents/skills/testing-python/SKILL.md` — mock live tools in perf/smoke tests where possible |
| **Docs** | Parent agent — `docs/AGENT_LIVE_TESTING.md` using `mcp-config` output as canonical snippet |
| **Verify (blocking)** | `verification-before-completion` + live `.venv/bin/apple-mail perf-test --json` on real Mail |

---

### Phase 2: Legacy scan-path hardening — skills & sub-agents

| Role | Resource |
|------|----------|
| **Read first** | `CLAUDE.md` § Performance defaults, `tasks/id-first-refactor-spec.md`, `.agents/skills/python-performance-optimization/SKILL.md` |
| **Explore** | **`explore`** (very thorough) — grep `every message of` across `tools/*.py`, compose bypass sites |
| **Implement** | Parent agent — `get_email_thread`, compose lookup, `message_ids` on move/trash/attachments |
| **Tests (blocking)** | `.agents/skills/testing-python/SKILL.md` — script-shape tests capturing AppleScript via mocked `subprocess.run` |
| **Code review** | `.agents/skills/reviewing-code/SKILL.md` |
| **Optional deep audit** | **`thermo-nuclear-code-quality-review`** if Phase 2 PR exceeds ~500 lines |
| **Validate** | **`plugin-validator`** if mcpb tool descriptions change for new params |
| **Verify** | `verification-before-completion` — `pytest tests/ -q`; grep audit for unbounded scans |

---

### Phase 3: MCP quality uplift — skills & sub-agents

| Role | Resource |
|------|----------|
| **Read first** | **`.agents/skills/mcp-builder/SKILL.md`**, reference `mcp_best_practices.md` + `python_mcp_server.md` under `.agents/skills/mcp-builder/reference/` |
| **Explore** | **`explore`** — inventory all 27 tools for annotation matrix (read/destructive/idempotent/openWorld) |
| **Implement** | Parent agent — FastMCP annotations, JSON return normalization, compose `run_applescript` migration |
| **MCP review** | **`generalPurpose`** with mcp-builder skill — annotation completeness, error message quality |
| **Tests** | `.agents/skills/testing-python/SKILL.md` — read-only registry integration test |
| **Eval (optional)** | mcp-builder § Phase 4 — draft 10 read-only eval Q&A pairs in XML (defer CI integration to P3 #25) |
| **Validate** | **`plugin-validator`** if manifest tool descriptions must reflect new return shapes |
| **Verify** | `verification-before-completion` — `/mcp` tool list; wrapper JSON spot-check on 3 tools |

---

### Phase 4: Hygiene & dedup — skills & sub-agents

| Role | Resource |
|------|----------|
| **Read first** | `CLAUDE.md`, `tasks/todo.md` § conservative dedup, `plugin-dev:plugin-structure` |
| **Implement** | Parent agent — small focused diffs (`core.py` helpers, compose dedup, fastmcp pin, `start_mcp.sh`) |
| **Code review** | `.agents/skills/reviewing-code/SKILL.md` — ensure dedup doesn't widen touch area |
| **Plugin metadata** | **`plugin-architect`** — keywords/category in plugin.json, mcpb `dxt_version` bump decision |
| **Validate (blocking)** | **`plugin-validator`** after plugin.json / mcpb manifest edits |
| **Shell** | **`shell`** — run `build-mcpb.sh`, verify embedded README |
| **Verify** | `verification-before-completion` — full pytest; fresh venv import test via `start_mcp.sh` |

---

### Phase 5: Skills & marketplace polish — skills & sub-agents

| Role | Resource |
|------|----------|
| **Read first** | **`plugin-dev:skill-development`**, `CLAUDE.md` § Skill authoring convention, template `plugin/skills/email-management/SKILL.md` |
| **Architect** | **`plugin-architect`** — deprecate `commands/email-management.md`, optional `.mcp.json` split |
| **Author each skill** | Parent agent + **`plugin-dev:agent-creator`** if adding plugin agents later |
| **Review (blocking per skill)** | **`plugin-dev:skill-reviewer`** on frontmatter for `email-drafting`, `inbox-triage`, `email-attachments` |
| **Validate (blocking)** | **`plugin-validator`** after any manifest or skill directory change |
| **MCP registry** | `.agents/skills/mcp-builder/SKILL.md` — `server.json` submission checklist |
| **Deferred architecture** | **`explore`** (readonly) — hybrid SQLite Envelope Index feasibility study only |
| **Verify** | `verification-before-completion` + skill-reviewer pass on all three siblings before merge |

---

### Delegation pattern (orchestrator workflow)

For each phase, the **parent agent** (orchestrator) should:

1. **Read** the phase's listed skills (do not skip — they encode repo-specific rules).
2. **Delegate explore** before unfamiliar edits (Phase A, 2, 3).
3. **Implement** directly or via `generalPurpose` / `shell` for bounded tasks.
4. **Run pytest** locally (`shell`) before calling phase complete.
5. **Delegate `plugin-validator`** after any manifest or plugin-shell change — treat as **blocking**.
6. **Delegate `skill-reviewer`** after any `plugin/skills/*/SKILL.md` change — treat as **blocking**.
7. **Apply `verification-before-completion`** before updating todo.md or declaring release-ready.

Parallel delegation example for Phase 0:

```
Parallel Task batch:
  - plugin-validator  → pre-check current drift report
  - generalPurpose    → apply manifest sync edits
  - shell             → pytest + grep tool counts
Then sequential:
  - plugin-validator  → post-check (blocking)
  - skill-reviewer    → email-management SKILL.md line 51 only
```

Parallel delegation example for Phase A:

```
Parallel Task batch:
  - explore           → dashboard + account validation call graph
  - generalPurpose    → implement validate_account_name + wire list_inbox/search
Parent agent:
  - inbox_dashboard async refactor (touches analytics + ui)
Then:
  - shell             → pytest + live smoke-test
  - generalPurpose    → re-run perf timings vs exit criteria
```

---

### Phase 0: Immediate sync fix (1–2 hours) — **Do before any release**

> **Skills:** `plugin-structure`, `mcp-integration`, `CLAUDE.md` § Versioning · **Sub-agents:** `generalPurpose` (edits), **`plugin-validator`** (blocking), `skill-reviewer` (SKILL.md L51), `shell` (mcpb build)

**Goal:** Make all manifests honest and pass plugin-validator.

1. Add `get_email_by_id` entry to `apple-mail-mcpb/manifest.json` `tools[]` with description matching tool docstring.
2. Update tool count strings from 26 → **27** in:
   - `.claude-plugin/marketplace.json` (plugins[0].description)
   - `apple-mail-mcpb/manifest.json` (description)
   - `CLAUDE.md` (tool count claim + per-module counts)
   - `README.md` (architecture tree comment)
   - `plugin/apple_mail_mcp/__init__.py` (import comments: inbox 6, search 3, manage 6)
3. Fix `SKILL.md` line 51: `confirm_empty=True`.
4. Update `tasks/todo.md`: mark `--draft-safe`, `smoke-test`, and Python 3.10+ gate as done; remove stale `--draft-safe` failure note.
5. Run `plugin-dev:plugin-validator` — treat failures as blocking.
6. Rebuild mcpb bundle and spot-check tool list.

**Exit criteria:** grep confirms 27 `@mcp.tool`; mcpb `tools[]` length = 27; all descriptions say 27; validator passes.

---

### Phase A: Live-testing fixes (2–3 days) — **Target: 3.1.6 core**

> **Skills:** `CLAUDE.md` conventions, `python-performance-optimization`, `testing-python` · **Sub-agents:** **`explore`** (preflight), `generalPurpose` (implement + perf re-check), `review-and-ship`, `verification-before-completion` + live smoke

**Goal:** Fix what the CLI sweep measured on real Mail.app.

1. **`inbox_dashboard` refactor** (`analytics.py:869-911`):
   - Add params: `account`, `max_total`, `max_per_account`, `include_preview=False` (default off).
   - Split data collection: async per-account via `asyncio.to_thread` + `gather(..., return_exceptions=True)`.
   - When `include_preview=False`, skip `content of aMessage` — metadata only (subject, sender, date, read).
   - Return partial results + `errors[]` for slow accounts.
2. **Account validation helper** (`core.py`):
   - Add `validate_account_name(name) -> Optional[str]` using cached `_list_mail_accounts()` (~0.4s).
   - Return structured JSON/text error: `{"error": "account_not_found", "requested": "...", "available_count": N}`.
   - Wire into `list_inbox_emails`, `search_emails`, and all tools taking explicit `account` (single-account path first).
3. **`get_inbox_overview` compact modes** (`inbox.py:1129+`):
   - Add `output_format="text"|"json"`, `compact=True`, `include_mailboxes`, `include_suggestions`, `max_preview`.
   - Default agent-facing call: compact JSON with unread counts only.
4. **Analysis tool tuning** (`smart_inbox.py`, `analytics.py`):
   - Remove unfiltered `every message of` error fallbacks — fail with structured error instead.
   - Defer content/body extraction until after whose+cap slice is materialized.
   - Add optional `include_timing=True` on the four slow tools measured live.

**Exit criteria:** `inbox-dashboard` completes under 10s with default params; invalid account returns in <2s with clear error; `get_statistics` with `--days-back 2` under 10s on test account.

---

### Phase 1: CI & validation guardrails (half day)

> **Skills:** `plugin-structure`, `tasks/todo.md` § validator follow-ups · **Sub-agents:** **`shell`** (author CI), **`plugin-validator`** (validate script), **`ci-watcher`** / `ci-investigator` (post-push)

**Goal:** Prevent manifest drift from recurring.

1. Create `tools/validate_manifests.sh`:
   - Assert version equality across 5 release files
   - Assert `@mcp.tool` count matches mcpb `tools[]` length
   - Assert every registered tool name appears in mcpb array
   - Assert plugin.json description count matches
2. Add `.github/workflows/ci.yml`:
   - `pytest tests/ -q` on push/PR
   - Run `validate_manifests.sh`
   - Matrix: macOS (required — platform-specific code, but tests mock subprocess)
3. Optional: pre-commit hook wrapping validate script.

**Exit criteria:** CI green on main; intentional tool add without manifest update fails CI.

---

### Phase B: Agent CLI completion (1–2 days)

> **Skills:** **`create-cli`**, `mcp-integration`, `testing-python` · **Sub-agents:** **`explore`** (CLI gap inventory), **`generalPurpose`** (perf-test + wrappers), `shell` (live perf-test run)

**Goal:** Repo-owned CLI replaces generated wrapper for agent testing.

1. Add `apple-mail perf-test` with thresholds from todo.md:
   - Metadata < 2s, no-hit search < 3s, limited inbox < 5s, dry-run no-hit < 5s, overview < 10s
   - Redacted JSON/markdown output; `--verbose` for samples
2. Add CLI wrappers: `unread`, `overview`, `needs-response`, `awaiting-reply`, `top-senders`, `statistics`, `move-dry-run`, `trash-dry-run`, `drafts list`
3. Add `docs/AGENT_LIVE_TESTING.md` (or README section): permissions, `mcp-config --repo`, draft-safe default, safe command examples
4. Extend `smoke-test` to cover: invalid-account error check, draft-safe send block verification

**Exit criteria:** Agent can run full safe test suite via `.venv/bin/apple-mail` only; no mcporter wrapper required.

---

### Phase 2: Legacy scan-path hardening (2–3 days)

> **Skills:** `CLAUDE.md` perf rules, `id-first-refactor-spec.md`, `python-performance-optimization`, **`testing-python`** · **Sub-agents:** **`explore`** (grep audit), parent agent (implement), `reviewing-code`, optional `thermo-nuclear-code-quality-review`

**Goal:** Eliminate unbounded mailbox scans on large Exchange inboxes (unit-test flagged; not hit in live CLI sweep).

1. **`get_email_thread`:** Add `whose subject contains` + date window + `items 1 thru max_messages`; expose `timeout` and `recent_days` params. Add script-shape unit test.
2. **Compose reply/forward lookup:** Replace `every message of inboxMailbox` with capped `whose` clause or require `message_id` from prior search result.
3. **`manage_drafts` list:** Cap at `items 1 thru 100`.
4. **ID-first actions** (per `tasks/id-first-refactor-spec.md`): Add `message_ids` to `move_email`, `manage_trash`, `save_email_attachment`.
5. Add `timeout` to: `get_email_by_id`, `get_email_thread`, `save_email_attachment`, `get_mailbox_unread_counts`.

**Exit criteria:** No `every message of` without `whose` or `items 1 thru N` in grep audit; script-shape tests for thread + compose lookup.

---

### Phase 3: MCP quality uplift (2–3 days)

> **Skills:** **`mcp-builder`** (+ `reference/mcp_best_practices.md`, `python_mcp_server.md`), `testing-python` · **Sub-agents:** **`explore`** (annotation matrix), `generalPurpose` (MCP review), **`plugin-validator`** if manifest descriptions change

**Goal:** Align with mcp-builder best practices for agent usability.

1. Add FastMCP annotations to all 27 tools:
   - `readOnlyHint: true` for list/get/search/analytics getters
   - `destructiveHint: true` for trash, move (non-dry-run), status updates, sends
   - `idempotentHint` where applicable
2. Standardize error prefix to `Error:` everywhere.
3. Normalize JSON return types — tools with `output_format="json"` return dict/list, not JSON strings (fixes wrapper inconsistency).
4. Normalize `list_inbox_emails` JSON shape (always return `{emails, errors}`).
5. Migrate compose osascript bypasses through `run_applescript()` with configurable timeout.
6. Add integration test: `main(["--read-only"])` → send tools absent from registry.

**Exit criteria:** All tools annotated; JSON output consistent for wrapper consumers; read-only registry test passes.

---

### Phase 4: Hygiene & dedup (1–2 days)

> **Skills:** `CLAUDE.md`, `reviewing-code`, `plugin-structure` · **Sub-agents:** parent agent (small diffs), **`plugin-architect`** (keywords/dxt_version), **`plugin-validator`** (blocking), **`shell`** (mcpb rebuild)

**Goal:** Conservative cleanup from 3.1.5 audit + todo.md.

1. Move `SENSITIVE_DIRS` to `core.py`; consolidate `_split_addresses`, CC/BCC builder in compose.py
2. Replace `except: pass` swallows with `errors[]` lists
3. Align fastmcp pin: `>=3.1.0,<4` in requirements.txt and pyproject.toml
4. `start_mcp.sh`: verify `import fastmcp` after venv creation
5. Refresh `build-mcpb.sh` embedded README; bump mcpb `dxt_version` if validated
6. Add `keywords` + `category` to plugin.json

---

### Phase 5: Skills & marketplace polish (ongoing)

> **Skills:** **`plugin-dev:skill-development`**, `CLAUDE.md` § Skill authoring, template `email-management/SKILL.md`, `mcp-builder` (registry) · **Sub-agents:** **`plugin-architect`**, **`skill-reviewer`** (blocking per skill), **`plugin-validator`** (blocking), `explore` (SQLite feasibility, readonly)

**Goal:** Expand agent workflows and improve discoverability.

1. Remove or deprecate legacy `commands/email-management.md`.
2. Author sibling skills (email-drafting, inbox-triage, email-attachments) — each passes skill-reviewer.
3. Consider dedicated `plugin/.mcp.json` for MCP config separation.
4. Submit to MCP registry when ready (`server.json` already configured).
5. Hybrid SQLite read-path prototype (deferred unless Apple Events remain too slow after Phase A).

---

## Action Plan (Original — superseded by revised plan above)

<details>
<summary>Original phase numbering kept for reference</summary>

### Phase 0: Immediate sync fix (1–2 hours) — **Do before any release**

**Goal:** Make all manifests honest and pass plugin-validator.

1. Add `get_email_by_id` entry to `apple-mail-mcpb/manifest.json` `tools[]` with description matching tool docstring.
2. Update tool count strings from 26 → **27** in:
   - `.claude-plugin/marketplace.json` (plugins[0].description)
   - `apple-mail-mcpb/manifest.json` (description)
   - `CLAUDE.md` (tool count claim + per-module counts)
   - `README.md` (architecture tree comment)
   - `plugin/apple_mail_mcp/__init__.py` (import comments: inbox 6, search 3, manage 6)
3. Fix `SKILL.md` line 51: `confirm_empty=True`.
4. Run `plugin-dev:plugin-validator` — treat failures as blocking.
5. Rebuild mcpb bundle and spot-check tool list.

**Exit criteria:** grep confirms 27 `@mcp.tool`; mcpb `tools[]` length = 27; all descriptions say 27; validator passes.

---

### Phase 1: CI & validation guardrails (half day)

**Goal:** Prevent manifest drift from recurring.

1. Create `tools/validate_manifests.sh`:
   - Assert version equality across 5 release files
   - Assert `@mcp.tool` count matches mcpb `tools[]` length
   - Assert every registered tool name appears in mcpb array
   - Assert plugin.json description count matches
2. Add `.github/workflows/ci.yml`:
   - `pytest tests/ -q` on push/PR
   - Run `validate_manifests.sh`
   - Matrix: macOS (required — platform-specific code, but tests mock subprocess)
3. Optional: pre-commit hook wrapping validate script.

**Exit criteria:** CI green on main; intentional tool add without manifest update fails CI.

---

### Phase 2: Performance hotfixes (2–3 days) — **Target: 3.1.6**

**Goal:** Eliminate unbounded mailbox scans on large Exchange inboxes.

1. **`get_email_thread`:** Add `whose subject contains` + date window + `items 1 thru max_messages`; expose `timeout` and `recent_days` params. Add script-shape unit test.
2. **Compose reply/forward lookup:** Replace `every message of inboxMailbox` with capped `whose` clause or require `message_id` from prior search result.
3. **Smart inbox fallbacks:** Fail fast with structured error instead of unfiltered `every message of` on `whose` failure.
4. **`manage_drafts` list:** Cap at `items 1 thru 100`.
5. ~~Profile `move_email` dry-run no-hit path~~ — resolved on current branch.
6. Add `timeout` to: `get_email_by_id`, `get_email_thread`, `save_email_attachment`, `get_mailbox_unread_counts`.

**Exit criteria:** No `every message of` without `whose` or `items 1 thru N` in grep audit; script-shape tests for thread + compose lookup; live perf on 24K inbox shows thread/search under budget.

---

### Phase 3: MCP quality uplift (2–3 days)

**Goal:** Align with mcp-builder best practices for agent usability.

1. Add FastMCP annotations to all 27 tools
2. Standardize error prefix to `Error:` everywhere.
3. Normalize `list_inbox_emails` JSON shape
4. Migrate compose osascript bypasses through `run_applescript()`
5. Add integration test: `main(["--read-only"])` → send tools absent from registry.

---

### Phase 4: Agent tooling & live testing (3–5 days)

**Goal:** Make the plugin testable by coding agents against real Mail.app safely.

1. Complete portable `apple-mail` CLI wrappers
2. Implement `apple-mail perf-test`
3. Document agent live-testing setup
4. Add optional `include_timing` telemetry
5. Optimize live perf targets

---

### Phase 5: Skills & marketplace polish (ongoing)

Same as revised Phase 5.

</details>

---

## Verification Checklist (Pre-Release)

Use this before declaring any release ready:

- [ ] `rg '^@mcp\.tool' plugin/apple_mail_mcp/tools/*.py | wc -l` → 27
- [ ] `apple-mail-mcpb/manifest.json` `tools[]` length = 27, names match Python functions
- [ ] All 5 version files at same semver
- [ ] `.venv/bin/pytest tests/ -q` → all pass (currently 113)
- [ ] `tools/validate_manifests.sh` → exit 0
- [ ] `plugin-dev:plugin-validator` → pass
- [ ] `plugin-dev:skill-reviewer` on email-management (if skill touched)
- [ ] Live smoke-test: `.venv/bin/apple-mail smoke-test --account <name> --json`
- [ ] Live perf-test (after Phase B): `.venv/bin/apple-mail perf-test --account <name> --json`
- [ ] Invalid account returns `account_not_found` in <2s (after Phase A)
- [ ] `inbox-dashboard` completes under 10s with default params (after Phase A)
- [ ] `/mcp` in Claude Code shows apple-mail server with 27 tools
- [ ] No unbounded `every message of` in tools/*.py (grep audit)

---

## Subagent Reports Summary

Four parallel reviews were conducted:

| Agent | Focus | Key finding |
|-------|-------|-------------|
| **plugin-architect** | Directory layout, conventions, portable paths | Structure PASS; tool count drift FAIL |
| **plugin-validator** | Marketplace readiness, manifest cross-ref | Overall FAIL — mcpb missing `get_email_by_id` |
| **explore (MCP deep-dive)** | Server implementation, best practices | 27 tools strong core; no annotations; 4 legacy scan paths |
| **generalPurpose (perf/tests)** | Anti-patterns, coverage map | 113 tests pass; 10 tools untested; 4 critical scan hotspots |

---

## Recommended Sequencing (Revised)

```
Phase 0 (manifest sync, ~2h)
    → Phase A (live fixes: dashboard, account validation, overview, analysis)
    → Phase 1 (CI)
    → Phase B (perf-test CLI + agent docs)
    → Phase 2 (thread/compose scan paths + ID-first)
    → Phase 3 (MCP annotations + JSON normalization)
    → Phase 4 (hygiene dedup)
    → Phase 5 (skills — paused until above complete)
```

| Release target | Phases required |
|----------------|-----------------|
| **Marketplace honest** | Phase 0 + Phase 1 |
| **Agent-ready on real Mail** | Phase 0 + A + B + Phase 1 |
| **Large-mailbox safe** | Above + Phase 2 |
| **Full 3.1.6** | Above + Phase 3 + Phase 4 |

**Best single next PR:** Phase 0 + Phase A items 1–2 (manifest sync + `inbox_dashboard` fix + account validation). These are independent, high-confidence, and directly validated by live testing.

---

## Subagent Reports Summary

Four parallel reviews were conducted, then validated against live CLI testing:

| Agent | Focus | Key finding | Live validation |
|-------|-------|-------------|-----------------|
| **plugin-architect** | Directory layout, conventions | Structure PASS; tool count drift FAIL | Unchanged |
| **plugin-validator** | Marketplace readiness | mcpb missing `get_email_by_id` | Unchanged — still blocking |
| **explore (MCP deep-dive)** | Server implementation | 27 tools; no annotations; legacy scans | Core paths fast live; legacy scans not exercised in CLI sweep |
| **generalPurpose (perf/tests)** | Anti-patterns, coverage | 113 tests; 10 tools untested | `move_email` dry-run regression **does not reproduce** on branch |
| **Live CLI sweep** | Real Mail.app on `ai.openclaw` | Dashboard timeout, bad account UX, analysis slowness | Confirmed with code root-cause analysis |

---

## Appendix: Current Test Command Reference

```bash
# Dev setup
python3 -m venv .venv
.venv/bin/pip install -e . pytest

# Run all tests
.venv/bin/pytest tests/ -q

# Run MCP server locally
.venv/bin/python plugin/apple_mail_mcp.py
.venv/bin/python plugin/apple_mail_mcp.py --read-only
.venv/bin/python plugin/apple_mail_mcp.py --draft-safe

# Install plugin locally
claude plugin marketplace add .
claude plugin install apple-mail@apple-mail-mcp

# Tool count verification
rg '^@mcp\.tool' plugin/apple_mail_mcp/tools/*.py | wc -l   # expect 27
```

---

*Report generated from coordinated multi-agent audit, validated against `CLI_TESTING_REPORT_2026-05-21.md` and `tasks/todo.md` on branch `improve-speed-and-tools`. Next update recommended after Phase 0 + Phase A.*

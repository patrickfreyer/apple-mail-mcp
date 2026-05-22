# Phase Plan — 3.1.7

**Branch:** `improve-speed-and-tools` · **Tests:** 249 *(baseline doc: 206)* · **Version:** 3.1.7
**Baseline:** [`live-test-baseline-2026-05-21.md`](live-test-baseline-2026-05-21.md) · root [`LIVE_MCP_CLI_TESTING_REPORT_2026-05-21.md`](../LIVE_MCP_CLI_TESTING_REPORT_2026-05-21.md)  
**Backlog:** [`todo.md`](todo.md) · **Archive:** [`archive/2026-05-21/`](archive/2026-05-21/)

## Situation

3.1.6 hardening **fixed the agent-critical path**: search, inbox, dashboard metadata, invalid-account errors, scan caps, CLI batteries, annotations. Core `perf-test` passes on light accounts.

**Remaining pain is concentrated in three places:**

1. **Generated wrapper parity** — the Python registry and MCPB manifest include `get_email_by_id`, but the generated `apple-mail` wrapper does not expose `get-email-by-id`. Agents using the wrapper cannot perform exact-id reads even though the server can.
2. **Production-scale accounts** (`cayman@agenticassets.ai`, 194 mailboxes) — metadata and overview breach thresholds; functional behavior is correct.
3. **Analysis / triage tools** — `needs-response`, `awaiting-reply`, `top-senders`, `get_statistics account_overview` are 6–24s and **not covered by `perf-test`**, so regressions slip through.

Do **not** start hybrid SQLite or id-first destructive refactors until analysis perf is benchmarked and gated. **Plugin workflow skills** (nine under `plugin/skills/`) shipped — see [`plugin/skills/CLAUDE.md`](../plugin/skills/CLAUDE.md).

## Sequence

```
1 (wrapper parity + perf gates) → 2 (analysis speed) → 3 (JSON/schema finish) → 4 (ship hygiene)
```

| Ship target | Phases |
|-------------|--------|
| Wrapper-safe agent testing | 1 |
| Production account green | 1 + 2 |
| Agent-ready JSON | 1 + 2 + 3 |
| Marketplace 3.1.6 release | all + version bump |

### Dependency gates

| Gate | Before |
|------|--------|
| Phase 1 wrapper command-surface check + `--include-analysis` scaffold | Phase 2 tool edits (need measurement and exact-id parity) |
| Phase 2 analysis tools &lt; targets on `cayman@agenticassets.ai` | Phase 3 JSON shape changes in smart_inbox/analytics |
| Phase 3 JSON stable | Version bump + mcpb rebuild |

Parallel OK within a phase for **different modules** (e.g. `list_mailboxes` vs `get_top_senders`). Do not parallelize two edits to the same AppleScript builder.

---

## Phase 1 — Wrapper parity + honest perf gates (~1–2 days)

**Goal:** generated wrapper exposes the same critical read tools as the Python server, and `perf-test` fails when production/analysis paths regress.

**Skills:** `mcp-builder` · `mcp-integration` · `plugin-structure` · `create-cli` · `python-performance-optimization` · `docs/AGENT_LIVE_TESTING.md`  
**Sub-agents:** `explore` (wrapper generation path) · `generalPurpose` (cli.py / wrapper checks) · `shell` (live runs on cayman account + wrapper help)  
**Verify:** repo CLI + generated wrapper command-surface checks both pass

- [x] **Regenerate or repair generated `apple-mail` wrapper** — mcporter bundle regenerated from live server; 27 commands including `get-email-by-id`.
- [x] **Wrapper command-surface smoke check** — `tools/check_wrapper_surface.py`.
- [x] **Document repo CLI vs wrapper flags** — profiles, regen steps, naming table in `AGENT_LIVE_TESTING.md`.
- [x] **Scale metadata threshold** — formula in `cli.py`; production cayman metadata ~5.8s passes 8090ms gate.
- [x] **Overview threshold** — `--profile production` (15s); cayman overview ~9.5s passes.
- [x] **`perf-test --include-analysis --allow-heavy-mail-scan`** — 4 analysis cases behind explicit heavy-scan opt-in; honest fail on `top_senders` (~15.6s) until Phase 2.
- [x] **Document two profiles** in `AGENT_LIVE_TESTING.md`.
- [ ] **Push `.github/workflows/ci.yml`** from developer terminal (OAuth `workflow` scope).

**Done when:** `apple-mail --help` includes `get-email-by-id`; repo `perf-test --include-analysis --allow-heavy-mail-scan` reports analysis cases with clear pass/fail; docs show both repo CLI and wrapper examples.

---

## Phase 2 — Analysis & metadata speed (~3–5 days)

**Goal:** Triage tools usable in agent loops (&lt;8s worst case on production account, &lt;5s target on light account).

**Skills:** `CLAUDE.md` conventions · `python-performance-optimization` · `testing-python`  
**Sub-agents:** `explore` (script shape audit) · parent/`generalPurpose` per tool · `shell` (live before/after)

### 2a — `list_mailboxes` (unblocks metadata gate)

- [x] **`include_counts=False` default for perf metadata probe** — counts are the expensive part (per-mailbox `count of messages`).
- [ ] **Cap or paginate** — `max_mailboxes` param (default 50 for JSON list mode); return `{mailboxes, truncated, total_count}` when capped.
- [ ] **Optional async fan-out** — only if single-script cap insufficient; prefer one script with counts disabled first.

### 2b — `get_statistics` / `account_overview`

- [ ] **Reduce work** — lower defaults: `max_mailboxes=10`, `max_messages_per_mailbox=100` for `days_back <= 7`; expose overrides.
- [ ] **Use mailbox count APIs where possible** — `unread count of aMailbox` instead of scanning messages for unread totals on overview scope.
- [ ] **Split scopes** — lightweight `mailbox_breakdown` for counts-only; heavy sender/attachment stats opt-in via `scope=sender_stats`.
- [ ] **Collect `on error` into `errors[]`** — replace silent skips in analytics loop (~line 504).

### 2c — `get_needs_response` (highest priority — 14.5s)

- [x] **Drop `content of aMessage` by default** — subject-only `?` detection; add `scan_body: bool = False`. This is the hottest confirmed line in `get_needs_response`.
- [x] **Tighten caps** — `inbox_cap = min(max_results * 5, 100)`; `sent_cap = 100`.
- [ ] **Index sent subjects in Python** — return raw pairs from AppleScript; match in Python (faster than nested AppleScript loops).

### 2d — `get_awaiting_reply` + `get_top_senders`

- [ ] **Awaiting reply** — parallel inbox/sent scripts via `asyncio.to_thread` (pattern from `inbox_dashboard`).
- [x] **Top senders** — move aggregation fully to Python (`Counter`); reduce `scan_cap` when `days_back` small.

**Done when:** `perf-test --include-analysis --allow-heavy-mail-scan --account cayman@agenticassets.ai` all green.

---

## Phase 3 — JSON/schema consistency (~2 days)

**Goal:** MCP + repo CLI emit predictable structured JSON for automation, and generated-wrapper behavior is documented or tested when it necessarily differs.

**Skills:** `mcp-builder` · `testing-python`  
**Sub-agents:** `generalPurpose` · `plugin-validator` after manifest description changes

- [ ] **`inbox_dashboard`** — `output_format='json'` returns dict (not JSON string).
- [ ] **Smart inbox four** — `get_needs_response`, `get_awaiting_reply`, `get_top_senders`, `get_actionable_emails` JSON modes return dicts with stable keys + `errors[]`.
- [ ] **`list_inbox_emails` JSON** — always `{emails, errors}` *(breaking — document in CHANGELOG)*.
- [ ] **Wrapper examples** — add copy-paste `--raw` examples for tools whose generated help exposes only raw JSON, especially `get-inbox-overview`.
- [ ] **Wrapper parity tests/docs** — note that manifest validation can pass while a stale generated wrapper is missing a command; keep wrapper command-surface smoke separate from manifest validation.

**Done when:** spot-check wrapper `--raw` and repo `--json` produce same key shapes for overview + statistics + needs-response.

---

## Phase 4 — Ship hygiene (~1 day)

**Goal:** Clean 3.1.6/3.1.7 release.

- [ ] Version bump (five files) + mcpb rebuild; `dxt_version` → 0.2 if mcpb CLI validates.
- [ ] Marketplace `metadata.version` documented or removed.
- [ ] **`id-first-refactor-spec.md`** — schedule as 3.1.8 (not blocking release).
- [x] **`inbox-triage` skill** — shipped (`plugin/skills/inbox-triage/`).
- [x] **Plugin `--draft-safe` default** — `plugin.json` `mcpServers` args include `--draft-safe`.
- [x] **Plugin workflow skill suite** — nine skills under `plugin/skills/` (operator, triage, management, taxonomy, archive, rules advisor, drafting, style profile, attachments).

**Done when:** `plugin-validator` green · live production perf-test green · CI green.

---

## Orchestrator checklist

1. Live baseline before/after: `tasks/live-test-baseline-2026-05-21.md`
2. `pytest tests/ -q` after every tool change
3. `apple-mail --help` command-surface check before closing Phase 1
4. `perf-test --include-analysis --allow-heavy-mail-scan --account cayman@agenticassets.ai --json` before closing Phase 2
5. `plugin-dev:plugin-validator` after manifest/skill marketing copy changes; `plugin-dev:skill-reviewer` after skill body/frontmatter edits

## Quick commands

```bash
export DEFAULT_MAIL_ACCOUNT="cayman@agenticassets.ai"

.venv/bin/pytest tests/ -q
.venv/bin/apple-mail quick-check --json
.venv/bin/apple-mail perf-test --json                              # core battery
.venv/bin/apple-mail perf-test --include-analysis --allow-heavy-mail-scan --json  # heavy opt-in
apple-mail --help                                                  # wrapper command-surface check
.venv/bin/apple-mail needs-response --days 2
.venv/bin/apple-mail statistics --scope account_overview --days 2 --json
tools/validate_manifests.sh
```

# Rolling backlog — apple-mail-mcp

Cross-session source of truth. In-conversation tasks are ephemeral; **this file survives**.

**Phase plan:** [`phase-plan-3.1.7.md`](phase-plan-3.1.7.md) · **Live baseline:** [`live-test-baseline-2026-05-21.md`](live-test-baseline-2026-05-21.md) · **Latest wrapper report:** [`../LIVE_MCP_CLI_TESTING_REPORT_2026-05-21.md`](../LIVE_MCP_CLI_TESTING_REPORT_2026-05-21.md) · **Archive:** [`archive/2026-05-21/`](archive/2026-05-21/)

**Production test account:** `cayman@agenticassets.ai` (194 mailboxes). Light regression: `ai.openclaw`.

---

## Now — Phase 1: wrapper parity + honest perf gates

- [x] **Regenerate or repair generated MCP wrapper** — regenerated mcporter bundle; `get-email-by-id` now on `apple-mail --help`.
- [x] **Add wrapper command-surface smoke check** — `tools/check_wrapper_surface.py` + `tests/test_wrapper_surface.py`.
- [x] **Document repo CLI vs wrapper flags** — `docs/AGENT_LIVE_TESTING.md` (profiles, regen, naming table).
- [x] **Scale `perf-test` metadata threshold** — `2000 + max(0, mailbox_count - 20) × 35` ms in `cli.py`.
- [x] **Add `perf-test --include-analysis --allow-heavy-mail-scan`** — needs-response, awaiting-reply, top-senders, statistics cases behind explicit heavy-scan opt-in.
- [x] **Overview threshold** — `--profile light` (10s) vs `production` (15s).
- [x] **Update `docs/AGENT_LIVE_TESTING.md`** — light vs production profiles; heavy analysis opt-in.
- [ ] **Push `.github/workflows/ci.yml`** — blocked on GitHub OAuth `workflow` scope from Cursor; push from local terminal.

---

## Next — Phase 2: analysis & metadata speed

### `list_mailboxes` (fixes metadata probe)

- [x] Default **`include_counts=False`** for perf metadata case; counts dominate on 194-mailbox accounts.
- [x] Add **`max_mailboxes`** cap + `{truncated, total}` in JSON mode.

### `get_statistics` / `account_overview` (~24s → target &lt;12s)

- [x] Lower scan defaults for short `days_back` (10 mailboxes × 100 messages when `days_back <= 7`; else 20 × 500).
- [ ] Prefer **`unread count of aMailbox`** over per-message unread scan where scope allows. (`mailbox_breakdown` already uses Mail count APIs.)
- [ ] Replace silent `on error` skips with **`errors[]`** in response.

### `get_needs_response` (~14.5s → target &lt;8s) — highest priority

- [x] Remove default **`content of aMessage`** fetch; `scan_body: bool = False`.
- [x] Tighter inbox/sent caps (`inbox_cap` ≤100, `sent_cap` 100).
- [ ] **Reply matching in Python** not nested AppleScript.

### `get_awaiting_reply` / `get_top_senders`

- [x] Async dual-script pattern for awaiting-reply.
- [x] Finish Python-side aggregation for top-senders (`Counter` + lower `scan_cap`).

**Verify:** `.venv/bin/apple-mail perf-test --include-analysis --allow-heavy-mail-scan --account cayman@agenticassets.ai --json` all green.

**Also done (Phase 2 partial / ship prep):**

- [x] **`inbox-triage` skill** — `plugin/skills/inbox-triage/`.
- [x] **Plugin `--draft-safe` default** — `plugin.json` `mcpServers` args.

---

## Then — Phase 3: JSON finish

- [ ] `inbox_dashboard` → dict JSON (not string).
- [ ] Smart inbox tools → structured JSON + `errors[]`.
- [ ] `list_inbox_emails` JSON → `{emails, errors}` *(breaking — changelog)*.
- [ ] Add generated-wrapper `--raw` examples for `get-inbox-overview` and any other wrapper command with poor flag discovery.

---

## Ship — Phase 4

- [ ] Version bump (five files) → 3.1.6 or 3.1.7.
- [ ] mcpb rebuild; **`dxt_version` 0.2** if validator accepts.
- [ ] Marketplace **`metadata.version`** — document or remove.
- [ ] **`plugin-dev:plugin-validator`** before merge.

---

## Deferred (do not start until Phase 2 green)

- [ ] **Hybrid SQLite read-path** — Envelope Index spike; feature-flagged.
- [ ] **Id-first destructive actions** — [`id-first-refactor-spec.md`](id-first-refactor-spec.md).
- [x] **Plugin workflow skill suite** — shipped `apple-mail-operator`, `inbox-triage`, `email-management`, `mailbox-taxonomy`, `email-archive-cleanup`, `mail-rules-advisor`, `email-drafting`, `email-style-profile`, `email-attachments`; plugin MCP defaults to `--draft-safe`.
- [ ] **`include_timing` telemetry** on tool responses.
- [ ] **Normalize generated wrapper JSON** — mcporter `content` wrapping vs direct dict.
- [ ] **MCP registry submit** (`server.json`).

---

## Maintenance

- After `tools/*.py`: `.venv/bin/pytest tests/ -q` (221 tests).
- After manifests/skills: `bash tools/validate_manifests.sh` + `plugin-dev:plugin-validator` (+ `plugin-dev:skill-reviewer` for skill body/frontmatter).
- Routine live gate: `export DEFAULT_MAIL_ACCOUNT="cayman@agenticassets.ai"` then `quick-check --json` or `perf-test --json`.
- Heavy analysis gate requires explicit opt-in: `perf-test --include-analysis --allow-heavy-mail-scan --json`. Do not run this during routine agent testing because it can make Mail.app fetch remote message state on large accounts.

---

## Done (3.1.6 — archived)

See [`archive/2026-05-21/README.md`](archive/2026-05-21/README.md). Highlights:

- [x] 27 tools, 206 tests at 3.1.6 archive *(221 tests now)*, manifest CI guards, ToolAnnotations on all tools.
- [x] `quick-check` / `perf-test` / `smoke-test` CLI + `docs/AGENT_LIVE_TESTING.md`.
- [x] `inbox_dashboard` async fix, account validation, scan caps (Phase 2).
- [x] Compose → `run_applescript()`, address dedup, `SENSITIVE_DIRS` in core.
- [x] JSON dict returns for `get_statistics`, `get_inbox_overview`.
- [x] Folder-level `CLAUDE.md` docs + root navigation hub.

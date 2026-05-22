# Plan Review Status — 2026-05-21

**Source:** [`PLAN_REVIEW_COMMENTS_2026-05-21.md`](../PLAN_REVIEW_COMMENTS_2026-05-21.md) (Forge)  
**Baseline at review:** 113 tests · commit `e4a7670`  
**Current baseline (post Phase 0+A+1):** **146 tests passing** · manifest CI guardrails · account validation wired across tools · `perf-test`/`quick-check` on branch

Legend: ✅ addressed · 🟡 partial · ⬜ open · 📋 process (apply going forward)

---

## Main recommendations

| # | Item | Status | Notes |
|---|------|--------|-------|
| 1 | Split Phase 0 and Phase A into separate PRs | 📋 | Shipped together in one branch; **apply split to remaining work** (Phase 1 guardrails vs Phase B CLI vs Phase 2 scans). |
| 2 | Fix tool-count verification command (`rg … \| wc -l`) | ✅ | `phase-plan-3.1.6.md` Quick commands + audit appendix use `rg '^@mcp\.tool' … \| wc -l`. |
| 3 | Remove stale `move_email --dry-run` ~61s hotspot | ✅ | Removed from audit critical hotspot table; issue register already marked resolved. |
| 4 | Update stale Python 3.7 text (`CLAUDE.md`, `build-mcpb.sh` README) | ✅ | `CLAUDE.md` L142 and `build-mcpb.sh` embedded README now say 3.10+. |
| 5 | Account validation — validate explicit `account` only; short timeout; avoid fan-out overhead; optional cache | ✅ | Wired across manage, analytics, smart_inbox, compose, search, inbox; no TTL cache (optional future). |
| 6 | CI strictly non-live (mocked pytest, manifest drift; no live smoke/perf) | ✅ | `.github/workflows/ci.yml` + `tools/validate_manifests.py`; no live Mail in CI. |
| 7 | Verify installed FastMCP supports annotation API before Phase 3 | ⬜ | `fastmcp>=3.1.0` / `==3.1.0`; confirm API before editing 27 tools. |
| 8 | Normalize JSON in stages (worst tools first; preserve text mode) | 🟡 | Overview compact/JSON modes ✅; staged rollout + `output_format` rule not yet formalized in Phase 3. |
| 9 | Tighten `inbox_dashboard` targets (metadata `<3s` preferred, `<5s` acceptable) | 🟡 | Async + `include_preview=False` default ✅; plan still says `<10s`; live gate not re-benchmarked to 3–5s. |
| 10 | “Do not do yet” note for hybrid SQLite path | 🟡 | Deferred in `todo.md` § Future architecture; Phase 5 gate exists; strengthen “after A/B/2 benchmarked” wording. |

---

## Smaller corrections

| Item | Status | Notes |
|------|--------|-------|
| P1/P2 issue register duplicated `#11` | ⬜ | Audit register: P1 #11 skill typo vs P2 #11 compose bypass — renumber P2. |
| `plugin-validator` / `skill-reviewer` fallback wording | ⬜ | Add “if unavailable, run local manifest checks and document gap” to phase orchestrator + `todo.md` maintenance. |
| “Repo CLI + smoke-test” → “foundation + smoke-test” | ⬜ | Phase plan “Already done” wording still implies full CLI coverage. |
| `get_mailbox_unread_counts` timeout / tree cap | ⬜ | Still Phase 2; relevant if overview/dashboard call it. |
| Specific `inbox_dashboard` test target | ✅ | `tests/test_phase_a_fixes.py` — preview skip/include script-shape tests. |

---

## Additions from review (not yet in plan)

| Item | Status | Target phase |
|------|--------|--------------|
| Explicit live performance gates (accounts `<1s`, dashboard metadata `<5s`, etc.) | 🟡 | **`perf-test` / `quick-check` thresholds in cli.py**; dashboard not in quick battery yet |
| `perf-test` privacy/redaction (no raw subjects/senders unless `--verbose-sensitive`) | 🟡 | Counts/lengths redacted; metadata sample still includes account/mailbox names |
| Backward compatibility rule: preserve `output_format="text"` when adding JSON | ⬜ | Phase 3 |
| Phase 0B: `tools/validate_manifests.sh` before CI | ✅ | Phase 1 |

---

## Suggested execution order vs current state

| Step | Review label | Status |
|------|--------------|--------|
| 0A Manifest and doc sync | Phase 0 | ✅ Done (27 tools, mcpb `get_email_by_id`, SKILL typo, todo cleanup) |
| 0B Guardrail script | Phase 1 prep | ✅ `validate_manifests.py` + CI workflow |
| A1 Unknown account validation | Phase A | ✅ Wired across account-scoped tools |
| A2 Dashboard default performance | Phase A | 🟡 Landed; re-benchmark vs `<5s` target |
| B Repo CLI + perf-test | Phase B | 🟡 **`perf-test` + `quick-check` + `docs/AGENT_LIVE_TESTING.md` landed**; expand CLI wrappers (overview, needs-response, etc.) still open |
| 2 Legacy scan hardening | Phase 2 | ⬜ |
| 3–5 Annotations, JSON, hygiene, skills | Phases 3–5 | ⬜ |

---

## Deferred explicitly (do not start in 3.1.6 unless benchmarks fail)

- **`include_timing` telemetry** — listed as done in an early Phase A draft; **not implemented**. Defer to Phase B alongside `perf-test` (review did not require it for A closure).
- **Hybrid SQLite read path** — spike only after Phase A/B/2 fixes benchmarked; feature-flagged.

---

## Next PR guidance (post Phase 0+A+1)

1. **PR: Phase B** — `perf-test` dashboard/bad-account cases, CLI wrappers, smoke-test extensions.
2. **PR: Doc hygiene** — stale Python 3.7 refs, audit hotspot table, grep command in phase plan. ✅ Addressed 2026-05-21.
3. **PR: Phase 2** — scan-path hardening (`get_email_thread`, compose lookup caps, etc.).

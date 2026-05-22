# Archive — 2026-05-21

Superseded by [`../../phase-plan-3.1.7.md`](../../phase-plan-3.1.7.md) after
safe live testing on the generated wrapper and production account
`cayman@agenticassets.ai`.

## Contents

| File | Role |
|------|------|
| `phase-plan-3.1.6.md` | Original release sequencing |
| `plugin-audit-and-action-plan-2026-05-21.md` | Full multi-agent audit |
| `plan-review-status-2026-05-21.md` | Review comment tracking |
| `PLAN_REVIEW_COMMENTS_2026-05-21.md` | External review input |
| `CLI_TESTING_REPORT_2026-05-21.md` | Earlier live CLI sweep |
| `phase-3-annotation-matrix.md` | Annotation workstream detail |

## Current Replacement

Use [`../../live-test-baseline-2026-05-21.md`](../../live-test-baseline-2026-05-21.md)
and [`../../phase-plan-3.1.7.md`](../../phase-plan-3.1.7.md) for active work.
# Archive — 2026-05-21 (3.1.6 hardening sprint)

Superseded by [`../../phase-plan-3.1.7.md`](../../phase-plan-3.1.7.md) after live retest on production account `cayman@agenticassets.ai`.

## What shipped (branch `improve-speed-and-tools`, commit `f0ca077`)

- 27 tools, 206 tests, manifest CI guards (`tools/validate_manifests.py`)
- Live CLI: `quick-check`, `perf-test`, `smoke-test` + safe probe wrappers
- Phase 0–2 complete: manifest sync, dashboard/overview fixes, scan caps, account validation
- Phase 3 partial: ToolAnnotations on all tools, `Error:` prefix, compose → `run_applescript()`, JSON for `get_statistics` + `get_inbox_overview`
- Phase 4 partial: `SENSITIVE_DIRS` in core, compose dedup, fastmcp pin, plugin keywords
- Folder-level `CLAUDE.md` navigation + `docs/CLAUDE-conventions.md`

## Files in this folder

| File | Role |
|------|------|
| `phase-plan-3.1.6.md` | Original release sequencing (phases 0–5) |
| `plugin-audit-and-action-plan-2026-05-21.md` | Full multi-agent audit |
| `plan-review-status-2026-05-21.md` | Review comment tracking |
| `PLAN_REVIEW_COMMENTS_2026-05-21.md` | External review input |
| `CLI_TESTING_REPORT_2026-05-21.md` | First live CLI sweep (`ai.openclaw`) |
| `phase-3-annotation-matrix.md` | Annotation workstream detail |

## Live baseline at archive time

See [`../../live-test-baseline-2026-05-21.md`](../../live-test-baseline-2026-05-21.md).

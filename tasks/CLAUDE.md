# tasks/ — planning and backlog

Cross-session planning artifacts. In-conversation work uses ephemeral task lists; **this folder survives between sessions**.

## todo.md vs phase-plan

| File | Role |
|------|------|
| [`todo.md`](todo.md) | **Rolling backlog** — checkboxes, file paths, "what's next". Prune done items; add ideas as they surface. Source of truth between sessions. |
| [`phase-plan-3.1.6.md`](phase-plan-3.1.6.md) | **Release sequencing** — phase gates (0→A→1→B→2→3→4→5), dependency rules, ship targets. Links to audit/review docs. |

**Convention:** when an item in `todo.md` grows into a workstream, link a dated folder under `tasks/<workstream>/`. Phase plan marks what's done; mirror completions in `todo.md` ("Already done" section).

Current branch context (3.1.6): **206 tests**. Phases 0–2 and most of 4 done; Phase 3 in flight (JSON normalization for remaining tools). See phase plan § Orchestration rule — don't start phase N+1 until exit criteria met.

## Other task files

- `plugin-audit-and-action-plan-2026-05-21.md` — full audit
- `plan-review-status-2026-05-21.md` — review tracking
- `phase-3-annotation-matrix.md` — annotation workstream detail

Root [`PLAN_REVIEW_COMMENTS_2026-05-21.md`](../PLAN_REVIEW_COMMENTS_2026-05-21.md) and [`CLI_TESTING_REPORT_2026-05-21.md`](../CLI_TESTING_REPORT_2026-05-21.md) live at repo root (referenced from phase plan).

## Maintenance reminders (from todo.md)

- After `tools/*.py` changes: `.venv/bin/pytest tests/ -q`
- After manifest/skill/layout changes: `plugin-dev:plugin-validator` (fallback: `tools/validate_manifests.sh`)
- After skill `description` edits: `plugin-dev:skill-reviewer`
- Version bump: grep all five version files (see [`docs/CLAUDE-conventions.md`](../docs/CLAUDE-conventions.md))

## Related

- Deep engineering rules: [`docs/CLAUDE-conventions.md`](../docs/CLAUDE-conventions.md)
- Live verification workflow: [`docs/AGENT_LIVE_TESTING.md`](../docs/AGENT_LIVE_TESTING.md)
- CI guardrails: [`tools/CLAUDE.md`](../tools/CLAUDE.md)
- Root overview: [`CLAUDE.md`](../CLAUDE.md)

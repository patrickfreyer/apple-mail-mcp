# tasks/ — planning and backlog

Cross-session planning artifacts. In-conversation work uses ephemeral task lists; **this folder survives between sessions**.

## Agent orchestration

When executing [`phase-plan-3.1.7.md`](phase-plan-3.1.7.md) or [`todo.md`](todo.md):

- **Subagents for research and implementation** — delegate coding, tests, docs, and live runs; parallelize independent modules, sequence dependent phases.
- **Plugin-dev experts always** — `plugin-dev:plugin-validator`, `plugin-dev:plugin-architect`, `plugin-dev:skill-reviewer`, plus `mcp-integration` / `plugin-structure` / `mcp-builder` skills per phase plan.

## Active files

| File | Role |
|------|------|
| [`todo.md`](todo.md) | **Rolling backlog** — checkboxes, paths, what's next. Prune done items. |
| [`phase-plan-3.1.7.md`](phase-plan-3.1.7.md) | **Current release sequencing** — phases 1→4 after 3.1.6 hardening. |
| [`live-test-baseline-2026-05-21.md`](live-test-baseline-2026-05-21.md) | **Live perf numbers** — production vs light account; root-cause notes. |
| [`id-first-refactor-spec.md`](id-first-refactor-spec.md) | Future spec (3.1.8+) — not in current phase plan. |

## Archive

Superseded plans live under [`archive/`](archive/). **Do not edit archived files for current work.**

- [`archive/2026-05-21/`](archive/2026-05-21/) — 3.1.6 audit, phase plan, CLI report, annotation matrix (shipped `f0ca077`).

## Production test account

Use **`cayman@agenticassets.ai`** for perf gates (194 mailboxes). **`ai.openclaw`** is light regression only.

```bash
export DEFAULT_MAIL_ACCOUNT="cayman@agenticassets.ai"
.venv/bin/apple-mail perf-test --json   # routine core battery
# Heavy analysis only with explicit opt-in:
.venv/bin/apple-mail perf-test --include-analysis --allow-heavy-mail-scan --json
```

## Maintenance

- After `tools/*.py`: `.venv/bin/pytest tests/ -q` (249 tests)
- After manifests: `bash tools/validate_manifests.sh` + `plugin-dev:plugin-validator`
- After skills: `plugin-dev:skill-reviewer` (+ manifest validator if marketing copy changed)
- Live workflow: [`docs/AGENT_LIVE_TESTING.md`](../docs/AGENT_LIVE_TESTING.md)
- Engineering rules: [`docs/CLAUDE-conventions.md`](../docs/CLAUDE-conventions.md)

## Related

- Root overview: [`CLAUDE.md`](../CLAUDE.md) → [`tasks/CLAUDE.md`](CLAUDE.md) link in table

# docs/ — documentation index

Human- and agent-facing docs that survive outside the codebase. Plugin skills and root `README.md` cover user install; this folder covers **agent workflows** and **deep engineering conventions**.

## Agent orchestration

- Use **subagents** for research **and** implementation (not research-only).
- Use **plugin-dev experts** (`plugin-dev:plugin-validator`, `plugin-dev:plugin-architect`) whenever docs or conventions touch manifests, skills, or MCP integration.

## Files

| Doc | Audience | Purpose |
|-----|----------|---------|
| [`AGENT_LIVE_TESTING.md`](AGENT_LIVE_TESTING.md) | Coding agents, maintainers | Live Mail verification via repo `.venv/bin/apple-mail` CLI |
| [`CLAUDE-conventions.md`](CLAUDE-conventions.md) | All agents editing Python/tools | Deep rules: perf, escaping, versioning, skills, plugin-dev agents |

## Who reads what

**Implementing or changing MCP tools** → start with root [`CLAUDE.md`](../CLAUDE.md) (architecture), then [`CLAUDE-conventions.md`](CLAUDE-conventions.md) (anti-patterns). Run mocked tests per [`tests/CLAUDE.md`](../tests/CLAUDE.md).

**Verifying against real Mail.app** → [`AGENT_LIVE_TESTING.md`](AGENT_LIVE_TESTING.md): setup, permissions, `quick-check` / `perf-test` batteries, safe probes, MCP env vars (`DEFAULT_MAIL_ACCOUNT`, `USER_EMAIL_PREFERENCES`).

**Plugin shell / manifests / skills** → [`plugin/CLAUDE.md`](../plugin/CLAUDE.md), [`.claude-plugin/CLAUDE.md`](../.claude-plugin/CLAUDE.md), [`apple-mail-mcpb/CLAUDE.md`](../apple-mail-mcpb/CLAUDE.md). Run `plugin-dev:plugin-validator` after manifest edits.

**Planning / backlog** → [`tasks/CLAUDE.md`](../tasks/CLAUDE.md) and [`tasks/todo.md`](../tasks/todo.md).

## AGENT_LIVE_TESTING.md structure

1. Setup (venv, `DEFAULT_MAIL_ACCOUNT`)
2. macOS permissions (Automation, Mail Data Access)
3. Safe commands — batteries (`quick-check`, `perf-test`, `smoke-test`) and individual probes
4. Post-edit workflow (fast loop → full perf gate + thresholds)
5. Unit tests vs live Mail (CI = mocked only)
6. MCP config for agents (`mcp-config --repo`, draft-safe)

## CI vs live

CI never touches Mail.app. Manifest validation + pytest only ([`tools/CLAUDE.md`](../tools/CLAUDE.md)). Live testing is manual on macOS after local changes.

## Related

- User-facing install: root [`README.md`](../README.md)
- Cross-session backlog: [`tasks/todo.md`](../tasks/todo.md)
- Phase sequencing: [`tasks/phase-plan-3.1.7.md`](../tasks/phase-plan-3.1.7.md) · live baseline: [`tasks/live-test-baseline-2026-05-21.md`](../tasks/live-test-baseline-2026-05-21.md)

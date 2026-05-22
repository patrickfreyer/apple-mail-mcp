# CLAUDE.md

Navigation hub for **apple-mail-mcp**: one Python MCP server (**27 tools**, **221 tests**, `fastmcp>=3.1.0,<4`) shipped as PyPI package (`mcp-apple-mail`), Claude Code plugin (`plugin/`), and Claude Desktop `.mcpb` (`apple-mail-mcpb/`). Marketplace entry: `.claude-plugin/marketplace.json`.

## Agent orchestration (required)

**Always use subagents** for both **research and implementation** — not just exploration. Delegate real fixes, tests, docs, and live verification to subagents; the lead agent orchestrates and reviews.

| When | Subagent |
|------|----------|
| Code changes, tests, docs | `generalPurpose` |
| Codebase search / file discovery | `explore` |
| pytest, live CLI, shell tasks | `shell` |
| Independent workstreams | Run subagents **in parallel** |
| Dependent steps (e.g. perf gates before tool edits) | Run subagents **sequentially** |

**Always use plugin-dev experts** for plugin, MCP, marketplace, and skill work — invoke before and after substantive changes:

| Expert | Use for |
|--------|---------|
| **`plugin-dev:plugin-validator`** | Manifest drift, tool counts, marketplace readiness |
| **`plugin-dev:plugin-architect`** | Plugin structure, MCP wiring, agent workflow gaps |
| Skills: **`mcp-integration`**, **`plugin-structure`**, **`mcp-builder`** | MCP server design, `.mcp.json` / `plugin.json`, tool quality |

Do not solo large plugin or perf workstreams without at least one plugin-dev expert pass.

## When working in…

| Area | Read |
|------|------|
| Plugin wrapper, `start_mcp.sh`, manifests | [`plugin/CLAUDE.md`](plugin/CLAUDE.md) |
| Package entry, `core.py`, `server.py`, CLI | [`plugin/apple_mail_mcp/CLAUDE.md`](plugin/apple_mail_mcp/CLAUDE.md) |
| Individual MCP tools | [`plugin/apple_mail_mcp/tools/CLAUDE.md`](plugin/apple_mail_mcp/tools/CLAUDE.md) |
| Skills (9 workflow skills) | [`plugin/skills/CLAUDE.md`](plugin/skills/CLAUDE.md) |
| Legacy slash commands | [`plugin/commands/CLAUDE.md`](plugin/commands/CLAUDE.md) |
| Tests & mocking AppleScript | [`tests/CLAUDE.md`](tests/CLAUDE.md) |
| Manifest validation, pre-commit | [`tools/CLAUDE.md`](tools/CLAUDE.md) |
| Live CLI testing, agent workflows | [`docs/CLAUDE.md`](docs/CLAUDE.md) |
| Deep tool/skill/plugin rules | [`docs/CLAUDE-conventions.md`](docs/CLAUDE-conventions.md) |
| Phase plans & backlog | [`tasks/CLAUDE.md`](tasks/CLAUDE.md) · [`tasks/todo.md`](tasks/todo.md) |
| MCPB bundle build | [`apple-mail-mcpb/CLAUDE.md`](apple-mail-mcpb/CLAUDE.md) |
| Marketplace manifest | [`.claude-plugin/CLAUDE.md`](.claude-plugin/CLAUDE.md) |

## Architecture (prose)

**Plugin wrapper** (`plugin/start_mcp.sh`, `plugin.json`) launches **Python package** (`plugin/apple_mail_mcp/`: `__main__` → import `tools/*` → register on `FastMCP` in `server.py`) which drives **Mail.app** through **`core.run_applescript()`** (stdin osascript, escaped user input, JSON-safe output). Dev venv: repo root `.venv/`; user plugin venv: `plugin/venv/` (install-time only).

## Dev setup

```bash
python3 -m venv .venv && .venv/bin/pip install -e . pytest
.venv/bin/pytest tests/                    # 221 tests
.venv/bin/apple-mail quick-check --json    # live Mail smoke (~30s)
.venv/bin/python plugin/apple_mail_mcp.py --read-only
```

## Version bump (release together)

- `pyproject.toml` → `[project].version`
- `plugin/.claude-plugin/plugin.json` → `version`
- `.claude-plugin/marketplace.json` → `plugins[0].version` (not `metadata.version`)
- `server.json` → top-level + `packages[0].version`
- `apple-mail-mcpb/manifest.json` → `version`

Sync tool-count claims in manifests with `grep -c "^@mcp.tool" plugin/apple_mail_mcp/tools/*.py`. No repo lint config — don't add without asking.

## Related folders

`plugin/apple_mail_mcp/` (source of truth) · `plugin/` (Claude plugin) · `apple-mail-mcpb/` · `.claude-plugin/` · `tests/` · `tools/` · `docs/` · `tasks/`

**Repo agent skills:** Add under `.agents/skills/<name>/`; symlink `.claude/skills/<name>` → `../../.agents/skills/<name>` (not `.cursor/skills/`). Commit and push after adding or moving skills.
**Post-change ship:** Invoke `finalize-apple-mail-mcp` to sync docs, CLAUDE.md, manifests, then commit and push when the user asks.

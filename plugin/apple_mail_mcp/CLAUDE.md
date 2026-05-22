# CLAUDE.md — `apple_mail_mcp` package

Source of truth for the MCP server and repo CLI. Packaged on PyPI as **`mcp-apple-mail`** (`pyproject.toml` → `plugin/apple_mail_mcp/`).

## Entry flow

**MCP:** `__main__.py` → orphan watcher → `--read-only` / `--draft-safe` → set `server.READ_ONLY` / `server.DRAFT_SAFE` → import package (registers tools) → remove `SEND_TOOLS` if read-only → `mcp.run()`.

**CLI:** `apple-mail` script → `cli.py:main` (same tool functions, no MCP transport). Entry points: `mcp-apple-mail` → `__main__:main`; `apple-mail` → `cli:main`.

## Key modules

| Module | Role |
|--------|------|
| `server.py` | Shared `FastMCP`, env config, `ToolAnnotations` presets, `SEND_TOOLS` |
| `core.py` | `run_applescript`, `escape_applescript`, validation, `@inject_preferences`, script builders |
| `cli.py` | `apple-mail` subcommands (search, inbox, draft, smoke-test, quick-check, …) |
| `__main__.py` | MCP stdio entry, orphan watcher (python-sdk#526), read-only tool removal |
| `__init__.py` | Side-effect imports of six `tools/` modules; `UI_AVAILABLE` flag |
| `constants.py` | Shared patterns (`SKIP_FOLDERS`, newsletter detection, `TIME_RANGES`) |

## `tools/` subfolder

**27 tools** in **6 modules** (inbox 6, search 3, compose 5, manage 6, analytics 4, smart_inbox 3). Verify: `grep -c "^@mcp.tool" tools/*.py`. For tool work read **`tools/CLAUDE.md`** and **`docs/CLAUDE-conventions.md`** — do not duplicate those conventions here.

## Shared state (`server.py`)

- `DEFAULT_MAIL_ACCOUNT` — from env; tools read lazily via `server.DEFAULT_MAIL_ACCOUNT`
- `USER_PREFERENCES` — from `USER_EMAIL_PREFERENCES` env; `@inject_preferences` appends to tool docstrings
- `READ_ONLY` / `DRAFT_SAFE` — set by CLI flags in `__main__.py`
- Annotation presets: `READ_ONLY_TOOL_ANNOTATIONS`, `WRITE_TOOL_ANNOTATIONS`, `IDEMPOTENT_WRITE_TOOL_ANNOTATIONS`, `DESTRUCTIVE_TOOL_ANNOTATIONS`
- `SEND_TOOLS = ("compose_email", "reply_to_email", "forward_email")` — removed in read-only mode

## AppleScript rule

All Mail.app I/O via `core.run_applescript()`. User strings through `core.escape_applescript()`. Catch `core.AppleScriptTimeout` in tools. No raw `subprocess.run(["osascript", …])`.

## Related & dev

- `../start_mcp.sh` — plugin launcher; `../../tests/` mocks `subprocess.run`; `../../tools/validate_manifests.py` — manifest parity
- `.venv/bin/pytest tests/` · `.venv/bin/apple-mail quick-check --account "…"` · `.venv/bin/python -m apple_mail_mcp --read-only`

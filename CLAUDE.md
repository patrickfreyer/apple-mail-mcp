# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Apple Mail MCP is a FastMCP server that exposes 29 tools for managing Apple Mail via MCP. It uses AppleScript as the primary backend and IMAP as a secondary backend for Proton Bridge operations. macOS-only.

## Development Commands

```bash
# Setup and install dependencies
uv sync

# Run the MCP server
uv run python apple_mail_mcp.py

# Or use startup script (auto-creates .venv and syncs deps)
./start_mcp.sh
```

There are no tests, linter, or CI/CD pipeline in this project. Testing is done manually via Claude Desktop or MCP clients.

## Architecture

**Entry point:** `apple_mail_mcp.py` → imports `mcp` from `apple_mail_mcp/` package → calls `mcp.run()`

**Package structure (`apple_mail_mcp/`):**
- `server.py` — Creates the FastMCP instance and loads `USER_EMAIL_PREFERENCES` from env
- `core.py` — Shared helpers: `run_applescript()` (stdin pipe via `osascript -`), `escape_applescript()`, `parse_email_list()`, `inject_preferences` decorator, and AppleScript template generators
- `constants.py` — Newsletter patterns, system folders to skip, thread prefixes, time range mappings
- `imap.py` — IMAP backend for Proton Bridge (SSL/STARTTLS/plain fallback, batch UID fetch, RFC 6851 MOVE)
- `tools/` — 6 modules, each registering tools via `@mcp.tool()` decorators:
  - `inbox.py` — List/overview tools (6 tools)
  - `search.py` — Advanced search tools (8 tools, largest module)
  - `compose.py` — Email composition with CC/BCC (4 tools)
  - `manage.py` — Move, status, trash operations (5 tools)
  - `imap_sort.py` — IMAP-based sorting and bulk move (2 tools)
  - `analytics.py` — Statistics, attachments, export, dashboard (4 tools)

**Tool registration:** Importing a tool module auto-registers its `@mcp.tool()` functions. `__init__.py` imports all tool modules.

## Key Patterns

**AppleScript execution:** All Mail.app interaction goes through `core.run_applescript()` which pipes scripts via stdin to `osascript -` (not `-e` flag). 120s timeout. Escape user strings with `core.escape_applescript()` (backslash before quotes).

**INBOX mailbox fallback:** `core.inbox_mailbox_script()` tries "INBOX" first, falls back to "Inbox" due to macOS Mail's inconsistent naming.

**User preferences:** The `USER_EMAIL_PREFERENCES` env var is injected into tool docstrings via the `@inject_preferences` decorator so Claude can see user workflow preferences.

**Safety limits:** Batch operations have conservative defaults — `move_email`: 1, `manage_trash`: 5, `update_email_status`: 10. These are parameter defaults, not hard limits.

**IMAP config:** Read from `~/.config/apple-mail-mcp/imap.json` or env vars (`PROTON_BRIDGE_HOST`, `PROTON_BRIDGE_PORT`, `PROTON_BRIDGE_USER`, `PROTON_BRIDGE_PASSWORD`).

## Adding a New Tool

1. Add the function in the appropriate `apple_mail_mcp/tools/*.py` module with `@mcp.tool()` decorator
2. The tool is automatically registered when the module is imported by `__init__.py`
3. Use `core.run_applescript()` for Mail.app operations, `imap.py` functions for IMAP operations
4. Use `core.escape_applescript()` for any user-provided strings injected into AppleScript
5. Update CHANGELOG.md with the new tool

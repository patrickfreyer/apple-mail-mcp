# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Apple Mail MCP is a Python-based Model Context Protocol (MCP) server that provides AI assistants access to Apple Mail on macOS. It uses FastMCP for the server framework and AppleScript (via `osascript` subprocess calls) for all Mail.app interactions. Current version: 1.5.0.

## Running & Building

```bash
# Setup
python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt

# Run server directly
python3 apple_mail_mcp.py

# Run via startup wrapper (auto-creates venv if missing)
./start_mcp.sh

# Build distributable MCP Bundle (.mcpb)
cd apple-mail-mcpb && ./build-mcpb.sh
```

There is no formal test suite. Testing is done manually via Claude Desktop or an MCP client.

## Architecture

### Single-file server design

The entire MCP server lives in **`apple_mail_mcp.py`** (~3,500 lines). It contains:
- All 26 MCP tool functions
- AppleScript generation and execution (`run_applescript()`)
- Email output parsing (`parse_email_list()`)
- User preference injection (`@inject_preferences` decorator)

### Tool registration pattern

Every tool follows this pattern:

```python
@mcp.tool()
@inject_preferences
def tool_name(param: str, optional_param: Optional[str] = None) -> str:
    """Docstring (becomes the tool description in MCP)."""
    script = f'''
    tell application "Mail"
        -- AppleScript logic
    end tell
    '''
    return run_applescript(script)
```

The `@inject_preferences` decorator appends the `USER_EMAIL_PREFERENCES` environment variable content to each tool's docstring at runtime.

### Key execution flow

1. Tool is called by MCP client → 2. Python function builds an AppleScript string → 3. `run_applescript()` executes it via `subprocess.run(['osascript', '-e', script])` with 120s timeout → 4. Output is parsed and returned

### Safety limits

Batch operations have built-in default limits to prevent accidental bulk changes:
- `update_email_status`: max 10
- `manage_trash`: max 5
- `move_email`: max 1

### UI Dashboard module

`ui/dashboard.py` creates an interactive HTML dashboard resource (`ui://apple-mail/inbox-dashboard`) using the `mcp-ui-server` package. Template lives in `ui/templates/dashboard.html`.

## Adding a New Tool

1. Add the decorated function to `apple_mail_mcp.py`
2. Add the tool definition to `apple-mail-mcpb/manifest.json` in the `tools` array
3. Update `CHANGELOG.md`
4. Rebuild the bundle with `./apple-mail-mcpb/build-mcpb.sh`

## Other Key Files

- **`apple-mail-mcpb/manifest.json`** — Bundle metadata and tool descriptions for distribution
- **`apple-mail-mcpb/build-mcpb.sh`** — Packages the server into an installable `.mcpb` bundle
- **`start_mcp.sh`** — Wrapper that ensures venv exists before launching
- **`skill-email-management/SKILL.md`** — Companion Claude Code skill with workflow patterns and tool orchestration guidance (~15K lines)
- **`requirements.txt`** — Dependencies: `fastmcp>=0.1.0`, `mcp-ui-server>=0.1.0`

## Configuration

The server accepts a `USER_EMAIL_PREFERENCES` environment variable (set in `claude_desktop_config.json`) that gets injected into all tool docstrings. Example: `"Default to BCG account, show max 50 emails"`.

## macOS Permissions

Requires Automation permission for Mail.app granted in System Settings > Privacy & Security > Automation.

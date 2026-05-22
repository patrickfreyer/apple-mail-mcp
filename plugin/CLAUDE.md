# plugin/ — Claude Code install surface

**Claude Code install surface** — registers the MCP server, ships skills/commands, bootstraps user-local venv. Tool logic lives in `apple_mail_mcp/`; see root `CLAUDE.md` for server architecture.

## Key files

| File | Role |
|------|------|
| `.claude-plugin/plugin.json` | Plugin manifest: `mcpServers`, keywords, category, version |
| `start_mcp.sh` | First-run venv bootstrap + `fastmcp` import verify, then exec server |
| `apple_mail_mcp.py` | Thin entry shim → `apple_mail_mcp.__main__.main()` |
| `requirements.txt` | Runtime deps installed into `plugin/venv/` (not root `.venv/`) |

## MCP wiring

```
Claude Code → /bin/bash ${CLAUDE_PLUGIN_ROOT}/start_mcp.sh → plugin/venv/bin/python3 apple_mail_mcp.py
```

`${CLAUDE_PLUGIN_ROOT}` resolves to this `plugin/` directory at install time. Never hard-code absolute paths in manifests.

## Subfolders

- **`apple_mail_mcp/`** — Python package (source of truth for all 27 MCP tools)
- **`skills/`** — Procedural workflows; see `skills/CLAUDE.md`
- **`commands/`** — Legacy slash command; see `commands/CLAUDE.md`
- **`ui/`** — Inbox dashboard HTML via `mcp-ui-server` (`dashboard.py`, `templates/`)

## Related distribution shapes

- **`../.claude-plugin/marketplace.json`** — Top-level marketplace manifest; `plugins[0].source` → `./plugin`
- **`../apple-mail-mcpb/`** — Claude Desktop `.mcpb` bundle build (separate manifest)

## When to change what

- **Manifest edits** (`plugin.json`, marketplace, mcpb): bump version in all five version files (see root `CLAUDE.md`); run **`plugin-dev:plugin-validator`** before merge.
- **Launcher / deps**: edit `start_mcp.sh` or `requirements.txt`; test fresh venv by removing `plugin/venv/`.
- **New MCP tools**: implement under `apple_mail_mcp/tools/` and register in `apple_mail_mcp/__init__.py` — not in this wrapper layer.
- **New user entry points**: add skills under `skills/` only (no new commands).
- **Venvs**: `plugin/venv/` = user install (gitignored); `../.venv/` = dev pytest/editable install.

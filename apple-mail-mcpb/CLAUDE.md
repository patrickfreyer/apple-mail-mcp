# apple-mail-mcpb/ — Claude Desktop bundle

Build files for the **`.mcpb`** distributable. Same Python server as [`plugin/`](../plugin/) — copied at build, not a separate codebase.

| File | Role |
|------|------|
| `manifest.json` | Version, `tools[]`, `user_config`, server entry |
| `build-mcpb.sh` | Stage `plugin/` → zip `../apple-mail-mcp-v{VERSION}.mcpb` |

```bash
cd apple-mail-mcpb && ./build-mcpb.sh
```

Copies `apple_mail_mcp.py`, `start_mcp.sh`, `requirements.txt`, `apple_mail_mcp/`, mirrored `plugin/skills` → **`skills/`** in build output, optional `ui/`. No venv in bundle — user machine creates it via `start_mcp.sh`. Keep embedded README Python 3.10+ claim in sync.

## tools[] must match code

Full `tools[]` in `manifest.json` must list every `@mcp.tool` name in code; description must claim correct count (**27**). Validated by [`tools/validate_manifests.sh`](../tools/validate_manifests.sh).

## vs plugin/

| | Claude Code | Claude Desktop |
|---|-------------|----------------|
| Manifest | `plugin/.claude-plugin/plugin.json` | `manifest.json` |
| Discovery | `.claude-plugin/marketplace.json` | Direct `.mcpb` install |

Version sync: five files per [`docs/CLAUDE-conventions.md`](../docs/CLAUDE-conventions.md). Open: `dxt_version` bump in [`tasks/todo.md`](../tasks/todo.md).

## Related

[`plugin/CLAUDE.md`](../plugin/CLAUDE.md) · [`tools/CLAUDE.md`](../tools/CLAUDE.md)

# .claude-plugin/ — marketplace manifest

Top-level **Claude Code marketplace** registration → [`plugin/`](../plugin/) via `"source": "./plugin"`.

## Two version fields

| Field | Example | Meaning |
|-------|---------|---------|
| `metadata.version` | `1.0.0` | **This marketplace JSON** — not the plugin. Don't bump on every release. |
| `plugins[0].version` | `3.1.7` | **Plugin release** — sync with `pyproject.toml`, `plugin.json`, `server.json`, mcpb manifest. |

`validate_manifests.sh` checks `plugins[0].version` and tool-count in `plugins[0].description` only.

## Not here

- Plugin manifest → `plugin/.claude-plugin/plugin.json`
- Desktop bundle → [`apple-mail-mcpb/`](../apple-mail-mcpb/)

## Local install

```bash
# From GitHub (users)
claude plugin marketplace add agenticassets/apple-mail-mcp
claude plugin install apple-mail@apple-mail-mcp

# From repo checkout (dev)
claude plugin marketplace add .
claude plugin install apple-mail@apple-mail-mcp
```

Installs the MCP server (27 tools, **`--draft-safe`** by default) plus **nine** auto-discovered workflow skills under `plugin/skills/` — see [`plugin/skills/CLAUDE.md`](../plugin/skills/CLAUDE.md).

After edits: `plugin-dev:plugin-validator` + `tools/validate_manifests.sh` (+ `plugin-dev:skill-reviewer` when skills change).

## Related

[`plugin/docs/CLAUDE.md`](../plugin/docs/CLAUDE.md) · [`apple-mail-mcpb/CLAUDE.md`](../apple-mail-mcpb/CLAUDE.md) · [`docs/CLAUDE-conventions.md`](../docs/CLAUDE-conventions.md)

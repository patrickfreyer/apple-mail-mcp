# tools/ — validation scripts

Dev-infra guardrails — not MCP tools (`plugin/apple_mail_mcp/tools/` is the server).

## validate_manifests

| Script | Role |
|--------|------|
| `validate_manifests.sh` | Bash entry; **CI calls this** |
| `validate_manifests.py` | Python equivalent; covered by `tests/test_validate_manifests.py` |

Enforces (source of truth: `pyproject.toml` `[project].version`):

1. **Version sync** — `plugin.json`, `marketplace.json plugins[0].version`, `server.json` (×2), `apple-mail-mcpb/manifest.json`
2. **Tool count claims** — descriptions must match `rg "^@mcp\.tool" … | wc -l` (**27**)
3. **MCPB name parity** — `@mcp.tool` names ↔ `apple-mail-mcpb/manifest.json` `tools[]`

```bash
bash tools/validate_manifests.sh
```

Skips marketplace `metadata.version` (1.0.0) — see [`.claude-plugin/CLAUDE.md`](../.claude-plugin/CLAUDE.md).

## pre-commit-validate.sh

Manifest validation + mocked pytest. No live Mail. Requires root `.venv/`.

```bash
bash tools/pre-commit-validate.sh
```

## CI

`.github/workflows/ci.yml` (Ubuntu, Python 3.10): `validate_manifests.sh` then `pytest tests/ -q`. Same gate as pre-commit; live Mail is manual ([`docs/AGENT_LIVE_TESTING.md`](../docs/AGENT_LIVE_TESTING.md)).

Run after tool add/remove, version bump, or mcpb `tools[]` edit. Supplement with **`plugin-dev:plugin-validator`** when available.

## Related

[`apple-mail-mcpb/CLAUDE.md`](../apple-mail-mcpb/CLAUDE.md) · [`.claude-plugin/CLAUDE.md`](../.claude-plugin/CLAUDE.md) · [`docs/CLAUDE-conventions.md`](../docs/CLAUDE-conventions.md)

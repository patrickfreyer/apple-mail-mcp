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

## check_wrapper_surface.py

| Script | Role |
|--------|------|
| `check_wrapper_surface.py` | Generated mcporter wrapper command-surface check; covered by `tests/test_wrapper_surface.py` |

Separate from **`validate_manifests`** — manifest validation checks Python `@mcp.tool` ↔ MCPB `tools[]` parity only. The generated `apple-mail` wrapper on PATH embeds schemas at generation time and can drift when new tools are added.

Verifies critical read commands (`get-email-by-id`, `search-emails`, `get-email-thread`, `list-inbox-emails`, `get-inbox-overview`) appear in `apple-mail --help`. Exit 0 when all present; exit 1 when missing. Skips gracefully (exit 0) if no wrapper on PATH.

```bash
python tools/check_wrapper_surface.py
python tools/check_wrapper_surface.py --wrapper /path/to/apple-mail
```

Run after regenerating the mcporter bundle or adding read tools agents rely on.

## pre-commit-validate.sh

Manifest validation + mocked pytest. No live Mail. Requires root `.venv/`.

```bash
bash tools/pre-commit-validate.sh
```

## CI

`.github/workflows/ci.yml` (Ubuntu, Python 3.10): `validate_manifests.sh` then `pytest tests/ -q`. Same gate as pre-commit; live Mail is manual ([`docs/AGENT_LIVE_TESTING.md`](../docs/AGENT_LIVE_TESTING.md)).

Run after tool add/remove, version bump, mcpb `tools[]` edit, or plugin skill marketing copy in manifests. Supplement with **`plugin-dev:plugin-validator`** when available; add **`plugin-dev:skill-reviewer`** when editing `plugin/skills/*/SKILL.md`.

## Related

[`apple-mail-mcpb/CLAUDE.md`](../apple-mail-mcpb/CLAUDE.md) · [`.claude-plugin/CLAUDE.md`](../.claude-plugin/CLAUDE.md) · [`docs/CLAUDE-conventions.md`](../docs/CLAUDE-conventions.md)

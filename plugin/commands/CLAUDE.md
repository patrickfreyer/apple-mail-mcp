# plugin/commands/ — Legacy slash commands

This folder holds **legacy Claude Code slash commands**. New user-facing workflows belong in `../skills/` instead.

## What shipped

| File | Purpose |
|------|---------|
| `email-management.md` | `/email-management` — delegates to the full skill at `${CLAUDE_PLUGIN_ROOT}/skills/email-management/SKILL.md` |

The command frontmatter sets `allowed-tools: ["mcp__apple-mail__*", "Read"]` and passes `$ARGUMENTS` to the model. The command body is a thin router; all procedural detail lives in the skill.

## Skills-only going forward

Do **not** add new commands here. Reasons:

1. Skills trigger automatically from user intent (description-driven).
2. Claude Code often auto-converts plugin commands to skills at install — maintaining both creates drift.
3. Sibling skills ship skill-only — `inbox-triage` is shipped; `email-drafting` and `email-attachments` remain planned.

If you need a new workflow entry point, create `../skills/<name>/SKILL.md` following the `email-management` template. See `../skills/CLAUDE.md`.

## Relationship to skills/

```
commands/email-management.md  ──delegates──▶  skills/email-management/SKILL.md
                                              └── references/, examples/, templates/
```

The command exists for users who invoke `/email-management` explicitly. The skill fires on natural-language triggers without a slash prefix. Both should stay aligned on tool names and safety caps.

## Related folders

- **`../skills/`** — Source of truth for workflow content
- **`../apple_mail_mcp/tools/`** — MCP tools invoked by skill workflows
- **`../.claude-plugin/plugin.json`** — Registers `"commands": ["./commands/"]` alongside `mcpServers`
- **`../../.claude-plugin/marketplace.json`** — Marketplace entry pointing at `./plugin`

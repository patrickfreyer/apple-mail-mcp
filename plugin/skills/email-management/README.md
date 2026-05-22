# Email Management Skill (plugin bundle)

Part of the **Apple Mail Claude Code plugin** skill suite. This directory is the **umbrella** skill for sustained Inbox Zero habits and cross-cutting workflows. Narrower siblings handle specialized intents — see [`../CLAUDE.md`](../CLAUDE.md) for the full routing map.

## What this skill is

- **Apple Mail MCP** = 27 tools (read, search, compose, organize, analyze)
- **This skill** = when to use those tools for long-running inbox discipline, plus references/examples for deep workflows
- **Sibling skills** = faster, sharper entry points (triage scan, taxonomy, archive campaigns, drafting, etc.)

## Contents

```
plugin/skills/email-management/
├── SKILL.md                 # Umbrella workflows + sibling decision tree
├── references/              # analytics, bulk cleanup, thread management
├── examples/                # inbox zero, triage, folder organization walkthroughs
└── templates/               # search patterns, common workflow snippets
```

## Install (Claude Code plugin — recommended)

```bash
claude plugin marketplace add agenticassets/apple-mail-mcp
claude plugin install apple-mail@apple-mail-mcp
```

All nine skills under `plugin/skills/` load automatically. Legacy slash command: `/email-management`.

## Install (standalone copy)

From a repo checkout, copy one skill or the full set:

```bash
# This skill only
cp -r plugin/skills/email-management ~/.claude/skills/email-management

# Full plugin skill suite
for d in apple-mail-operator inbox-triage email-management mailbox-taxonomy \
         email-archive-cleanup mail-rules-advisor email-drafting \
         email-style-profile email-attachments; do
  cp -r "plugin/skills/$d" "$HOME/.claude/skills/$d"
done
```

Claude Desktop `.mcpb` bundles mirror `skills/` inside the archive — see [`../../../apple-mail-mcpb/CLAUDE.md`](../../../apple-mail-mcpb/CLAUDE.md).

## When to use this skill vs siblings

| User intent | Prefer |
|-------------|--------|
| MCP setup / which tool / slow searches | `apple-mail-operator` |
| “What came in today?” quick scan | `inbox-triage` |
| Ongoing Inbox Zero program | **this skill** (`email-management`) |
| Folder naming / taxonomy design | `mailbox-taxonomy` |
| Bulk archive or delete campaigns | `email-archive-cleanup` |
| Mail rule / filter suggestions | `mail-rules-advisor` |
| Draft or reply | `email-drafting` (+ `email-style-profile` for voice) |
| Save attachments | `email-attachments` |

Details live in each skill’s `SKILL.md` frontmatter (`description` triggers) and in [`../CLAUDE.md`](../CLAUDE.md).

## Learning path

1. Read `SKILL.md` — purpose, decision tree, safety caps
2. `examples/inbox-zero-workflow.md` — full methodology
3. `references/bulk-cleanup.md` — before any large move/trash
4. `references/analytics.md` — when using `get_statistics` / `get_top_senders`

## Requirements

- macOS with Apple Mail configured
- Apple Mail MCP server (plugin, PyPI `mcp-apple-mail`, or `.mcpb`)
- Claude Code with skills support

## Authoring / contributing

Follow [`docs/CLAUDE-conventions.md`](../../../docs/CLAUDE-conventions.md) § Skill authoring. Run **`plugin-dev:skill-reviewer`** before merge. Do not add new slash commands — new workflows → new `plugin/skills/<name>/SKILL.md`.

## License

MIT — same as Apple Mail MCP

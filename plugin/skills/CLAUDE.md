# plugin/skills/ — Agent skills directory

Skills are the **primary entry point** for email workflows in Claude Code. They teach the model when and how to call MCP tools — they do not implement tool logic.

## Skills-only policy

**Ship new entry points as skills only.** Do not add new files under `commands/`. The existing `commands/email-management.md` stays for backward compatibility; Claude Code may auto-convert commands to skills at install time, so authoring both is duplicative.

## Current and planned skills

| Directory | Status |
|-----------|--------|
| `email-management/` | Shipped — template for all siblings |
| `email-drafting/` | Planned — compose, reply, forward |
| `inbox-triage/` | Planned — one-off recent-mail passes |
| `email-attachments/` | Planned — download/save attachments |

## SKILL.md conventions (summary)

Follow the shipped `email-management/SKILL.md` as the canonical template. Full rules: [`docs/CLAUDE-conventions.md`](../../docs/CLAUDE-conventions.md) (Skill authoring section).

- **Directory name == frontmatter `name`** (e.g. `email-management/`)
- **`description`**: third-person, 4–6 quoted trigger phrases, names 3–5 central MCP tools, ends with "Do NOT use for X (see \<sibling\>)"
- **Body**: imperative voice; top sections = purpose, when-to-use / when-NOT, performance defaults, decision tree, destructive-op caps
- **Length**: ~1,500–2,000 words in `SKILL.md`; detail → `references/`, examples → `examples/`, scripts → `scripts/`
- **No persona openers** ("You are an expert…")

## Before merging skill changes

Run **`plugin-dev:skill-reviewer`** on the description and body. Description quality determines whether the skill triggers at all.

## Related folders

- **`../commands/`** — Legacy slash command that delegates to `email-management/SKILL.md` via `${CLAUDE_PLUGIN_ROOT}`
- **`../../docs/CLAUDE-conventions.md`** — Deep skill-authoring and tool rules
- **`../apple_mail_mcp/tools/`** — MCP tools referenced in skill prose (search, inbox, compose, manage, analytics, smart_inbox)
- **`../.claude-plugin/plugin.json`** — Plugin manifest; skills auto-discovered from this tree

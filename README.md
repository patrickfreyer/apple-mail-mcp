# Apple Mail MCP Server

<!-- mcp-name: io.github.patrickfreyer/apple-mail -->

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI](https://img.shields.io/pypi/v/mcp-apple-mail)](https://pypi.org/project/mcp-apple-mail/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io)
[![GitHub stars](https://img.shields.io/github/stars/patrickfreyer/apple-mail-mcp?style=social)](https://github.com/patrickfreyer/apple-mail-mcp/stargazers)

## Star History

<a href="https://star-history.com/#patrickfreyer/apple-mail-mcp&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=patrickfreyer/apple-mail-mcp&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=patrickfreyer/apple-mail-mcp&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=patrickfreyer/apple-mail-mcp&type=Date" />
 </picture>
</a>

An MCP server that gives AI assistants full access to Apple Mail -- read, search, compose, organize, and analyze emails via natural language. Built with [FastMCP](https://github.com/jlowin/fastmcp) (`fastmcp>=3.1.0,<4`). **27 tools**, **221** unit tests, Python **3.10+**.

## Documentation map

| Doc | Purpose |
|-----|---------|
| [`CLAUDE.md`](CLAUDE.md) | Root navigation hub for agents |
| [`docs/CLAUDE-conventions.md`](docs/CLAUDE-conventions.md) | Tool performance rules, read-only, skills, plugin-dev |
| [`docs/AGENT_LIVE_TESTING.md`](docs/AGENT_LIVE_TESTING.md) | Live Mail verification via `apple-mail` CLI |
| [`plugin/CLAUDE.md`](plugin/CLAUDE.md) | Plugin wrapper & `start_mcp.sh` |
| [`plugin/apple_mail_mcp/CLAUDE.md`](plugin/apple_mail_mcp/CLAUDE.md) | Package entry, `core.py`, CLI |
| [`plugin/apple_mail_mcp/tools/CLAUDE.md`](plugin/apple_mail_mcp/tools/CLAUDE.md) | MCP tool modules |
| [`plugin/skills/CLAUDE.md`](plugin/skills/CLAUDE.md) | Skill authoring |
| [`plugin/commands/CLAUDE.md`](plugin/commands/CLAUDE.md) | Legacy slash commands |
| [`tests/CLAUDE.md`](tests/CLAUDE.md) | Test layout & AppleScript mocks |
| [`tools/CLAUDE.md`](tools/CLAUDE.md) | Manifest validation scripts |
| [`docs/CLAUDE.md`](docs/CLAUDE.md) | Docs folder index |
| [`tasks/CLAUDE.md`](tasks/CLAUDE.md) | Phase plans & backlog |
| [`apple-mail-mcpb/CLAUDE.md`](apple-mail-mcpb/CLAUDE.md) | Desktop bundle build |
| [`.claude-plugin/CLAUDE.md`](.claude-plugin/CLAUDE.md) | Marketplace manifest |

## Quick Install

**Prerequisites:** macOS with Apple Mail configured, Python 3.10+

### Claude Code Plugin (Recommended)

One install — MCP server (27 tools), `/email-management` slash command, and two skills (`email-management`, `inbox-triage`):

```bash
claude plugin marketplace add patrickfreyer/apple-mail-mcp
claude plugin install apple-mail@apple-mail-mcp
```

Then restart Claude Code.

### Other Install Methods

<details>
<summary><strong>Repo CLI + MCP runtime</strong></summary>

This fork includes a maintained `apple-mail` CLI that wraps the same Python
tool code as the MCP server. It is meant for humans, shell scripts, smoke
tests, and agents on another Mac.

```bash
git clone https://github.com/agenticassets/apple-mail-mcp.git
cd apple-mail-mcp
python3 -m venv .venv
.venv/bin/pip install -e .

.venv/bin/apple-mail accounts --json
.venv/bin/apple-mail search --account "Gmail" --query "invoice" --limit 10 --json
.venv/bin/apple-mail show --account "Gmail" --id 12345 --json
.venv/bin/apple-mail draft --account "Gmail" --to person@example.com --subject "Draft" --body "Draft body"
.venv/bin/apple-mail quick-check --account "Gmail" --json
.venv/bin/apple-mail perf-test --account "Gmail" --json
.venv/bin/apple-mail perf-test --include-analysis --account "Gmail" --json
.venv/bin/apple-mail smoke-test --account "Gmail" --json
```

See [`docs/AGENT_LIVE_TESTING.md`](docs/AGENT_LIVE_TESTING.md) for batteries, permissions, and when to use each command.

Generate draft-safe Claude/OpenClaw MCP config from the same checkout:

```bash
.venv/bin/apple-mail mcp-config --repo "$(pwd)"
```

</details>

<details>
<summary><strong>uvx (zero install, MCP server only)</strong></summary>

```bash
claude mcp add apple-mail -- uvx mcp-apple-mail
```

Or for Claude Desktop (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "apple-mail": {
      "command": "uvx",
      "args": ["mcp-apple-mail"]
    }
  }
}
```

</details>

<details>
<summary><strong>pip install (MCP server only)</strong></summary>

```bash
pip install mcp-apple-mail
claude mcp add apple-mail -- mcp-apple-mail
```

</details>

<details>
<summary><strong>Claude Desktop MCPB</strong></summary>

1. Download the latest `apple-mail-mcp-*.mcpb` from [Releases](https://github.com/patrickfreyer/apple-mail-mcp/releases)
2. Open Claude Desktop → Settings → Developer → MCP Servers → Install from file
3. Select the `.mcpb` file and grant Mail.app permissions

</details>

<details>
<summary><strong>Manual setup</strong></summary>

```bash
git clone https://github.com/patrickfreyer/apple-mail-mcp.git
cd apple-mail-mcp/plugin
python3 -m venv venv
venv/bin/pip install -r requirements.txt

claude mcp add apple-mail -- /bin/bash $(pwd)/start_mcp.sh
```

</details>

## Tools (27)

### Reading & Search
| Tool | Description |
|------|-------------|
| `get_inbox_overview` | Dashboard with unread counts, folders, and recent emails |
| `list_inbox_emails` | List emails (defaults to 50 most recent). Async parallel per-account dispatch |
| `get_mailbox_unread_counts` | Unread counts per mailbox or per-account summary |
| `list_accounts` | List all configured Mail accounts |
| `list_account_addresses` | List sender aliases configured for a Mail account |
| `search_emails` | Unified search — subject, sender, body, dates, attachments. Defaults to last 48h and the default account |
| `get_email_by_id` | Fetch one exact email by the Apple Mail message id returned from search results |
| `get_email_thread` | Conversation thread view across Inbox + Sent |

### Organization
| Tool | Description |
|------|-------------|
| `list_mailboxes` | Folder hierarchy with optional message counts |
| `create_mailbox` | Create new mailboxes (supports nested paths) |
| `move_email` | Move emails with filters (subject, sender, date, read status, dry-run). Default max 50 |
| `update_email_status` | Mark read/unread, flag/unflag — by filters or message IDs. Default max 10 |
| `manage_trash` | Soft delete, permanent delete, empty trash. Default max 5 |
| `synchronize_account` | Trigger Mail.app to fetch new messages for an account (or all) |

### Composition
| Tool | Description |
|------|-------------|
| `compose_email` | Send a new email (defaults to `DEFAULT_MAIL_ACCOUNT`) |
| `reply_to_email` | Reply or reply-all with optional HTML body |
| `forward_email` | Forward with optional message, CC/BCC |
| `manage_drafts` | Create, list, send, and delete drafts (`send` blocked in `--read-only`) |
| `create_rich_email_draft` | Build a multipart HTML `.eml` draft, open in Mail, optionally save to Drafts |

### Attachments
| Tool | Description |
|------|-------------|
| `list_email_attachments` | List attachments with names and sizes (capped at 50 by default) |
| `save_email_attachment` | Save attachments to disk (validates target path) |

### Smart Inbox
| Tool | Description |
|------|-------------|
| `get_awaiting_reply` | Sent emails that haven't received a reply (default last 7 days) |
| `get_needs_response` | Unread emails likely needing a response (filters out newsletters/automated) |
| `get_top_senders` | Most frequent senders by count or domain over a date window |

### Analytics & Export
| Tool | Description |
|------|-------------|
| `get_statistics` | Account overview, sender stats, or mailbox breakdown (top 20 mailboxes × 500 msgs) |
| `export_emails` | Export single emails or full mailboxes to TXT/HTML (default cap 1000) |
| `inbox_dashboard` | Interactive UI dashboard (requires `mcp-ui-server`) |

## Configuration

### Read-Only Mode

Pass `--read-only` to disable tools that send email (`compose_email`, `reply_to_email`, `forward_email`). Draft management remains available (list, create, delete) but sending a draft via `manage_drafts` is blocked.

```json
{
  "mcpServers": {
    "apple-mail": {
      "command": "/path/to/venv/bin/python3",
      "args": ["/path/to/apple_mail_mcp.py", "--read-only"]
    }
  }
}
```

### Draft-Safe Mode

Pass `--draft-safe` to keep read, search, draft, and open-for-review workflows available while blocking actual sends. This is the recommended mode for shared agent workspaces.

```json
{
  "mcpServers": {
    "apple-mail": {
      "command": "/path/to/plugin/start_mcp.sh",
      "args": ["--draft-safe"]
    }
  }
}
```

In draft-safe mode:

- `compose_email`, `reply_to_email`, and `forward_email` default to draft behavior
- explicit `mode="send"` calls return an error
- `manage_drafts action="send"` returns an error

### Default Mail Account

Set `DEFAULT_MAIL_ACCOUNT` to make most tools default to one account instead of scanning every configured Mail account. This is the single biggest perf win on multi-account setups. Tools still accept an explicit `account` parameter to override, and you can pass `all_accounts=True` to a tool that supports it for explicit cross-account scope.

```json
{
  "mcpServers": {
    "apple-mail": {
      "command": "/path/to/venv/bin/python3",
      "args": ["/path/to/apple_mail_mcp.py"],
      "env": {
        "DEFAULT_MAIL_ACCOUNT": "Work"
      }
    }
  }
}
```

Use the exact account name as it appears in Apple Mail (e.g. `Gmail`, `Work`, `iCloud`). Leave unset to query all accounts by default.

### User Preferences (Optional)

Set `USER_EMAIL_PREFERENCES` to give the assistant context about your workflow. The string is injected into every preference-aware tool's docstring so the model sees it as part of the tool description.

```json
{
  "mcpServers": {
    "apple-mail": {
      "command": "/path/to/venv/bin/python3",
      "args": ["/path/to/apple_mail_mcp.py"],
      "env": {
        "DEFAULT_MAIL_ACCOUNT": "Work",
        "USER_EMAIL_PREFERENCES": "Prefer Archive folder over Trash, show max 25 emails, default to last week for triage"
      }
    }
  }
}
```

For `.mcpb` installs, configure both under Claude Desktop → **Developer > MCP Servers > Apple Mail MCP** (the bundle exposes them via `user_config`).

### Performance Defaults

To stay fast on large mailboxes (24K+ messages), the server applies conservative defaults you can opt out of per-call:

| Default | Tools | Override |
|---------|-------|----------|
| Last 48 hours | `search_emails`, `get_awaiting_reply`, `get_needs_response`, `get_top_senders` | Pass `recent_days=N` (e.g. `7` for a week, `0` for unlimited) |
| 50 emails max | `list_inbox_emails`, `list_email_attachments` | Pass `max_emails` / `max_results` |
| Single account | All scoped tools when `DEFAULT_MAIL_ACCOUNT` is set | Pass `account=<name>` or `all_accounts=True` |
| Per-call timeout | All long-running tools | Pass `timeout=<seconds>` |

When a per-account call times out in a multi-account fan-out, you get partial results plus an `errors` field naming the slow account.

### Safety Limits (destructive ops)

Batch operations cap by default to prevent accidental bulk actions. Override via the per-tool parameter when needed.

| Operation | Default cap | Param |
|-----------|-------------|-------|
| `move_email` | 50 | `max_moves` |
| `update_email_status` | 10 | `max_updates` |
| `manage_trash` | 5 | `max_deletes` |
| `export_emails` | 1000 | `max_emails` |

## Usage Examples

```
Show me an overview of my inbox
Search for emails about "project update" in my Gmail
Reply to the email about "Domain name" with "Thanks for the update!"
Move emails with "invoice" in the subject to my Archive folder
Show me email statistics for the last 30 days
Create a rich HTML draft for a weekly update and open it in Mail
```

## CLI

Install from a repo checkout:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

Common commands:

```bash
apple-mail accounts --json
apple-mail addresses --json
apple-mail inbox --account "Gmail" --limit 10 --json
apple-mail search --account "Gmail" --query "invoice" --limit 10 --json
apple-mail show --account "Gmail" --id 12345 --json
apple-mail mailboxes --account "Gmail" --json
apple-mail draft --account "Gmail" --to person@example.com --subject "Draft" --body "Draft body"
apple-mail mcp-config --repo "$(pwd)"
apple-mail quick-check --account "Gmail" --json
apple-mail perf-test --account "Gmail" --json
apple-mail perf-test --include-analysis --account "Gmail" --json
apple-mail smoke-test --account "Gmail" --json
```

Live verification guide: [`docs/AGENT_LIVE_TESTING.md`](docs/AGENT_LIVE_TESTING.md).

Use `perf-test --include-analysis` to gate triage tools (`needs-response`, `awaiting-reply`, `top-senders`, `statistics`) in addition to the core battery.

The CLI keeps write operations draft-first. It intentionally does not expose
send/delete shortcuts; use the MCP tools with `--draft-safe` for shared agents.

### Rich HTML Drafts

Use `create_rich_email_draft` when you need a visually formatted email, newsletter, or leadership update.

- It generates an unsent `.eml` file with multipart plain-text + HTML bodies
- It can open the draft directly in Mail for editing
- It can optionally ask Mail to save the opened compose window into Drafts
- It accepts partial details, so you can start with just an account and subject and fill in the rest later

This is more reliable than injecting raw HTML into AppleScript `content`, which Mail often stores as literal markup.

## Claude Code Skills

Two companion skills ship with the plugin and load automatically on install:

| Skill | Purpose |
|-------|---------|
| [`email-management`](plugin/skills/email-management/) | Sustained organization, Inbox Zero, folder workflows |
| [`inbox-triage`](plugin/skills/inbox-triage/) | 5–10 min daily read-first scan (needs-response, awaiting-reply, top senders) |

For standalone MCP installs, copy manually:

```bash
cp -r plugin/skills/email-management ~/.claude/skills/email-management
cp -r plugin/skills/inbox-triage ~/.claude/skills/inbox-triage
```

The plugin MCP server starts with **`--draft-safe`** by default (see `plugin/.claude-plugin/plugin.json`).

## Requirements

- macOS with Apple Mail configured
- Python 3.10+
- `fastmcp>=3.1.0,<4` (+ optional `mcp-ui-server` for the `inbox_dashboard` tool)
- Claude Desktop or any MCP-compatible client
- Mail.app permissions: Automation + Mail Data Access (grant in **System Settings > Privacy & Security > Automation**)

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Mail.app not responding | Ensure Mail.app is running; check Automation permissions in System Settings |
| Slow searches on a large account | Set `DEFAULT_MAIL_ACCOUNT` to the account you actually work in. Pair `account=` with `recent_days=` (default 48h) for tight scopes. Pass `include_content=False` if you don't need bodies |
| One account times out across a fan-out | Returned JSON includes an `errors` array naming the slow account. The other accounts' results are still returned. Bump the call's `timeout=` parameter if you need to wait longer for the slow one |
| Mailbox not found | Use exact folder names; nested folders use `/` separator (e.g., `Projects/Alpha`) |
| Permission errors | Grant access in **System Settings > Privacy & Security > Automation** |
| Rich draft shows raw HTML | Use `create_rich_email_draft` instead of pasting HTML into `manage_drafts` or AppleScript `content` |

## Project Structure

```
apple-mail-mcp/
├── .claude-plugin/
│   └── marketplace.json       # Marketplace manifest (for plugin distribution)
├── plugin/                    # Claude Code plugin
│   ├── .claude-plugin/
│   │   └── plugin.json        # Plugin manifest
│   ├── commands/              # /email-management slash command
│   ├── skills/                # email-management + inbox-triage skills
│   ├── apple_mail_mcp/        # Python MCP server package (27 tools)
│   ├── apple_mail_mcp.py      # Entry point
│   ├── start_mcp.sh           # Startup wrapper (auto-creates venv)
│   └── requirements.txt
├── apple-mail-mcpb/           # MCPB build files (Claude Desktop)
├── LICENSE
└── README.md
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit and push
4. Open a Pull Request

## License

MIT -- see [LICENSE](LICENSE).

## Links

- [Changelog](CHANGELOG.md)
- [Issues](https://github.com/patrickfreyer/apple-mail-mcp/issues)
- [Discussions](https://github.com/patrickfreyer/apple-mail-mcp/discussions)
- [FastMCP](https://github.com/jlowin/fastmcp)
- [Model Context Protocol](https://modelcontextprotocol.io)

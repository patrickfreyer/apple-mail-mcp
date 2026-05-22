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

An MCP server that gives AI assistants full access to Apple Mail -- read, search, compose, organize, and analyze emails via natural language. Built with [FastMCP](https://github.com/jlowin/fastmcp).

## Quick Install

**Prerequisites:** macOS with Apple Mail configured, Python 3.10+

### Claude Code Plugin (Recommended)

Two commands — gets you the MCP server, `/email-management` slash command, and the Email Management Expert skill:

```bash
claude plugin marketplace add patrickfreyer/apple-mail-mcp
claude plugin install apple-mail@apple-mail-mcp
```

Then restart Claude Code.

### Other Install Methods

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

1. Download `apple-mail-mcp-v2.2.0.mcpb` from [Releases](https://github.com/patrickfreyer/apple-mail-mcp/releases)
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

## Tools (26)

### Reading & Search
| Tool | Description |
|------|-------------|
| `get_inbox_overview` | Dashboard with unread counts, folders, and recent emails |
| `list_inbox_emails` | List emails (defaults to 50 most recent). Async parallel per-account dispatch |
| `get_mailbox_unread_counts` | Unread counts per mailbox or per-account summary |
| `list_accounts` | List all configured Mail accounts |
| `list_account_addresses` | List sender aliases configured for a Mail account |
| `search_emails` | Unified search — subject, sender, body, dates, attachments. Defaults to last 48h and the default account |
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

### Rich HTML Drafts

Use `create_rich_email_draft` when you need a visually formatted email, newsletter, or leadership update.

- It generates an unsent `.eml` file with multipart plain-text + HTML bodies
- It can open the draft directly in Mail for editing
- It can optionally ask Mail to save the opened compose window into Drafts
- It accepts partial details, so you can start with just an account and subject and fill in the rest later

This is more reliable than injecting raw HTML into AppleScript `content`, which Mail often stores as literal markup.

## Email Management Skill

A companion [Claude Code Skill](plugin/skills/email-management/) is included that teaches Claude expert email workflows (Inbox Zero, daily triage, folder organization). When installed as a plugin, the skill is loaded automatically. For standalone MCP installs, copy it manually:

```bash
cp -r plugin/skills/email-management ~/.claude/skills/email-management
```

## Requirements

- macOS with Apple Mail configured
- Python 3.10+
- `fastmcp` (+ optional `mcp-ui-server` for the `inbox_dashboard` tool)
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
│   ├── skills/                # Email Management Expert skill
│   ├── apple_mail_mcp/        # Python MCP server package (26 tools)
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

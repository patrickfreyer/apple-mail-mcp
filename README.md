# Apple Mail MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.7+](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
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

## Installation

**Prerequisites:** macOS with Apple Mail configured, Python 3.7+

### Option A: Claude Code Plugin (Recommended)

```bash
# Clone the repo
git clone https://github.com/patrickfreyer/apple-mail-mcp.git

# Install as plugin (from Claude Code)
/plugin install /path/to/apple-mail-mcp
```

The plugin automatically:
- Registers the MCP server with Claude Code
- Adds the `/email-management` slash command
- Loads the Email Management Expert skill

### Option B: Claude Desktop (MCPB)

1. Download `apple-mail-mcp-v2.2.0.mcpb` from [Releases](https://github.com/patrickfreyer/apple-mail-mcp/releases)
2. Open Claude Desktop → Settings → Developer → MCP Servers → Install from file
3. Select the `.mcpb` file and grant Mail.app permissions
4. Restart Claude Desktop

### Option C: Manual MCP Setup

```bash
git clone https://github.com/patrickfreyer/apple-mail-mcp.git
cd apple-mail-mcp
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# Add to Claude Code
claude mcp add apple-mail -- /bin/bash $(pwd)/start_mcp.sh
```

## Tools (22)

### Reading & Search
| Tool | Description |
|------|-------------|
| `get_inbox_overview` | Dashboard with unread counts, folders, and recent emails |
| `list_inbox_emails` | List emails with account/read-status filtering and optional content preview |
| `get_mailbox_unread_counts` | Unread counts per mailbox or per-account summary |
| `list_accounts` | List all configured Mail accounts |
| `search_emails` | Unified search — subject, sender, body text, dates, attachments, cross-account |
| `get_email_thread` | Conversation thread view |

### Organization
| Tool | Description |
|------|-------------|
| `list_mailboxes` | Folder hierarchy with message counts |
| `create_mailbox` | Create new mailboxes (supports nested paths) |
| `move_email` | Move/archive emails with filters (subject, sender, date, read status, dry-run) |
| `update_email_status` | Mark read/unread, flag/unflag — by filters or message IDs |
| `manage_trash` | Soft delete, permanent delete, empty trash (with dry-run) |

### Composition
| Tool | Description |
|------|-------------|
| `compose_email` | Send new emails (plain text or HTML body) |
| `reply_to_email` | Reply or reply-all with optional HTML body |
| `forward_email` | Forward with optional message, CC/BCC |
| `manage_drafts` | Create, list, send, and delete drafts |
| `create_rich_email_draft` | Build a rich HTML `.eml` draft, open it in Mail, and optionally save it to Drafts |

### Attachments
| Tool | Description |
|------|-------------|
| `list_email_attachments` | List attachments with names and sizes |
| `save_email_attachment` | Save attachments to disk |

### Smart Inbox
| Tool | Description |
|------|-------------|
| `get_awaiting_reply` | Find sent emails that haven't received a reply |
| `get_needs_response` | Identify emails that likely need your response |
| `get_top_senders` | Analyse most frequent senders by count or domain |

### Analytics & Export
| Tool | Description |
|------|-------------|
| `get_statistics` | Email analytics (volume, top senders, read ratios) |
| `export_emails` | Export single emails or mailboxes to TXT/HTML |
| `inbox_dashboard` | Interactive UI dashboard (requires mcp-ui-server) |

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

### User Preferences (Optional)

Set the `USER_EMAIL_PREFERENCES` environment variable to give the assistant context about your workflow:

```json
{
  "mcpServers": {
    "apple-mail": {
      "command": "/path/to/venv/bin/python3",
      "args": ["/path/to/apple_mail_mcp.py"],
      "env": {
        "USER_EMAIL_PREFERENCES": "Default to BCG account, show max 50 emails, prefer Archive and Projects folders"
      }
    }
  }
}
```

For `.mcpb` installs, configure this in Claude Desktop under **Developer > MCP Servers > Apple Mail MCP**.

### Safety Limits

Batch operations have conservative defaults to prevent accidental bulk actions:

| Operation | Default Limit |
|-----------|---------------|
| `update_email_status` | 10 emails |
| `manage_trash` | 5 emails |
| `move_email` | 1 email |

Override via function parameters when needed.

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

A companion [Claude Code Skill](skill-email-management/) is included that teaches Claude expert email workflows (Inbox Zero, daily triage, folder organization). Install it alongside the MCP for intelligent, multi-step email management:

```bash
cp -r skill-email-management ~/.claude/skills/email-management
```

See [skill-email-management/README.md](skill-email-management/README.md) for details.

## Requirements

- macOS with Apple Mail configured
- Python 3.7+
- `fastmcp` (+ optional `mcp-ui-server` for dashboard)
- Claude Desktop or any MCP-compatible client
- Mail.app permissions: Automation + Mail Data Access (grant in **System Settings > Privacy & Security > Automation**)

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Mail.app not responding | Ensure Mail.app is running; check Automation permissions in System Settings |
| Slow searches | Set `include_content: false` and lower `max_results` |
| Mailbox not found | Use exact folder names; nested folders use `/` separator (e.g., `Projects/Alpha`) |
| Permission errors | Grant access in **System Settings > Privacy & Security > Automation** |
| Rich draft shows raw HTML | Use `create_rich_email_draft` instead of pasting HTML into `manage_drafts` or AppleScript `content` |

## Project Structure

```
apple-mail-mcp/
├── apple_mail_mcp.py          # Main MCP server (27 tools)
├── requirements.txt           # Python dependencies
├── apple-mail-mcpb/           # MCP Bundle build files
├── skill-email-management/    # Email Management Expert Skill
├── CHANGELOG.md
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

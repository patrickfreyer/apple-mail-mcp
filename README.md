# Apple Mail MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.7+](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io)
[![GitHub stars](https://img.shields.io/github/stars/patrickfreyer/apple-mail-mcp?style=social)](https://github.com/patrickfreyer/apple-mail-mcp/stargazers)

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=patrickfreyer/apple-mail-mcp&type=Date)](https://star-history.com/#patrickfreyer/apple-mail-mcp&Date)

An MCP server that gives AI assistants full access to Apple Mail -- read, search, compose, organize, and analyze emails via natural language. Built with [FastMCP](https://github.com/jlowin/fastmcp).

## Quick Start

**Prerequisites:** macOS with Apple Mail configured, Python 3.7+

```bash
git clone https://github.com/patrickfreyer/apple-mail-mcp.git
cd apple-mail-mcp
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "apple-mail": {
      "command": "/path/to/apple-mail-mcp/venv/bin/python3",
      "args": ["/path/to/apple-mail-mcp/apple_mail_mcp.py"]
    }
  }
}
```

Restart Claude Desktop and grant Mail.app permissions when prompted.

> **Tip:** An `.mcpb` bundle is also available on the [Releases](https://github.com/patrickfreyer/apple-mail-mcp/releases) page for one-click install in Claude Desktop.

## Tools (26)

### Reading & Search
| Tool | Description |
|------|-------------|
| `get_inbox_overview` | Dashboard with unread counts, folders, and recent emails |
| `list_inbox_emails` | List emails with account/read-status filtering |
| `get_email_with_content` | Search emails with full content preview |
| `get_unread_count` | Unread count per account |
| `list_accounts` | List all configured Mail accounts |
| `get_recent_emails` | Recent emails from a specific account |
| `get_recent_from_sender` | Recent emails from a sender with time-range filters |
| `search_emails` | Advanced multi-criteria search (subject, sender, dates, attachments) |
| `search_by_sender` | Find all emails from a specific sender |
| `search_email_content` | Full-text search in email bodies |
| `search_all_accounts` | Cross-account unified search |
| `get_newsletters` | Detect newsletter and subscription emails |
| `get_email_thread` | Conversation thread view |

### Organization
| Tool | Description |
|------|-------------|
| `list_mailboxes` | Folder hierarchy with message counts |
| `move_email` | Move emails between folders (supports nested paths) |
| `update_email_status` | Batch mark read/unread, flag/unflag |
| `manage_trash` | Soft delete, permanent delete, empty trash |

### Composition
| Tool | Description |
|------|-------------|
| `compose_email` | Send new emails (TO, CC, BCC) |
| `reply_to_email` | Reply or reply-all with optional CC/BCC |
| `forward_email` | Forward with optional message, CC/BCC |
| `manage_drafts` | Create, list, send, and delete drafts |

### Attachments
| Tool | Description |
|------|-------------|
| `list_email_attachments` | List attachments with names and sizes |
| `save_email_attachment` | Save attachments to disk |

### Analytics & Export
| Tool | Description |
|------|-------------|
| `get_statistics` | Email analytics (volume, top senders, read ratios) |
| `export_emails` | Export single emails or mailboxes to TXT/HTML |
| `inbox_dashboard` | Interactive UI dashboard (requires mcp-ui-server) |

## Configuration

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
```

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

## Project Structure

```
apple-mail-mcp/
├── apple_mail_mcp.py          # Main MCP server (26 tools)
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

# Apple Mail MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.7+](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io)

A comprehensive Model Context Protocol (MCP) server that provides AI assistants with natural language access to Apple Mail. Built with [FastMCP](https://github.com/jlowin/fastmcp), this server enables reading, searching, organizing, composing, and managing emails directly through Claude Desktop or other MCP-compatible clients.

**✨ NEW:** Now includes the [Email Management Expert Skill](#-email-management-expert-skill) - a comprehensive Claude Code skill that teaches Claude intelligent email management workflows and productivity strategies!

## Features

### 📧 Email Reading & Search
- **Inbox Overview**: Dashboard view with unread counts, folder structure, and recent emails
- **Advanced Search**: Multi-criteria search (subject, sender, attachments, read status, date ranges)
- **Cross-Folder Search**: Search across all mailboxes or specific folders
- **Email Content**: Full content preview with configurable length
- **Thread View**: Conversation threading across all mailboxes
- **Recent Emails**: Quick access to latest messages per account

### 📁 Email Organization
- **Mailbox Management**: List and navigate folder hierarchies
- **Move Emails**: Transfer messages between folders (supports nested mailboxes)
- **Status Updates**: Batch mark as read/unread, flag/unflag
- **Trash Management**: Soft delete, permanent delete, and empty trash

### ✉️ Email Composition
- **Compose**: Send new emails with TO, CC, BCC support
- **Reply**: Respond to messages (single or reply-all)
- **Forward**: Forward emails with optional custom message
- **Draft Management**: Create, list, send, and delete drafts

### 📎 Attachment Handling
- **List Attachments**: View all attachments with names and sizes
- **Save Attachments**: Download specific attachments to disk

### 📊 Analytics & Export
- **Statistics**: Comprehensive email analytics (volume, top senders, mailbox distribution)
- **Export**: Export single emails or entire mailboxes to TXT/HTML formats

## 🎓 Email Management Expert Skill

**NEW:** This repository now includes a comprehensive **Claude Code Skill** that teaches Claude how to be an expert email management assistant!

### What's a Skill?

A **Skill** is a Claude Code feature that packages expertise and workflows, teaching Claude not just *what* it can do (MCP tools), but *how* to do it effectively. It's like giving Claude a productivity consultant for email management.

### MCP + Skill = Intelligent Email Management

- **Apple Mail MCP** (this server) = The **tools** (25 email functions)
- **Email Management Skill** ([skill-email-management/](skill-email-management/)) = The **expertise** (workflows, strategies, best practices)

Together, they create an intelligent assistant that knows both the capabilities and the best ways to use them.

### What You Get with the Skill

**📋 Complete Workflows:**
- **Inbox Zero** - Achieve and maintain empty inbox
- **Daily Email Triage** - Process emails quickly (10-15 min)
- **Folder Organization** - Structure strategies and filing systems
- **Advanced Search** - Find any email instantly
- **Bulk Operations** - Clean up and organize efficiently

**🧠 Expert Knowledge:**
- Industry-standard productivity methods (GTD, Inbox Zero)
- Tool orchestration patterns (when to use which tool)
- Safety-first approaches (backups, limits, confirmations)
- Context-aware suggestions based on inbox state

**📚 Ready-to-Use Resources:**
- 6 detailed documents (3,500+ lines)
- Copy-paste workflow templates
- Comprehensive search pattern reference
- Common scenarios and solutions

### Installing the Skill

The skill works alongside the MCP. Install it to your Claude Code user scope:

```bash
# Clone this repo (if you haven't already)
git clone https://github.com/patrickfreyer/apple-mail-mcp.git
cd apple-mail-mcp

# Install skill to user scope (available in all projects)
cp -r skill-email-management ~/.claude/skills/email-management
```

That's it! The skill activates automatically when you mention email management topics.

### Using the Skill

Once installed, just ask Claude Code about email management:

**Examples:**
- "Help me achieve inbox zero"
- "Triage my inbox"
- "How should I organize my project emails?"
- "Find all emails from John about the Alpha project"
- "Clean up old emails from last year"

Claude will now:
1. ✅ Recognize email management requests
2. ✅ Load expert workflows and best practices
3. ✅ Use MCP tools intelligently
4. ✅ Provide actionable step-by-step guidance

### What's Inside the Skill

```
skill-email-management/
├── SKILL.md                        # Core workflows & tool orchestration
├── examples/
│   ├── inbox-zero-workflow.md     # Complete inbox zero methodology
│   ├── email-triage.md            # Quick daily triage techniques
│   └── folder-organization.md     # Folder structure strategies
└── templates/
    ├── common-workflows.md        # Copy-paste workflow patterns
    └── search-patterns.md         # Comprehensive search reference
```

**📖 [Read the full Skill documentation →](skill-email-management/README.md)**

### Before vs. After the Skill

| Before Skill | After Skill |
|--------------|-------------|
| "Show me my emails" | "Let me analyze your inbox state and suggest an optimal workflow" |
| Uses tools individually | Orchestrates multi-step workflows intelligently |
| Generic responses | Expert productivity strategies and context-aware advice |
| User figures out sequences | Pre-built workflows (Inbox Zero, GTD, triage, etc.) |

**💡 Pro Tip:** The skill and MCP are designed to work together. Install both for the complete intelligent email management experience!

## Installation

### Prerequisites
- macOS with Apple Mail configured
- Python 3.7 or higher
- At least one Mail account configured in Apple Mail
- Claude Desktop (for MCP Bundle installation) or any MCP-compatible client

### Option 1: MCP Bundle (.mcpb) - Recommended

The easiest way to install is using the pre-built MCP Bundle:

1. Download the latest `.mcpb` file from the [Releases](https://github.com/patrickfreyer/apple-mail-mcp/releases) page

2. Install in Claude Desktop:
   - Open Claude Desktop settings
   - Navigate to **Developer > MCP Servers**
   - Click **Install from file**
   - Select the downloaded `.mcpb` file
   - Restart Claude Desktop

3. Grant permissions when prompted:
   - Mail.app Control
   - Mail Data Access

### Option 2: Manual Installation

1. Clone the repository:
```bash
git clone https://github.com/patrickfreyer/apple-mail-mcp.git
cd apple-mail-mcp
```

2. Create and activate a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Configure Claude Desktop by adding to `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "apple-mail": {
      "command": "/path/to/apple-mail-mcp/venv/bin/python3",
      "args": [
        "/path/to/apple-mail-mcp/apple_mail_mcp.py"
      ]
    }
  }
}
```

5. Restart Claude Desktop

### Building Your Own .mcpb Bundle

To build a distributable MCP Bundle:

```bash
cd apple-mail-mcpb
./build-mcpb.sh
```

The script will create `apple-mail-mcp-v{version}.mcpb` in the parent directory.

## Usage Examples

Once installed, you can interact with Apple Mail using natural language in Claude:

### Reading Emails
```
Show me an overview of my inbox
How many unread emails do I have?
List recent emails from my work account
Search for emails about "project update" in my Gmail account
Search for emails about "invoice" across all folders in my work account
Show me the conversation thread about "meeting"
```

### Organizing Emails
```
Move emails with "invoice" in the subject to my Archive folder
Mark all emails from john@example.com as read
Flag important emails about "deadline"
Delete emails from newsletter@example.com
```

### Composing & Responding
```
Reply to the email about "Domain name" with "Thanks for the update!"
Compose an email to jane@example.com from my work account
Forward the email about "meeting notes" to team@example.com
Create a draft email to John about project status
```

### Managing Attachments
```
List attachments in emails about "invoice"
Save the PDF attachment from the email about "contract"
```

### Analytics & Export
```
Show me email statistics for the last 30 days
Export all emails from my Archive folder to HTML
Get statistics for emails from sarah@example.com
```

## Available Tools

The MCP server provides 25 tools:

| Tool | Description |
|------|-------------|
| `get_inbox_overview` | Comprehensive dashboard with unread counts, folders, and recent emails |
| `list_inbox_emails` | List emails from inbox with filtering options |
| `get_email_with_content` | Search emails with full content preview |
| `search_emails` | Advanced search with multiple criteria |
| `get_unread_count` | Quick unread count per account |
| `list_accounts` | List all configured Mail accounts |
| `get_recent_emails` | Recent emails from specific account |
| `list_mailboxes` | List folder structure with message counts |
| `move_email` | Move emails between folders |
| `reply_to_email` | Reply to messages |
| `compose_email` | Send new emails |
| `forward_email` | Forward messages |
| `update_email_status` | Mark read/unread, flag/unflag |
| `manage_trash` | Delete operations (soft/hard delete, empty trash) |
| `get_email_thread` | View conversation threads |
| `manage_drafts` | Draft lifecycle management |
| `list_email_attachments` | List attachments |
| `save_email_attachment` | Download attachments |
| `get_statistics` | Email analytics |
| `export_emails` | Export to TXT/HTML |
| `search_by_sender` | Find all emails from a specific sender |
| `search_all_accounts` | Search across all accounts and mailboxes |
| `search_email_content` | Deep search within email body content |
| `get_newsletters` | Find newsletter and subscription emails |
| `get_recent_from_sender` | Get recent emails from a specific sender |

## Configuration

### Email Preferences (Optional)

You can configure personal email preferences that will be provided to the AI assistant when using email tools. This helps Claude understand your preferred email accounts, defaults, and workflow.

**MCP Bundle Installation (.mcpb):**

When installing via the .mcpb bundle, you can set preferences through Claude Desktop:
1. Open Claude Desktop settings
2. Navigate to **Developer > MCP Servers**
3. Click on the **Apple Mail MCP** server
4. Configure **Email Preferences** field

**Example preferences:**
```
Default to BCG account, show max 50 emails, prefer Archive and Projects folders
```

**Manual Installation:**

Add the `env` section to your `claude_desktop_config.json`:

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

**What to include in preferences:**
- Default email account name (e.g., "BCG", "Gmail", "Personal")
- Preferred maximum email results
- Frequently used mailboxes/folders
- Any workflow preferences

These preferences are automatically injected into every tool's description, helping Claude make better decisions aligned with your workflow.

### Safety Limits

Several operations include safety limits to prevent accidental bulk actions:
- `update_email_status`: Default max 10 updates
- `manage_trash`: Default max 5 deletions
- `move_email`: Default max 1 move

These limits can be adjusted via function parameters when needed.

## Permissions

On first use, macOS will prompt for permissions:

1. **Mail.app Control**: Required to automate Mail operations
2. **Mail Data Access**: Required to read email content

Grant both permissions in **System Settings > Privacy & Security > Automation** for full functionality.

## Technical Details

- **Framework**: [FastMCP](https://github.com/jlowin/fastmcp) - Python MCP server framework
- **Automation**: AppleScript for Mail.app interaction
- **Platform**: macOS only (requires Apple Mail)
- **Python**: 3.7+

## Project Structure

```
apple-mail-mcp/
├── apple_mail_mcp.py              # Main MCP server
├── requirements.txt               # Python dependencies
├── README.md                      # This file
├── LICENSE                        # MIT License
├── CHANGELOG.md                   # Version history
├── claude_desktop_config_example.json  # Configuration example
├── apple-mail-mcpb/
│   ├── manifest.json              # MCP Bundle metadata
│   └── build-mcpb.sh             # Bundle build script
└── skill-email-management/        # 🎓 Email Management Expert Skill
    ├── README.md                  # Skill installation & usage guide
    ├── SKILL.md                   # Core workflows & expertise
    ├── examples/                  # Workflow examples
    │   ├── inbox-zero-workflow.md
    │   ├── email-triage.md
    │   └── folder-organization.md
    └── templates/                 # Reusable patterns
        ├── common-workflows.md
        └── search-patterns.md
```

## Troubleshooting

### Mail.app Not Responding
- Ensure Mail.app is running
- Check that permissions are granted in System Settings
- Restart Mail.app and Claude Desktop

### Slow Performance
- Fetching email content is slower than metadata
- Use `include_content: false` when content preview isn't needed
- Reduce `max_results` for large searches

### Mailbox Not Found
- Use exact folder names as they appear in Mail.app
- For nested folders, use "/" separator: `"Projects/Amplify Impact"`
- Some accounts (Exchange) may use different mailbox names

### Permission Errors
```bash
# Grant permissions via System Settings
System Settings > Privacy & Security > Automation > [Your Terminal/Claude]
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Roadmap

Recent additions:
- [x] ✨ Email Management Expert Skill with workflows and best practices (v1.0.0)

Future enhancements under consideration:
- [ ] Smart mailbox support
- [ ] Rule/filter management
- [ ] Email template system
- [ ] Bulk operations improvements
- [ ] Enhanced search operators
- [ ] Multi-account operations

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built with [FastMCP](https://github.com/jlowin/fastmcp) by Jeremiah Lowin
- Inspired by the [Model Context Protocol](https://modelcontextprotocol.io) specification
- Thanks to Anthropic for Claude Desktop, MCP support, and [Claude Code Skills](https://docs.claude.com/en/docs/claude-code/skills)
- Email Management Expert Skill demonstrates best practices for combining MCPs with Skills

## Support

- **Issues**: [GitHub Issues](https://github.com/patrickfreyer/apple-mail-mcp/issues)
- **Discussions**: [GitHub Discussions](https://github.com/patrickfreyer/apple-mail-mcp/discussions)

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history and release notes.

---

Made with ❤️ for the Claude Desktop community

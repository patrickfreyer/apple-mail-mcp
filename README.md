# Apple Mail MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.7+](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io)

A comprehensive Model Context Protocol (MCP) server that provides AI assistants with natural language access to Apple Mail. Built with [FastMCP](https://github.com/jlowin/fastmcp), this server enables reading, searching, organizing, composing, and managing emails directly through Claude Desktop or other MCP-compatible clients.

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

The MCP server provides 20 tools:

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

## Configuration

### No Configuration Required!
The MCP server automatically uses the accounts configured in your Apple Mail app. No additional setup or API keys needed.

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
└── apple-mail-mcpb/
    ├── manifest.json              # MCP Bundle metadata
    └── build-mcpb.sh             # Bundle build script
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
- Thanks to Anthropic for Claude Desktop and MCP support

## Support

- **Issues**: [GitHub Issues](https://github.com/patrickfreyer/apple-mail-mcp/issues)
- **Discussions**: [GitHub Discussions](https://github.com/patrickfreyer/apple-mail-mcp/discussions)

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history and release notes.

---

Made with ❤️ for the Claude Desktop community

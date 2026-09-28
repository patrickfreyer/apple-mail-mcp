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

1. Download the latest `apple-mail-mcp-vX.Y.Z.mcpb` from [Releases](https://github.com/patrickfreyer/apple-mail-mcp/releases)
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

## Tools (22)

### Reading & Search
| Tool | Description |
|------|-------------|
| `get_inbox_overview` | Dashboard with unread counts, folders, and recent emails |
| `list_inbox_emails` | List emails with account/read-status filtering and optional content preview |
| `get_mailbox_unread_counts` | Unread counts per mailbox or per-account summary |
| `list_accounts` | List all configured Mail accounts |
| `search_emails` | Unified search — subject, sender, body text, dates, attachments, flag status/color, cross-account |
| `get_email_thread` | Conversation thread view |

### Organization
| Tool | Description |
|------|-------------|
| `list_mailboxes` | Folder hierarchy with message counts |
| `create_mailbox` | Create new mailboxes (supports nested paths) |
| `move_email` | Move/archive emails with filters (subject, sender, date, read status, dry-run) |
| `update_email_status` | Mark read/unread, flag/unflag (optional flag color) — by filters or message IDs |
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

Pass `--read-only` to block delivery. Nothing leaves the machine: `compose_email` and `reply_to_email` refuse `mode="send"`, `manage_drafts` refuses `action="send"`, and `forward_email` is removed entirely because it has no non-sending mode.

The composing tools stay registered so that `mode="draft"` and `mode="open"` keep working. Those never deliver anything, and they are the only place in the compose surface that supports `attachments` — `manage_drafts` and `create_rich_email_draft` cannot attach files.

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

For a formatted message that has to land in Drafts and stay sendable, pass `body_html` to
`compose_email` (`mode="draft"`, `"send"` or `"open"`). Mail receives the markup through its
`html content` property, so headings, lists, links, inline colours and non-ASCII text arrive
verbatim, and Mail attaches your real signature.

`create_rich_email_draft` is the alternative when you want the message as a file: it writes an
unsent `.eml` with multipart plain-text + HTML bodies and opens it in Mail. Note that Mail opens
a `.eml` as a read-only viewer, so it can never be saved into Drafts — use `compose_email` for
that.

## Known Mail.app limitations

These are Mail's behaviour, not this server's. They are listed here because they are visible in
the messages it produces and there is no way around them from AppleScript.

| Behaviour | Effect | Why it is not fixed here |
|---|---|---|
| macOS 15+ wraps every AppleScript-supplied body in `<div class="Apple-Mail-URLShareWrapperClass"><blockquote type="cite">` | Recipients whose client ignores the wrapper's inline `inherit` styles (Outlook's Word engine) see the message indented; clients that collapse `type="cite"` (Gmail) may hide it behind a "…" toggle | The wrapper is added by Mail after the body is set. All four routes produce it identically: a `content` property, a later `set content`, `set html content`, and a GUI paste into a scripted compose window. Nothing in this package writes it, and no ordering avoids it. The server does make sure the wrapper never *stacks* when a draft is edited repeatedly. |
| Adding an attachment re-renders the body through Mail's editor | HTML formatting on a message with attachments is flattened to plain font runs | Setting the body after the attachment drops the attachment instead. The tools say so in their output rather than letting you find out from the sent mail. |
| `close <message> saving no` does not always discard the message | An abandoned compose object can stay in Drafts | Mail's own scripting behaviour |

## Email Management Skill

A companion [Claude Code Skill](plugin/skills/email-management/) is included that teaches Claude expert email workflows (Inbox Zero, daily triage, folder organization). When installed as a plugin, the skill is loaded automatically. For standalone MCP installs, copy it manually:

```bash
cp -r plugin/skills/email-management ~/.claude/skills/email-management
```

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
| Rich draft shows raw HTML | Pass the markup as `body_html` to `compose_email`, not as plain `body` / `manage_drafts` content |
| Message looks quoted or indented at the recipient | Mail's share wrapper, see [Known Mail.app limitations](#known-mailapp-limitations) |
| Formatting lost on a message with attachments | Mail re-renders the body when a file is attached, see [Known Mail.app limitations](#known-mailapp-limitations) |

## Project Structure

```
apple-mail-mcp/
├── .claude-plugin/
│   └── marketplace.json       # Marketplace manifest (for plugin distribution)
├── plugin/                    # Claude Code plugin
│   ├── .claude-plugin/
│   │   └── plugin.json        # Plugin manifest
│   ├── skills/                # Email Management Expert skill (also invocable as /email-management)
│   ├── apple_mail_mcp/        # Python MCP server package (24 tools)
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

## Releasing

Follow these steps when cutting a new release to keep all version strings in sync:

1. Bump `__version__` in `plugin/apple_mail_mcp/__init__.py` to the new version.
2. Update `apple-mail-mcpb/manifest.json` (`"version"` field) to match.
3. Update `pyproject.toml` (`version = ...` under `[project]`) to match.
4. Update both version fields in `server.json` (`"version"` and `"packages"[0]["version"]`) to match.
5. Run `python3 scripts/check_versions.py` — it must print **OK** before you proceed.
6. Commit, tag, and push: `git tag vX.Y.Z && git push origin vX.Y.Z`.
7. Create a GitHub release from the tag.
8. Build and publish to PyPI: `python -m build && twine upload dist/*` (requires PyPI credentials).

> The test suite also enforces version consistency (`tests/test_version_consistency.py`), so any CI run on a branch with mismatched versions will fail fast.

## License

MIT -- see [LICENSE](LICENSE).

## Links

- [Changelog](CHANGELOG.md)
- [Issues](https://github.com/patrickfreyer/apple-mail-mcp/issues)
- [Discussions](https://github.com/patrickfreyer/apple-mail-mcp/discussions)
- [FastMCP](https://github.com/jlowin/fastmcp)
- [Model Context Protocol](https://modelcontextprotocol.io)

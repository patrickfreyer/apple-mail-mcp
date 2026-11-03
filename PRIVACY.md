# Privacy Policy

_Last updated: 2026-11-02_

Apple Mail MCP (`mcp-apple-mail`) is an open-source MCP server that runs
entirely on your Mac. It has no backend, no accounts and no analytics.

## What it accesses

- **Your Apple Mail data**, through Mail.app's AppleScript interface: account
  names and addresses, mailboxes, message headers, bodies and attachments.
  It reads only what a tool call asks for.
- **Files you name**: attachments you save, emails you export and rich drafts
  you create are written to the paths you give. A path guard blocks writes to
  sensitive locations (dotfiles, SSH keys, launch agents and similar).
- **One lock file** at
  `~/Library/Application Support/apple-mail-mcp/mail_automation.lock`, used
  to keep Mail.app automation calls from overlapping. It holds no mail data.
- **Optional preferences** you set in the `USER_EMAIL_PREFERENCES`
  environment variable, passed to your AI assistant with tool results.

## Where data goes

- The server itself makes **no network requests** and sends nothing to the
  author or any third party.
- Tool results are returned to the **MCP client you run** (for example
  Claude Code, Claude Desktop or Codex). That client may send them to its AI
  model provider under that provider's own privacy policy.
- Email leaves your Mac only when a tool sends it on your behalf
  (`compose_email`, `reply_to_email`, `forward_email`, `manage_drafts` with
  `send`), through your own Mail.app account, to the recipients you set.
  `synchronize_account` asks Mail.app to check your own mail server.
  Starting the server with `--read-only` disables sending.

## Retention

The server stores no mail data. Nothing is kept between calls apart from
the lock file and any files you explicitly save or export.

## Your control

Mail.app access requires your approval in **System Settings > Privacy &
Security > Automation**, and you can revoke it there at any time. Removing
the plugin or server stops all access.

## Contact

Questions or concerns: open an issue at
<https://github.com/patrickfreyer/apple-mail-mcp/issues>.

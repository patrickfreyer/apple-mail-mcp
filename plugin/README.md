# Apple Mail MCP plugin

Lets your AI assistant work with Apple Mail on your Mac: search and read
email, triage the inbox, draft and send replies, organize mailboxes, save
attachments and analyze mail. It includes 28 MCP tools and an Email
Management skill (also available as `/email-management`).

## Requirements

- macOS with Apple Mail set up and at least one account
- [uv](https://docs.astral.sh/uv/) (provides `uvx`)
- On first use, approve the Automation prompt so the server can control Mail.app

## What it runs

The plugin starts one local MCP server over stdio:

```
uvx mcp-apple-mail==3.4.0
```

On first launch `uvx` downloads that exact, pinned version of
[`mcp-apple-mail`](https://pypi.org/project/mcp-apple-mail/) and its
dependencies from PyPI. After that, the server runs on your Mac and talks
only to Mail.app through AppleScript. It makes no network requests of its
own. Email leaves your Mac only when you ask a tool to send it.

## Safety

- Every tool is labelled read-only, local write, or sends mail (MCP
  `readOnlyHint` / `destructiveHint` / `openWorldHint`), so your client can
  ask before anything irreversible.
- Bulk and destructive tools need explicit filters, and emptying the trash
  needs explicit confirmation.
- File-writing tools refuse sensitive paths (dotfiles, SSH keys, launch agents).

## Privacy

See the [Privacy Policy](https://github.com/patrickfreyer/apple-mail-mcp/blob/main/PRIVACY.md).
No data is collected by the author.

## Docs and support

Full tool reference, configuration and troubleshooting:
<https://github.com/patrickfreyer/apple-mail-mcp>. Report issues at
<https://github.com/patrickfreyer/apple-mail-mcp/issues>.

## License

MIT, see [LICENSE](LICENSE).

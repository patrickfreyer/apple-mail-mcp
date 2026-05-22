# Phase 3 — MCP Tool Annotation Matrix

**Server:** `mcp.server.fastmcp.FastMCP` (MCP SDK 1.27.1 via `fastmcp==3.1.0`)  
**API:** `@mcp.tool(annotations=ToolAnnotations(...))` from `mcp.types`  
**Tool count:** 27 (`rg '^@mcp\.tool' plugin/apple_mail_mcp/tools/*.py | wc -l`)

Legend: T=true, F=false. Multi-action tools annotated for worst-case capability.

| Tool | Module | readOnlyHint | destructiveHint | idempotentHint | openWorldHint | Notes |
|------|--------|:------------:|:---------------:|:--------------:|:-------------:|-------|
| list_accounts | inbox | T | F | T | T | Pilot annotated |
| list_account_addresses | inbox | T | F | T | T | |
| list_mailboxes | inbox | T | F | T | T | |
| list_inbox_emails | inbox | T | F | T | T | |
| get_mailbox_unread_counts | inbox | T | F | T | T | |
| get_inbox_overview | inbox | T | F | T | T | |
| search_emails | search | T | F | T | T | Pilot annotated |
| get_email_by_id | search | T | F | T | T | Pilot annotated |
| get_email_thread | search | T | F | T | T | |
| get_awaiting_reply | smart_inbox | T | F | T | T | |
| get_needs_response | smart_inbox | T | F | T | T | |
| get_top_senders | smart_inbox | T | F | T | T | |
| list_email_attachments | analytics | T | F | T | T | |
| get_statistics | analytics | T | F | T | T | |
| inbox_dashboard | analytics | T | F | T | T | |
| export_emails | analytics | F | F | F | T | Writes files to disk |
| save_email_attachment | manage | F | F | F | T | Saves attachment to path |
| update_email_status | manage | F | F | T | T | Mark read/flag |
| move_email | manage | F | F | F | T | Moves messages |
| manage_trash | manage | F | T | F | T | Trash/delete/empty |
| create_mailbox | manage | F | F | F | T | Creates folder |
| synchronize_account | manage | F | F | T | T | Triggers IMAP sync |
| create_rich_email_draft | compose | F | F | F | T | Creates draft / .eml |
| compose_email | compose | F | T | F | T | Removed in `--read-only` |
| reply_to_email | compose | F | T | F | T | Removed in `--read-only` |
| forward_email | compose | F | T | F | T | Removed in `--read-only` |
| manage_drafts | compose | F | T | F | T | send/delete actions |

## Read-only registry

`--read-only` removes: `compose_email`, `reply_to_email`, `forward_email`  
Source: `plugin/apple_mail_mcp/__main__.py`, `server.SEND_TOOLS`

## Rollout order

1. Pilot (done): `list_accounts`, `search_emails`, `get_email_by_id`
2. Remaining read-only tools (done): inbox, search, smart_inbox, analytics read paths
3. Mutating tools with accurate destructive/idempotent hints (done)
4. JSON normalization (separate Phase 3 track — not started)

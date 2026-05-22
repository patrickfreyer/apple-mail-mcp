# tools/ — MCP tool registrations
All `@mcp.tool` handlers live here; `apple_mail_mcp/__init__.py` imports these six modules (side-effect registration). **27 tools** — verify: `rg '^@mcp\.tool' plugin/apple_mail_mcp/tools/*.py | wc -l`.

## Module map

| Module | # | Purpose / tools |
|--------|---|-----------------|
| `inbox.py` | 6 | Listing & overview: `list_inbox_emails`, `get_mailbox_unread_counts`, `list_accounts`, `list_account_addresses`, `list_mailboxes`, `get_inbox_overview` |
| `search.py` | 3 | Find & fetch: `search_emails`, `get_email_by_id`, `get_email_thread` |
| `compose.py` | 5 | Send & drafts: `create_rich_email_draft`, `compose_email`, `reply_to_email`, `forward_email`, `manage_drafts` |
| `manage.py` | 6 | Move/status/trash/sync: `move_email`, `save_email_attachment`, `update_email_status`, `manage_trash`, `create_mailbox`, `synchronize_account` |
| `analytics.py` | 4 | Stats & export: `list_email_attachments`, `get_statistics`, `export_emails`, `inbox_dashboard` |
| `smart_inbox.py` | 3 | Triage heuristics: `get_awaiting_reply`, `get_needs_response`, `get_top_senders` |

## Add a tool

1. Pick module by domain; add `@mcp.tool(annotations=…)` using presets from `../server.py` (matrix: `tasks/phase-3-annotation-matrix.md`).
2. `@inject_preferences` on user-facing tools; user strings → `core.escape_applescript()`; fan-out → `async` + `asyncio.to_thread`.
3. New file → import in `__init__.py`; bump five version manifests + `apple-mail-mcpb/manifest.json` `tools[]` and advertised tool count.

## Performance (summary)

- Default `recent_days=2.0` (48h); `0` disables. Cap in AppleScript (`whose` + `items 1 thru N`), not Python slicing.
- Pass `timeout` through to `run_applescript`; catch `AppleScriptTimeout` → structured error with account name.
- Mutations: `normalize_message_ids` / `message_ids` for targeted ops. Detail: `docs/CLAUDE-conventions.md`.

## Account scoping

`account: Optional[str] = None` → `server.DEFAULT_MAIL_ACCOUNT`; error if unset. Exceptions: `synchronize_account` (None = all accounts), `inbox_dashboard` (always cross-account). `all_accounts=True` overrides default scoping.

## JSON `output_format`

Normalized: `get_statistics`, `get_inbox_overview`; also `list_inbox_emails`, `list_mailboxes` (`output_format="json"`).

## Related

`../core.py` (bridge), `../server.py` (mcp + annotations), `../../tests/` (mock `run_applescript`), `tasks/phase-3-annotation-matrix.md`.

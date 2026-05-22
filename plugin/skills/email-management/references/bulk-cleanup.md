# Bulk Cleanup Operations

Bulk operations remove or relocate many messages at once. Apple Mail offers no undo for permanent deletes, so this reference exists to keep cleanup safe and reversible.

## Safety Defaults

The MCP server enforces conservative defaults to prevent runaway destructive operations:

| Tool | Default cap | Override parameter |
|------|-------------|--------------------|
| `manage_trash` (move_to_trash, delete_permanent) | 5 messages | `max_deletes=N` |
| `manage_trash` (empty_trash) | hard confirmation required | `confirm=True` |
| `update_email_status` | 10 messages | `max_updates=N` |
| `move_email` | 1 message | `max_moves=N` |

Raise these caps only after a confirming search shows the user exactly which messages will be affected.

## Safe Cleanup Sequence

1. **Identify candidates** with `search_emails()`, narrowed by sender, date range, mailbox, or read status.
2. **Preview the result set** — print sender, subject, and date for the first ten matches. Confirm the count is what the user expects.
3. **Move to Trash first** with `manage_trash(action="move_to_trash", max_deletes=N)`. This is reversible inside Apple Mail.
4. **Verify** by listing the Trash mailbox or re-running the search to confirm zero remaining matches in the source.
5. **Permanent delete only when certain** with `manage_trash(action="delete_permanent")`. Cite the exact count to the user before running.
6. **Empty Trash is the nuclear option.** Run `manage_trash(action="empty_trash", confirm=True)` only after explicit user confirmation.

## Pre-Cleanup Backup

Before deleting a large mailbox, export it: `export_emails(scope="entire_mailbox", mailbox="Archive/2023", format="html")`. The user gets a local copy in case a permanent delete removes something important.

## Common Cleanup Patterns

### Purge old read newsletters

```text
search_emails(sender="newsletter@example.com", read_status="read", recent_days=0)
manage_trash(action="move_to_trash", sender="newsletter@example.com", max_deletes=200)
```

### Archive everything older than 90 days

```text
search_emails(date_to="2025-02-20", read_status="read", recent_days=0)
move_email(to_mailbox="Archive/2025", date_to="2025-02-20", max_moves=500)
```

### Empty a defunct project folder

1. `export_emails(scope="entire_mailbox", mailbox="Projects/OldProject")` for the audit trail.
2. `manage_trash(action="move_to_trash", mailbox="Projects/OldProject", max_deletes=1000)`.
3. Verify, then `manage_trash(action="empty_trash", confirm=True)` if appropriate.

## Confirmation Script

Before any bulk destructive action, restate to the user:

- The exact tool call about to run.
- The expected affected count from the preview search.
- Whether the action is reversible (move_to_trash) or permanent (delete_permanent, empty_trash).

If any of those three are unclear, stop and ask.

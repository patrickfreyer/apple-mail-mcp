---
name: email-management
description: This skill should be used when the user asks to "help me get to inbox zero", "clean up my inbox", "organize my email", "set up folders", "I'm drowning in email", or otherwise wants to triage, organize, or reduce volume in their Apple Mail inbox. Covers daily triage routines, folder structure design, bulk cleanup with safety limits, and Inbox Zero methodology using the apple-mail MCP tools (get_inbox_overview, search_emails, move_email, update_email_status, manage_trash, get_statistics). Do NOT use for composing or replying to a specific message (see email-drafting), one-off triage runs over a specific time window (see inbox-triage), or attachment handling (see email-attachments).
---

# Email Management

Sustained inbox organization for Apple Mail: daily triage routines, folder structure design, bulk cleanup, and Inbox Zero methodology. This skill is about ongoing habits and structural cleanup, not one-off message actions.

## When To Use This Skill

Use when the request is about reducing inbox volume, designing or reshaping a folder layout, building a sustainable triage habit, or running a safe bulk cleanup.

Do NOT use for:

- Composing or replying to a specific message — see `email-drafting`.
- A one-off pass over the last N hours of mail — see `inbox-triage`.
- Downloading or saving attachments — see `email-attachments`.

For finding a single specific email, call `search_emails()` directly without invoking this skill.

## Performance Defaults To Know

Internalize these before constructing any tool call. The defaults exist to keep AppleScript queries fast on large Exchange inboxes.

- `search_emails` defaults to the last 48 hours on the configured default account. Pass `recent_days=7` or `recent_days=30` to widen, and `recent_days=0` to search the full inbox.
- `list_inbox_emails` defaults to the 50 most-recent emails. Pass `max_emails=0` to disable the cap.
- Cross-account scans cost time on large Exchange inboxes. Pass `all_accounts=True` only when truly needed; otherwise let the `DEFAULT_MAIL_ACCOUNT` environment variable keep things scoped.

When in doubt, run a narrow query first and widen only if results are insufficient.

## Decision Tree

| Request signal | Route to |
|----------------|----------|
| "Help me get to inbox zero" / "clean up my inbox" / "organize email" | This skill |
| "Write an email to..." / "reply to..." / "draft a..." | `email-drafting` |
| "Triage what came in today" / "what needs my attention right now" | `inbox-triage` |
| "Save the attachment from..." | `email-attachments` |
| "Find the email about X" | Call `search_emails()` directly |
| "Delete all emails from..." / "archive everything older than..." | This skill, Cleanup section |

## Destructive Operations — Safety Caps

The MCP server enforces conservative defaults. Confirm with the user before raising any cap.

| Operation | Default cap | When to confirm with user |
|-----------|-------------|---------------------------|
| `manage_trash(action="move_to_trash")` | 5 messages | Any time `max_deletes` exceeds 20 |
| `manage_trash(action="delete_permanent")` | 5 messages | Always — this is irreversible |
| `manage_trash(action="empty_trash")` | hard confirm via `confirm=True` | Always |
| `move_email` | 1 message | Any bulk move (`max_moves` > 10) |
| `update_email_status` | 10 messages | Any bulk update (`max_updates` > 50) |

Pattern: identify candidates with `search_emails()`, preview the count and sample, confirm the user's intent, then run the destructive call with an explicit cap.

## Core Principles

- Start every workflow with `get_inbox_overview()` to understand current state before acting.
- Prefer batch operations with explicit caps over message-by-message changes.
- Treat the inbox as a processing queue, not as storage; archive or delete once a decision is made.
- Search beats sort for most retrieval needs; keep folder structure shallow (two to three levels max).
- Confirm destructive actions before executing, and prefer reversible operations (move to trash) over permanent ones.
- Respect the configured default account; only widen to all accounts when single-account scope is demonstrably incomplete.
- Cite expected counts to the user before any bulk action so they can intervene if a query has matched more than intended.

## Workflow: Daily Inbox Triage

Goal: process inbox to zero or near-zero in 15 to 30 minutes.

1. Get overview: `get_inbox_overview()` to see unread counts, recent messages, and suggested actions.
2. Surface priorities: `search_emails(subject_keyword="urgent")` and variants for "action required", "deadline". Use the default 48-hour window unless the user requests otherwise.
3. Decide per message using the four-option rule: respond, defer, file, or delete.
   - For responses, hand off to the `email-drafting` skill.
   - To defer, flag with `update_email_status(action="flag", subject_keyword="...")`.
   - To file, use `move_email(to_mailbox="...", max_moves=1)`.
   - To delete, use `manage_trash(action="move_to_trash")` with an explicit cap.
4. Mark processed batches read: `update_email_status(action="mark_read", ...)`.
5. End the session by re-running `get_inbox_overview()` to confirm the queue is drained.

Tips:

- Process by sender or topic, not strictly chronologically.
- Apply the 2-minute rule: if a reply is short, do it now rather than deferring.
- Do not organize what can be found later by search.

## Workflow: Weekly Email Organization

Goal: keep folder structure healthy and archive aging messages.

1. Review structure: `list_mailboxes(include_counts=True)`.
2. Identify clutter: mailboxes with more than 1,000 messages or with a high unread ratio.
3. Analyze patterns: `get_statistics(scope="account_overview")` plus `get_top_senders()`. Full guidance lives in `references/analytics.md`.
4. Adjust folders: create or rename mailboxes inside Apple Mail (the MCP cannot create folders via AppleScript reliably; `create_mailbox` works for nested mailboxes but confirm with the user first).
5. Bulk-organize by sender or date:
   - `search_emails(sender="...", recent_days=0)` then `move_email(sender="...", to_mailbox="...", max_moves=N)`.
   - `search_emails(date_to="YYYY-MM-DD", recent_days=0)` then move to an archive folder.
6. Archive read mail older than 30 days into `Archive/<year>`.

Detailed safe bulk operations are documented in `references/bulk-cleanup.md`.

## Workflow: Achieving Inbox Zero

Goal: drain the inbox by processing every message exactly once.

1. Survey: `get_inbox_overview()` and `get_statistics(scope="account_overview")` to size the problem.
2. Process top-down with the five-D framework on each message:
   - Delete: spam, expired notifications — `manage_trash(action="move_to_trash")`.
   - Delegate: forward via the `email-drafting` skill.
   - Defer: flag and move to a "Follow Up" mailbox.
   - Do: respond now if under two minutes (`email-drafting`).
   - File: `move_email(to_mailbox="...")` for reference material.
3. Keep folders sparing: an "Action Required", "Waiting For", and "Reference" trio handles most cases.
4. Maintain daily — Inbox Zero is a habit, not a one-time event.

Mindset:

- Every message needs a decision.
- Touch each message once when possible.
- The inbox is a queue, not an archive.

## Tool Selection Guidelines

| Goal | Tool | Notes |
|------|------|-------|
| Inbox snapshot | `get_inbox_overview()` | Always the first call |
| Full dashboard | `inbox_dashboard()` | Heavier, richer view |
| Find a specific email | `search_emails(subject_keyword="...")` | Defaults to last 48 hours |
| Search by sender | `search_emails(sender="...")` | Same defaults apply |
| Search email bodies | `search_emails(body_text="...", include_content=True)` | Slower; use when subject is unknown |
| Cross-account search | `search_emails(account=None, all_accounts=True)` | Costly on Exchange; use sparingly |
| Recent inbox listing | `list_inbox_emails(max_emails=50)` | Default cap is 50 |
| View a conversation | `get_email_thread(subject_keyword="...")` | See `references/thread-management.md` |
| Move messages | `move_email(..., max_moves=N)` | Default cap is 1 |
| Flag / mark read | `update_email_status(action="...", max_updates=N)` | Default cap is 10 |
| Move to trash / delete | `manage_trash(action="...", max_deletes=N)` | See `references/bulk-cleanup.md` |
| Analytics | `get_statistics()` and `get_top_senders()` | See `references/analytics.md` |
| Export for backup | `export_emails(scope="...", mailbox="...")` | Run before any large delete |
| Sync stale account | `synchronize_account(account="...")` | When recent messages appear missing |

## Common Scenarios

### "I'm overwhelmed by my inbox"

1. Size the problem: `get_inbox_overview()` and `get_statistics(scope="account_overview")`.
2. Identify the worst senders: `get_top_senders(limit=10)`.
3. Adopt the Daily Triage workflow above for 15 to 30 minutes per day.
4. Unsubscribe from non-essential senders identified in step 2.
5. Build the minimum folder structure ("Action Required", "Waiting For", "Reference", "Archive").
6. Aim for sustainable progress — do not attempt a one-shot cleanup of a 10,000-message backlog.

### "I can't find an important email"

1. Start with `search_emails(subject_keyword="...")` on the default account and default 48-hour window.
2. Widen the time window: add `recent_days=30` or `recent_days=0` (full inbox).
3. Widen the scope: add `all_accounts=True` to search every configured account.
4. Search the body: `search_emails(body_text="...", include_content=True, recent_days=0)`.
5. Filter by attachment if relevant: `search_emails(has_attachments=True, ...)`.
6. Check Trash explicitly: `search_emails(mailbox="Trash", recent_days=0, ...)`.

### "I want to organize emails by project"

1. Review current layout: `list_mailboxes(include_counts=True)`.
2. Create project folders in Apple Mail (or via `create_mailbox` if the user confirms).
3. Find project messages: `search_emails(subject_keyword="ProjectName", recent_days=0)`.
4. Bulk move: `move_email(subject_keyword="ProjectName", to_mailbox="Projects/ProjectName", max_moves=50)` after previewing.
5. Add sender-based moves for team members on the same project.

### "I need to follow up on emails"

1. Flag the message: `update_email_status(action="flag", subject_keyword="...", max_updates=1)`.
2. Optionally move flagged items into a dedicated "Follow Up" mailbox for visibility.
3. Schedule a recurring weekly review of the flagged set: `search_emails(flagged=True, recent_days=0)`.
4. Clear the flag once handled: `update_email_status(action="unflag", subject_keyword="...")`.

### "Too many emails from one sender"

1. Confirm volume: `get_statistics(scope="sender_stats", sender="...")`.
2. Find the messages: `search_emails(sender="...", recent_days=0)`.
3. If unwanted, run the cleanup sequence from `references/bulk-cleanup.md`.
4. If wanted but noisy, create a dedicated folder and bulk-move with `move_email(sender="...", to_mailbox="...", max_moves=N)`.
5. If the sender is a newsletter, surface it via `get_top_senders()` and unsubscribe in Apple Mail.

## Additional Resources

### Reference Files

- `references/analytics.md` — Email analytics, statistics scopes, and using `get_top_senders` for noise diagnosis.
- `references/bulk-cleanup.md` — Safe bulk cleanup operations with confirmation patterns.
- `references/thread-management.md` — Working with reconstructed email threads.

### Examples

The `examples/` directory contains worked walkthroughs:

- `examples/email-triage.md`
- `examples/folder-organization.md`
- `examples/inbox-zero-workflow.md`

### Templates

The `templates/` directory holds reusable query and workflow templates referenced by the examples.

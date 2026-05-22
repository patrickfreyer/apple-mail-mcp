---
name: inbox-triage
description: This skill should be used when the user asks to "check my email", "what came in today", "what needs my attention", "morning email scan", "triage my inbox", "anything urgent in my mail", or wants a fast 5–10 minute read-only pass over Apple Mail without full inbox-zero cleanup. Uses get_inbox_overview, get_needs_response, get_awaiting_reply, list_inbox_emails, and get_email_by_id. Do NOT use for deep folder reorganization or bulk cleanup (see email-management) or composing replies (use compose MCP tools).
---

# Inbox Triage

Fast, read-first email check for Apple Mail — what arrived, what needs a reply, what you're still waiting on. Target **5–10 minutes**, not inbox zero.

## When To Use

| User says | Use this skill |
|-----------|----------------|
| "Check my email" / "what came in today" | Yes |
| "What needs my attention" / "anything urgent" | Yes |
| "Morning email scan" / "quick triage" | Yes |
| "Clean up my inbox" / "inbox zero" | No → `email-management` |
| "Write / reply to this email" | No → compose MCP tools (`reply_to_email`, `compose_email`, `create_rich_email_draft`, `manage_drafts`) |

## Setup (once)

Set **`DEFAULT_MAIL_ACCOUNT`** to the user's primary Mail account name (e.g. `Work`, `cayman@agenticassets.ai`). Without it, tools may fan out across every account and run slowly.

For agent testing, run the MCP server with **`--draft-safe`** so send tools stay blocked.

## Daily loop (5–10 min)

Run on the **configured default account** unless the user names another.

### 1. Snapshot (30–60s)

```
get_inbox_overview(
  output_format="compact",
  include_mailboxes=false,
  include_recent=true,
  include_suggestions=false
)
```

Note unread totals and recent subjects. Do not open every message yet.

### 2. Needs your reply (1–3 min)

```
get_needs_response(days_back=2, max_results=10)
```

Subject-only detection is the default (fast). Use `scan_body=True` only when the user asks to hunt question marks in bodies.

Present as a short prioritized list: subject, sender, age, priority hint.

### 3. Waiting on others (optional, ~1 min)

```
get_awaiting_reply(days_back=7, max_results=5)
```

Use when the user cares about follow-ups they already sent.

### 4. Scan recent inbox (1–2 min)

```
list_inbox_emails(max_emails=25, include_content=false, output_format="json")
```

Skim subjects. Flag obvious P0 keywords (urgent, deadline, outage) with `search_emails` only if overview/needs-response missed them.

### 5. Drill-down by exact id (when needed)

After search or list returns a `message_id`, fetch the full message without re-searching:

```
get_email_by_id(message_id="12345", include_content=true, output_format="json")
```

Repo CLI equivalent: `apple-mail show --id 12345 --json`.

## Output format for the user

Summarize in plain language:

1. **Needs reply** — count + top 3 subjects
2. **Waiting on others** — count + top 2 if any
3. **Notable recent** — anything flagged/urgent from overview
4. **Suggested next action** — read one message, reply, defer, or schedule full cleanup

Do not bulk-move or trash during triage unless the user explicitly asks.

## Performance rules

- Keep `days_back` small (2 for needs-response, 7 for awaiting-reply).
- Avoid `get_statistics(account_overview)` in the daily loop — use weekly in `email-management`.
- Avoid `all_accounts=True` unless the user has no default account and wants every account.
- Prefer `list_mailboxes(include_counts=false)` when listing folders.

## Related skills

- **`email-management`** — folder design, bulk cleanup, inbox zero sessions
- **Compose MCP tools** — `reply_to_email`, `compose_email`, `forward_email`, `create_rich_email_draft`, `manage_drafts` after triage identifies a message

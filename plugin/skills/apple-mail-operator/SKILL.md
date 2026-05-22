---
name: apple-mail-operator
description: This skill should be used when the user asks "how does this Mail MCP work", "which tool should I use", "why is Mail slow", "set up Mail for the assistant", "list my accounts/mailboxes", "find an email quickly", or needs safe read/search navigation in Apple Mail with the MCP. Uses list_accounts, list_mailboxes, get_inbox_overview, list_inbox_emails, search_emails, get_email_by_id, and get_email_thread. Do NOT use for sustained inbox-zero programs (see email-management), a 5–10 minute triage ritual (see inbox-triage), or drafting mail (see email-drafting).
---

# Apple Mail Operator

Operational guide for using the Apple Mail MCP safely and quickly. Focus on bootstrap, selecting the correct tool per intent, avoiding slow cross-account scans, and understanding draft-safe versus send-capable setups.

## When To Use This Skill

| Request signal | Use this skill |
|----------------|----------------|
| "How do I configure this?", "What's DEFAULT_MAIL_ACCOUNT?" | Yes |
| "List accounts / aliases / folders" | Yes |
| "How do I read or find a thread without moving mail?" | Yes |
| Performance or timeout troubleshooting | Yes |
| "Clean my inbox forever" / Inbox Zero program | No → `email-management` |
| "Quick scan what needs reply today" | No → `inbox-triage` |
| Draft or send a message | No → `email-drafting` |

## Bootstrap Checklist

1. Confirm Mail.app is running and macOS Automation + Mail Data Access are granted for the host app (terminal or IDE running the MCP).
2. Prefer setting **`DEFAULT_MAIL_ACCOUNT`** so tools default to one account instead of fanning out across every mailbox.
3. Default plugin installs run **`--draft-safe`**: drafts and open-for-review workflows work; **`mode="send"`** paths error until the server is reconfigured intentionally.
4. Set optional **`USER_EMAIL_PREFERENCES`** for stable tone and workflow hints; those preferences surface on preference-aware tool docstrings plus the **`email-style-profile`** skill.

## Decision Tree — Read And Navigate

| Goal | Primary tool chain |
|------|-------------------|
| See configured accounts | `list_accounts()` |
| See outbound identities | `list_account_addresses(account="...")` |
| Snapshot unread + recent hints | `get_inbox_overview()` — start compact `output_format`, avoid heavy dashboards during debugging |
| Page recent inbox bodies | `list_inbox_emails(max_emails=..., include_content=false|true)` |
| Locate a needle | Narrow `search_emails(...)` (`recent_days=2` unless user insists on widening) → `get_email_by_id(message_id=...)` |
| Conversation context | `get_email_thread(...)` instead of chained subject guesses |
| Mailbox map | `list_mailboxes(include_counts=true)` |
| Idle mail fetch | `synchronize_account()` when results look stale |

## Performance Rules

- Run **narrow** queries first (`recent_days` small, explicit `account=`, `include_content=false`, tight `limit`).
- Reserve `all_accounts=True` / cross-account scans for explicit user requests — large Exchange profiles may time out; partial JSON with `errors` is expected behavior.
- After `list_inbox_emails` or `search_emails` returns `message_id`, always drill with `get_email_by_id` rather than fuzzy re-search.

## Operator Safety Patterns

| Need | Guidance |
|------|----------|
| No accidental sends | Keep `--draft-safe`; require explicit user confirmation before any send attempt |
| Quiet bulk drafts | Default `mode="draft"` on compose tools; do not leave unsaved compose windows |
| Review each draft in Mail | Use `mode="open"` (saves first, then leaves window open); for rich `.eml`, `review_in_mail=True` |
| Reply to a known message | Pass `message_id` from search/list; avoid `subject_keyword` when an id is already known |
| Read-only auditing | Mention `--read-only` server flag — removes send-facing compose registrations |
| Destructive moves/deletes | Defer to `email-archive-cleanup` or `email-management`; never bury trash/delete actions inside troubleshooting |

## Optional Dashboards And UI

Use `inbox_dashboard()` only when the client supports MCP UI hosting and the session needs a richer explorer view; it is heavier than `get_inbox_overview()` for routine operator tasks.

## Additional Resources

- Root README → Configuration section for **`DEFAULT_MAIL_ACCOUNT`**, **`USER_EMAIL_PREFERENCES`**, **`--draft-safe`**, **`--read-only`**.
- Sibling **`inbox-triage`** for scripted daily queues.
- Sibling **`email-management`** when the objective is habitual processing and bulk transformation, not tooling orientation.

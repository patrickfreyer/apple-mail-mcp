---
name: email-drafting
description: This skill should be used when the user asks to "draft an email", "reply to this message", "forward the thread", "write a weekly update email", or needs HTML-rich drafts saved to Mail Drafts with optional explicit open-for-review behavior. Uses compose_email, reply_to_email, forward_email, create_rich_email_draft, manage_drafts, plus get_email_by_id and search_emails when a message handle is missing. Do NOT use for daily inbox scanning (see inbox-triage), Mail MCP setup errors (apple-mail-operator), voice capture before writing (email-style-profile first), folder taxonomy only (mailbox-taxonomy), Mail rule prose (mail-rules-advisor), staged bulk moves (email-archive-cleanup), or attachment extraction (email-attachments).
---

# Email Drafting

Compose-first workflows against Apple Mail. Default draft workflows save quietly to Drafts and should not leave fresh compose windows open; sends require explicit confirmation and are blocked when the MCP runs `--draft-safe` (recommended for shared agents).

## When To Use This Skill

| Request signal | Use this skill |
|----------------|----------------|
| "Reply / forward / write / draft" | Yes |
| "Make a nicer HTML newsletter-style draft" | Yes |
| Manage open drafts (`list/send/delete`) with guardrails | Yes |
| Bulk archive or reorganize folders | No → `email-archive-cleanup` |
| Decide folder strategy | No → `mailbox-taxonomy` |

## Preconditions

1. Know the **`account`** (defaults follow `DEFAULT_MAIL_ACCOUNT`).
2. For replies/forwards, use the Mail **`message_id`** returned by `search_emails`, `list_inbox_emails`, `get_email_by_id`, or thread tools whenever available. Do not switch to `subject_keyword` just because the subject is visible; subject lookup is only for cases where no message id is available.
3. Load **`USER_EMAIL_PREFERENCES`** plus any capture from **`email-style-profile`** before writing content.

## Tool Selection Pattern

| Situation | Tool | Notes |
|-----------|------|-------|
| New outbound mail | `compose_email` | Prefer quiet `mode="draft"` unless user explicitly authorizes send and server permits |
| Structured reply context | `reply_to_email` | After search/list returns a Mail `message_id`, pass `message_id=...`; subject lookup is fallback only |
| Share thread outward | `forward_email` | After search/list returns a Mail `message_id`, pass `message_id=...`; subject lookup is fallback only |
| Marketing / HTML layout | `create_rich_email_draft` | Produces multipart `.eml`, saves to Drafts by default; safest for visuals |
| Low-level draft listing / CRUD | `manage_drafts` | Respect cap defaults; never batch-delete without confirming folder scope |

Always restate recipients, subject line, and whether the user intends **Draft vs Review vs Send** before running a mutate call. Use `mode="open"` only when the user explicitly wants the saved-open review mode; open-for-review paths save first so closing immediately should not trigger Mail's Save/Don't Save prompt.

## Safety And Compliance

| Risk | Mitigation |
|------|-------------|
| Accidental dispatch | Maintain `--draft-safe`; disallow `mode="send"` silently |
| Over-broad lookups | Narrow `recent_days`, provide `subject_keyword` anchors, escalate to explicit `message_id` |
| Sensitive content | Warn before quoting full threads into new messages |
| Signature alignment | Prefer matching recent Sent-tone via `email-style-profile` routines |

### Draft-Safe And Read-Only Modes Reminder

- **`--draft-safe`**: Sending via compose tools or `manage_drafts(action="send")` returns structured errors — treat send requests as drafting tasks until configuration changes.
- **`--read-only`**: Compose send tools unregister entirely; drafts are still workable where permitted.

## Rich Draft Guidance

Choose `create_rich_email_draft` when plain-text AppleScript insertion would show escaped HTML artifacts. By default it writes the `.eml`, opens Mail only long enough to save the draft, then closes the fresh compose window. Use `open_in_mail=False` when the caller only needs the `.eml` artifact, and use `review_in_mail=True` only when the user explicitly wants Mail left open after the draft has been saved.

## Post-Draft Verification

Summarize artifacts for the operator:

1. Mailbox + identifiers (`message_id` if surfaced).
2. Draft location and whether Mail was left open for explicit review.
3. Next actions (edit, attachments, approvals).

## Related Skills

- **`email-style-profile`** — learn voice from Sent mail samples.
- **`email-attachments`** — after drafting, optionally attach binaries with validated filesystem paths (`compose_*` attachments parameters).
- **`apple-mail-operator`** — if tools error on account scope or timeouts, fix infra before rewriting prose.

---
name: email-drafting
description: This skill should be used when the user asks to "draft an email", "reply to this message", "forward the thread", "write a weekly update email", "leave the draft open for review", or needs HTML-rich drafts saved quietly to Mail Drafts (mode="draft" default; mode="open" or review_in_mail=True only when explicitly requested). Uses compose_email, reply_to_email, forward_email, create_rich_email_draft, manage_drafts, plus get_email_by_id and search_emails when a message handle is missing; applies DEFAULT_MAIL_SIGNATURE when configured unless include_signature=False. Do NOT use for daily inbox scanning (see inbox-triage), Mail MCP setup errors (apple-mail-operator), voice capture before writing (email-style-profile first), folder taxonomy only (mailbox-taxonomy), Mail rule prose (mail-rules-advisor), staged bulk moves (email-archive-cleanup), or attachment extraction (email-attachments).
---

# Email Drafting

Compose-first workflows against Apple Mail. Default plugin installs run **`--draft-safe`**: compose tools default to quiet `mode="draft"` (no leftover compose windows), and `mode="send"` returns a structured error until the server is reconfigured. When send is allowed, still confirm intent with the user before calling `mode="send"` or `manage_drafts(action="send")`.

## When To Use This Skill

| Request signal | Use this skill |
|----------------|----------------|
| "Reply / forward / write / draft" | Yes |
| "Make a nicer HTML newsletter-style draft" | Yes |
| Manage open drafts (`list/send/delete`) with guardrails | Yes |
| Bulk archive or reorganize folders | No → `email-archive-cleanup` |
| Decide folder strategy | No → `mailbox-taxonomy` |

## Preconditions

1. Know the **`account`** (defaults follow `DEFAULT_MAIL_ACCOUNT`) and signature intent. Compose/reply/forward default to **`include_signature=True`**, which applies **`DEFAULT_MAIL_SIGNATURE`** when that env var is set; when unset, no signature is applied. Pass `include_signature=False` to suppress, or `signature_name` to override the default for one call.
2. For replies/forwards, use the Mail **`message_id`** returned by `search_emails`, `list_inbox_emails`, `get_email_by_id`, or thread tools whenever available. Do not switch to `subject_keyword` just because the subject is visible; subject lookup is only for cases where no message id is available.
3. Load **`USER_EMAIL_PREFERENCES`** plus any capture from **`email-style-profile`** before writing content.

## Tool Selection Pattern

| Situation | Tool | Notes |
|-----------|------|-------|
| New outbound mail | `compose_email` | Default `mode="draft"`; use `mode="open"` only for explicit saved-open review; `mode="send"` blocked under `--draft-safe` |
| Structured reply context | `reply_to_email` | Default quiet draft (`send=False` / `mode="draft"`); pass `message_id=...` from search/list; `subject_keyword` is fallback only |
| Share thread outward | `forward_email` | Default `mode="draft"`; pass `message_id=...` from search/list; `subject_keyword` is fallback only |
| Marketing / HTML layout | `create_rich_email_draft` | Produces multipart `.eml`, saves to Drafts by default; use `review_in_mail=True` for saved-open review; no Mail signature params — use plain compose tools when a named signature is required |
| Low-level draft listing / CRUD | `manage_drafts` | Respect cap defaults; never batch-delete without confirming folder scope |

Always restate recipients, subject line, **Draft vs Review vs Send**, and signature intent (named signature or no signature) before running a mutate call. Use `mode="open"` only when the user explicitly wants the saved-open review mode; open-for-review paths save first so closing immediately should not trigger Mail's Save/Don't Save prompt.

## Safety And Compliance

| Risk | Mitigation |
|------|-------------|
| Accidental dispatch | Maintain `--draft-safe`; disallow `mode="send"` silently |
| Over-broad lookups | Prefer `message_id` from search/list; when id is unknown, narrow `recent_days` and anchor `subject_keyword` |
| Sensitive content | Warn before quoting full threads into new messages |
| Signature alignment | Prefer matching recent Sent-tone via `email-style-profile` routines |

### Draft-Safe And Read-Only Modes Reminder

- **`--draft-safe`** (default plugin install): `compose_email`, `reply_to_email`, and `forward_email` stay on quiet `mode="draft"` unless the user explicitly requests `mode="open"`; `mode="send"` and `manage_drafts(action="send")` return structured errors — treat send requests as drafting tasks until configuration changes.
- **`--read-only`**: Unregisters `compose_email`, `reply_to_email`, and `forward_email`; also enables draft-safe send blocking for `manage_drafts(action="send")`. `create_rich_email_draft` and `manage_drafts` remain for draft workflows where permitted.

## Rich Draft Guidance

Choose `create_rich_email_draft` when plain-text AppleScript insertion would show escaped HTML artifacts. With a nonblank subject and default `open_in_mail=True`, it writes the `.eml`, opens Mail only long enough to save the draft, then closes the fresh compose window. Blank subject → `.eml` only (Mail not opened). Use `open_in_mail=False` when the caller only needs the `.eml` artifact, and use `review_in_mail=True` only when the user explicitly wants Mail left open after the draft has been saved.

## Post-Draft Verification

Summarize artifacts for the operator:

1. Mailbox + identifiers (`message_id` if surfaced).
2. Draft location and whether Mail was left open for explicit review.
3. Next actions (edit, attachments, approvals).

## Related Skills

- **`email-style-profile`** — learn voice from Sent mail samples.
- **`email-attachments`** — after drafting, optionally attach binaries with validated filesystem paths (`compose_*` attachments parameters).
- **`apple-mail-operator`** — if tools error on account scope or timeouts, fix infra before rewriting prose.

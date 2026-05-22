---
name: email-archive-cleanup
description: This skill should be used when the user asks to "archive old mail safely", "move everything from X sender", "clear newsletters", "bulk mark read after export", or run staged cleanup campaigns. Uses search_emails, move_email (with dry_run), update_email_status, export_emails, manage_trash, synchronize_account, and get_statistics when measuring progress. Do NOT use for taxonomy design sessions without execution (mailbox-taxonomy), proposing Mail filter rules copy (mail-rules-advisor only), drafting mail (email-drafting), or the 5-minute triage skim (inbox-triage).
---

# Archive And Cleanup Campaigns

High-leverage transformations with **explicit human checkpoints**. Optimize for reversible moves (`Archive`, `Trash` soft-delete) unless the operator understands permanent deletes.

## Standard Campaign Shape

### 1. Frame The Objective And Scope

- Confirm target **account**, mailbox, sender/topic/date window.
- Decide whether backlog is exploratory (`recent_days` wide) or targeted (`sender=`, `subject_keyword=`).

### 2. Establish Evidence

Sequence:

1. `search_emails(..., limit≤50)` preview — escalate only after inspecting sample subjects.
2. Optional analytics: `get_statistics(scope="sender_stats", sender="...")` or `scope="mailbox_breakdown"` for volume proof.
3. When deletion risk looms: `export_emails(...)` snapshots before **`manage_trash`**.

Always quote expected totals after dry runs.

### 3. Simulate Mutations (`dry_run=True`)

Mandatory first pass:

- **`move_email(dry_run=True, ...)`** — validate counts + mailbox path spelling (nested slashes).
- Trash paths: **`manage_trash(action="move_to_trash", dry_run=True, ...)`** before committing.

Discuss raising `max_moves` / `max_deletes`; defaults protect against catastrophe.

### 4. Execute In Batches

| Action | Typical tool |
|--------|---------------|
| File / archive batch | `move_email(dry_run=False, subject_keyword | sender | message_ids ..., max_moves=50)` |
| Mark processed | `update_email_status(action="mark_read"|"unflag", max_updates≤50 after confirmation)` |
| Remove noise | Prefer trash soft-delete with caps; escalate `delete_permanent` only post-export + verbal/written affirmation |
| Hydrate caches | `synchronize_account()` after large moves |

Re-run narrower searches between batches until stop conditions.

### 5. Regression Check

Finish with **`get_statistics(scope="account_overview")`** or **`get_inbox_overview()`** verifying queues match operator expectations.

## Safety Reference

| Hazard | Mitigation |
|--------|-------------|
| Over-broad keywords | Narrow by `mailbox=`, combine sender + unread flags |
| Mailbox typos | `list_mailboxes` validation before destructive move |
| Accidental unread wipe | Separate pass for unread-only subsets |
| Cross-account fallout | Iterate per account instead of omnibus `all_accounts=True` mutations |

Permanent deletes invoke irreversible **`manage_trash(action="delete_permanent")`** — escalate only with evidence export + checklist.

## Sibling Routing

| If the user pivots... | Skill |
|------------------------|-------|
| Needs smarter folder ontology | **`mailbox-taxonomy`** |
| Wants sieve text for automation | **`mail-rules-advisor`** |
| Suddenly needs reply drafts | **`email-drafting`** |

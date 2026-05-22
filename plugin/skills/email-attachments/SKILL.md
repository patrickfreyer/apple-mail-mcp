---
name: email-attachments
description: This skill should be used when the user asks to "list attachments on messages about X", "save this PDF from email", "which invoices have ZIP files", or needs disk-safe attachment extraction. Uses list_email_attachments (subject-scoped scans), save_email_attachment, search_emails (has_attachments filters), get_email_by_id for confirmation, optionally export_emails for bundles. Do NOT use when the real goal is writing responses (email-drafting), diagnosing slow accounts (apple-mail-operator), bulk deleting mail (email-archive-cleanup), or designing folder hierarchies (mailbox-taxonomy).
---

# Email Attachments

Attachment-focused traversal with deliberate **filesystem hygiene**. Never save into sensitive system paths — the MCP blocks known dangerous destinations; still confirm user intention.

## When To Use This Skill

| Signal | Skill |
|--------|-------|
| "Save attachment ..." | Here |
| "What files shipped with invoice thread?" | Here |
| "Reply summarizing attachments" | Start here for inventory → **`email-drafting`** |

## Operational Flow

### 1. Narrow The Message Universe

Prefer known `message_id` from upstream search/list.

Otherwise:

```
search_emails(subject_keyword="...", has_attachments=true, recent_days=7, limit=20)
```

Widen timeframe only after checking performance.

### 2. Inspect Attachments Cheaply

```
list_email_attachments(subject_keyword="...", max_results=10)
```

If duplicates exist, escalate with `search_emails` + **`get_email_by_id`** targeting specific numeric ids prior to save.

### 3. Persist With Validation

```
save_email_attachment(subject_keyword="...", attachment_name="Quarterly.pdf",
                      save_path="/Users/<user>/Documents/Finance/Quarterly.pdf",
                      message_ids=["12345"])
```

Rules:

- Path must reside under **`$HOME`** per server validation.
- When multiple attachments match partial names, disambiguate with additional filters or sequential saves per `message_ids`.

### 4. Integrity Pass

Echo saved path, approximate size expectation, optionally open file externally (outside MCP).

When batch exports help (entire mailbox evidence trail), optionally layer **`export_emails`** afterward.

### 5. Aftercare

Recommend virus scanning posture for unsolicited archives; never auto-enable macros/ZIPs.

## Pitfalls Table

| Issue | Guidance |
|-------|----------|
| Ambiguous filenames | Prefer exact match substrings surfaced by `list_email_attachments` |
| Password-protected zips | Note inability to introspect payload |
| Extremely large corp attachments | Mention Mail may choke — consider chunked manual download |

## Related Skills

- **`email-drafting`** — cite attachment paths when emailing summaries.
- **`apple-mail-operator`** — if attachment listing times out due to account scope mishaps.

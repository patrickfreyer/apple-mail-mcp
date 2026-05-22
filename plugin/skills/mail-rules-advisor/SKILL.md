---
name: mail-rules-advisor
description: This skill should be used when the user asks to "suggest Gmail-style filters", "build Mail rules text", "separate newsletters", "route invoices", or tame noisy domains by automation — without expecting MCP automation. Uses get_top_senders, search_emails, get_statistics(scope="sender_stats"), list_mailboxes, and optionally export_emails for offline evidence. Ends with prose rule specs only; Mail rules/VIP lists must be created manually in Mail.app UI. Do NOT use for drafting mail (email-drafting), taxonomy-only planning without evidence (narrow use with mailbox-taxonomy), or destructive cleanup (email-archive-cleanup).
---

# Mail Rules Advisor (Read-Only Evidence)

Produce **implementable**, human-applied Mail rules derived from MCP analytics. Explicitly disclaim: **no MCP call creates Mail rules.**

## Investigation Loop

### 1. Quantify Sources

```
get_top_senders(limit=30, days_back=30, group_by_domain=true)
```

Focus on recurring automated domains versus human counterparts.

### 2. Drill Candidates

```
search_emails(sender="...", recent_days=30, limit=20, include_content=false)
get_statistics(scope="sender_stats", sender="...")
```

Note subject archetypes (“invoice attached”, newsletters, ticketing systems).

### 3. Inventory destinations

`list_mailboxes(include_counts=false)` ensures proposed targets exist or call out missing folders (Mail UI creation or `mailbox-taxonomy` path).

### 4. Compose Rule Spec Sheets

Deliver tables like:

| Rule name | Scope | Predicate | Actions | Confidence |
|-----------|-------|-----------|---------|-------------|
| `Finance Invoices Auto-File` | account X | Sender domain `@vendor.com` + subject tokens `INV` | Move to `Finance/AP Inbox`, skip notification | Medium |

Specify whether Apple Mail **Rules**, **VIP**, Smart Mailboxes — each still manual wiring.

### 5. Tie To Operational Follow-Up

Recommend pairing with **`email-archive-cleanup`** for historical remediation **after** new rules intercept fresh mail.

### Optional Offline Bundle

Offer `export_emails(max_emails=1000)` for analysts who spreadsheet outside MCP — confirm disk path hygiene first.

## Guardrails

| Pitfall | Response |
|---------|----------|
| False positives during transition | Recommend staging + monthly review mailbox |
| Apple Mail limitations | Mention server-side sieve absent for some providers |
| Privacy | Strip customer PII from sample sections when emailing specs externally |

## Related Skills

- **`mailbox-taxonomy`** — aligns folder namespaces with rule targets.
- **`email-archive-cleanup`** — backfills backlog once interception works.

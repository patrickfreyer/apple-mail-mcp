---
name: email-style-profile
description: This skill should be used when the user asks to "write like me", "match my email tone", "learn my signatures", or wants the assistant to capture voice, structure, greeting/closing habits, and length preferences before drafting mail. Reads mostly via search_emails (Sent mailbox corpus), get_email_thread(account=..., ...), get_email_by_id and supplements with USER_EMAIL_PREFERENCES injection; hands off drafting to email-drafting. Do NOT use for inbox cleanup (email-management), archiving (email-archive-cleanup), or Mail setup errors (apple-mail-operator).
---

# Email Style Profile

Establish a repeatable **voice contract** derived from observable mail plus explicit preferences.

## Workflow

### 1. Gather Explicit Preferences First

Collect explicit bullets (or ingest existing notes from the user) covering:

- Formality ladder (investor memo vs teammate ping).
- Default greeting/sign-off patterns (including language toggles).
- Paragraph length norms, bullets vs prose, emoji policy.
- Red lines (topics not to autop-generate).

Encode durable preferences inside **`USER_EMAIL_PREFERENCES`** so every preference-aware MCP tool inherits the context.

### 2. Harvest Sent-Mail Samples Read-Only

| Step | Tool call |
|------|-----------|
| Pull recent Sends | `search_emails(mailbox="Sent", include_content=true, recent_days=30, limit=15)` — tighten `recent_days` if timeouts |
| Deepen hallmark threads | `get_email_thread(account="...", subject_keyword="...")` or `get_email_by_id(...)` when the user cites concrete threads |
| Check alternate aliases | Cross-check `list_account_addresses` outputs if tone shifts per persona |

Interpret samples **summaristically** — do not stash full bodies into long-term prose outside the negotiated profile document the user accepts.

### 3. Produce A Style Ledger

Deliver a concise artifact (bullet list acceptable) containing:

- Voice adjectives + example phrases sanitized of PII unless user consents.
- Structural habits (lead with ask vs context-first).
- Signature components and escalation paths (“when to CC legal/finance”).
- Anti-patterns to avoid inferred from frustrations the user mentions.

### 4. Wire Into Draft Flow

Always cross-link to **`email-drafting`** for actual compose operations. Mention when **draft-safe** mode means output must stop at drafts pending human send.

### 5. Maintain And Refresh

Recommend re-sync after major role changes quarterly or whenever the user says responses “sound off”. Use narrower `recent_days` window for refreshes unless they request historical study.

## Guardrails

- Never impersonate humans outside authorized mailbox scope.
- If Sent-mail samples are insufficient, pause and gather **two** real examples before guessing voice.
- When privacy policies forbid training on mail, revert to declarative **`USER_EMAIL_PREFERENCES`** only.

## Related Skills

- **`email-drafting`** — operational compose/draft/send guardrails (subject to `--draft-safe`).
- **`apple-mail-operator`** — fix account enumeration issues blocking Sent pulls.

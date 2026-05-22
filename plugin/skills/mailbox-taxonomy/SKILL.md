---
name: mailbox-taxonomy
description: This skill should be used when the user asks to "design my folder structure", "mailboxes are a mess", "project vs client email organization", or wants a repeatable taxonomy plus noise diagnosis before archiving. Uses list_mailboxes, get_statistics (account_overview, mailbox_breakdown), get_top_senders, synchronize_account, and create_mailbox after explicit approval. Do NOT use for the 5-minute triage ping (see inbox-triage), one-shot bulk moves (see email-archive-cleanup), drafting mail (email-drafting), or building Mail.app filter rules programmatically — there is no rule-creation MCP tool (see mail-rules-advisor).
---

# Mailbox Taxonomy And Structure

Architect a **shallow**, searchable folder system aligned to how Apple Mail behaves with this MCP. Emphasize semantics that survive growth (clients, streams, SLA queues) rather than heroic deep trees.

## When To Use

| Signal | Route here |
|--------|-------------|
| "How should folders work?" | Yes |
| Naming schemes for Ops / Sales / Exec assistants | Yes |
| Diagnose cluttered mailboxes + top offenders | Yes (pair with **`mail-rules-advisor`** for rule text) |

## Discovery Pass

Run in order, stopping if latency spikes:

1. `list_mailboxes(include_counts=true)` — capture depth, orphan folders, hotspots.
2. `get_statistics(scope="account_overview", days_back=30)` plus `get_statistics(scope="mailbox_breakdown", mailbox="...")` **per folder under review** — omitting `mailbox` on `mailbox_breakdown` scopes to the default Inbox in code, so always pass the folder name when assessing non-Inbox clutter.
3. `get_top_senders(limit=25, days_back=30, group_by_domain=true)` — map noise domains vs humans.
4. `synchronize_account()` if counts look stale vs Mail UI.

## Design Principles

- Keep tiers **≤3** deep wherever possible (`Client/Anchor` beats `BizDev/Clients/Industry/Alice`).
- Split **Action**, **Waiting For**, **FYI/Reference**, **Automated Streams** primitives before bespoke project folders.
- Prefer search + tagging flags for ephemeral contexts; carve dedicated folders only for compliance or retention-heavy streams.
- Name mailboxes deterministically (`Archive/YYYY` vs ad-hoc synonyms).

## Applying Structure With MCP

Only after user sign-off:

- Create net-new folders via **`create_mailbox(name="Parent/Child")`** — rename/delete still occurs inside Mail UI manually.
- Document rollback (move everything back Inbox?) before writes.

Avoid bulk migrations inside this skill — hand off staged moves plus `dry_run` flows to **`email-archive-cleanup`**.

## Interfaces With Adjacent Skills

| Need | Delegate |
|------|----------|
| Filter text for Mail Rules UI | **`mail-rules-advisor`** |
| Execute moves / trash / exports | **`email-archive-cleanup`** |
| Compose templates per folder SLA | **`email-drafting`** + **`email-style-profile`** |

## Risk Notes

Structural writes lack undo beyond manual moves — treat `create_mailbox` like infra change management (ticket + rationale).

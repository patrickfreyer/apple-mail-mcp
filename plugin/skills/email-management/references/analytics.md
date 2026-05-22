# Email Analytics & Insights

Use analytics tools to understand email patterns before reorganizing or cleaning up. Insight first, action second.

## Tools

- `get_statistics(scope="account_overview")` — totals, read/unread ratio, flagged count, top senders, mailbox distribution.
- `get_statistics(scope="sender_stats", sender="name@example.com")` — message count and unread count from a specific sender, plus attachment volume.
- `get_statistics(scope="mailbox_breakdown", mailbox="FolderName")` — per-mailbox totals, unread count, and read ratio.
- `get_top_senders(account="...", limit=20)` — surface the heaviest senders ranked by volume. Use this to identify newsletter overload, noisy systems, or recurring threads worth bulk-archiving.

## Workflows

### Understand overall load

Run `get_statistics(scope="account_overview")` once per account. Look at the unread ratio and the top senders list. A read ratio below 50% usually means inbound volume exceeds processing capacity — fix that with filters and unsubscribes before tweaking folders.

### Diagnose a noisy sender

Run `get_top_senders()` first to find the worst offenders. For each candidate, call `get_statistics(scope="sender_stats", sender="...")` to confirm volume and unread proportion. High volume plus high unread ratio is a strong signal to unsubscribe (newsletters) or create a dedicated folder (active project threads).

### Identify newsletters

There is no dedicated newsletter detector. Use `get_top_senders()` to rank by volume, then evaluate each sender by name — list addresses, automated systems, and `no-reply@` patterns are almost always newsletters. Unsubscribe in the Mail app or set up a rule.

### Find folders that need cleanup

Iterate over the output of `list_mailboxes(include_counts=True)`, then call `get_statistics(scope="mailbox_breakdown", mailbox="...")` on the top three by message count. Mailboxes with thousands of messages and a high read ratio are good archive candidates.

## Actionable Signals

| Pattern | Suggested action |
|---------|------------------|
| One sender accounts for more than 10% of inbox | Create a dedicated folder or unsubscribe |
| Many unread messages in Archive | Archive is being used as a triage queue — run bulk cleanup |
| Flagged count growing week over week | Schedule a follow-up review block |
| Mailbox over 5,000 messages | Export and prune (see `references/bulk-cleanup.md`) |

# Thread Management

Apple Mail does not expose true conversation threads to AppleScript. The MCP server reconstructs threads by stripping `Re:`, `Fwd:`, and locale-specific prefixes from subjects and grouping the result.

## Tool

`get_email_thread(subject_keyword="...", account="...", mailbox="All")` returns all messages whose normalized subject matches the keyword, sorted chronologically.

## When To Use

- The user references a conversation that spans multiple replies.
- A single message lacks context and the prior exchange is needed to understand it.
- Before bulk-archiving a long-running discussion, to confirm the full set of related messages.

## Workflows

### Read a conversation in order

```text
get_email_thread(subject_keyword="Q2 planning")
```

The result is already chronological. Read top to bottom for context.

### Archive a resolved thread

1. `get_email_thread(subject_keyword="...")` to surface every related message.
2. Confirm the count and date range with the user.
3. `move_email(subject_keyword="...", to_mailbox="Archive/2026", max_moves=N)` where N is the confirmed count plus a small buffer.

### Find the latest message in a long thread

The last entry returned by `get_email_thread()` is the most recent. Prefer replying with `reply_to_email(message_id=...)` when search or list tools already returned the Mail id; use `subject_keyword` only when no id is available. For bulk human review, use `mode="open"` so each saved draft stays visible in Mail. See **`email-drafting`** for compose tool selection.

## Cross-Account Threads

`get_email_thread()` honors the same account and mailbox scoping as `search_emails()`. For a thread that spans personal and work accounts, pass `account=None` and `mailbox="All"` to capture every match. This is slower; only do it when single-account scope is known to be incomplete.

## Limitations

- Subject-prefix stripping is approximate; threads with subject edits ("Q2 planning → revised") will split.
- The MCP server cannot expose the underlying `Message-ID` or `In-Reply-To` headers, so deeply nested forwards may appear as separate threads.
- Use `include_content=True` sparingly on `get_email_thread` — full content for every message in a long thread is expensive.

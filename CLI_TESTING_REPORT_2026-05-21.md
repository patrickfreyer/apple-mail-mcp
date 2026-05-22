# Apple Mail MCP CLI Testing Report

**Date:** 2026-05-21  
**Branch:** `improve-speed-and-tools`  
**Scope:** Safe live testing of the repo-owned `apple-mail` CLI, the shared generated `apple-mail` wrapper, and core Apple Mail MCP tools against the local Mail.app mailbox.  
**Safety:** Read-only calls and dry-run mutation previews only. No messages were moved, deleted, sent, or marked during this sweep.

## Summary

The current branch is much improved. The repo-owned CLI and shared generated wrapper are now fast for the basic workflows agents need most often: listing accounts, listing addresses, listing mailboxes, reading limited inbox metadata, subject search, exact-id read, smoke testing, and no-hit dry-run move/trash previews.

The remaining problems are concentrated in heavier cross-account dashboard/overview paths, invalid-account handling, slow analysis tools, and inconsistent generated wrapper JSON output.

## Validation

- Full unit test suite: `113 passed`
- Repo branch: `improve-speed-and-tools`
- Latest tested commit before this report: `3d033a6`
- Shared generated wrapper path: `/Users/cayman-mac-mini/.local/bin/apple-mail`
- Repo CLI path: `.venv/bin/apple-mail`
- Checked for stale AppleScript/MCP runner processes after testing; no stale `osascript`, `start_mcp`, `mcporter`, or Apple Mail MCP runner remained.

## What Works Well

### Repo-Owned CLI

These commands worked correctly and returned quickly:

- `accounts --json`: about `0.37s`
- `addresses --json`: about `0.45s`
- `mailboxes --account ai.openclaw --no-counts --json`: about `0.73s`
- `inbox --account ai.openclaw --limit 2 --json`: about `0.60s`
- `inbox --account ai.openclaw --limit 1 --content --json`: about `0.59s`
- `search --account ai.openclaw --query NO_SUCH_SUBJECT_APPLE_MAIL_CLI_SMOKE_20991231 --limit 2 --json`: about `0.49s`
- `search --account ai.openclaw --query "Run failed" --limit 2 --json`: about `1.21s`
- `show --account ai.openclaw --id <message-id> --no-content --json`: about `0.58s`
- `smoke-test --account ai.openclaw --json`: about `0.88s`
- `mcp-config --repo <repo>`: about `0.24s`

The repo-owned CLI is now a good default for coding agents because it is stable, portable, and uses the same Python tool functions as the MCP server.

### Shared Generated Wrapper

The generated shared wrapper is now pointed at the repo plugin, so it benefits from the branch fixes instead of running a stale copied plugin.

These wrapper paths worked well:

- `list-accounts`: about `0.63s`
- `list-account-addresses`: about `0.59s`
- `list-mailboxes --include-counts false`: about `0.82s`
- `list-inbox-emails --max-emails 2 --include-content false --output-format json`: about `0.77s`
- no-hit `search-emails`: about `0.62s`
- no-hit `list-email-attachments`: about `0.51s`
- no-hit `move-email --dry-run true`: about `0.61s`
- no-hit `manage-trash --dry-run true`: about `0.62s`
- `get-mailbox-unread-counts --summary-only true`: about `0.83s`
- `manage-drafts --action list`: about `0.53s`

The previous severe dry-run timeout for `move-email` no longer reproduced in this sweep.

## What Does Not Work Well

### `inbox-dashboard` Times Out

`apple-mail -o json inbox-dashboard` hit a `40s` wrapper timeout.

Likely cause: it calls both unread summary and `_get_recent_emails_structured(max_total=20, max_per_account=10)` across every configured account. That helper also extracts message previews, which forces content reads and makes the dashboard too expensive for a default cross-account call.

Recommended fix:

- Make dashboard data collection async/per-account.
- Add `account`, `max_total`, `max_per_account`, and `include_preview` parameters.
- Default `include_preview` to `false`.
- Return partial results if one account is slow.
- Prefer metadata-only dashboard cards unless the user explicitly asks for previews.

### Unknown Account Handling Is Poor

Two invalid-account checks behaved badly:

- Generated wrapper `list-inbox-emails --account NO_SUCH_ACCOUNT_APPLE_MAIL_CLI_SMOKE ...` timed out at `40s`.
- Repo CLI `inbox --account NO_SUCH_ACCOUNT_APPLE_MAIL_CLI_SMOKE --limit 1 --json` returned empty success after about `12s`.

Recommended fix:

- Validate explicit account names before running mailbox scripts.
- Return a structured `account_not_found` error with available account names or a redacted count.
- Do not call `account "<name>"` directly for a missing account when the account list can be checked cheaply first.

### Higher-Level Analysis Tools Are Still Slow

Live wrapper timings on `ai.openclaw`:

- `get-needs-response --days-back 2 --max-results 3`: about `14s`
- `get-awaiting-reply --days-back 2 --max-results 3`: about `6s`
- `get-top-senders --days-back 2 --top-n 3`: about `6s`
- `get-statistics --scope account_overview --days-back 2`: about `23s`

Recommended fix:

- Push filtering into AppleScript `whose` clauses before property extraction.
- Cap candidate collections before extracting sender/body/content fields.
- Add optional timing metadata: AppleScript duration, parse duration, account count, scanned count, returned count, timeout budget.
- Consider repo-owned CLI wrappers for these tools with conservative defaults.

### `get_inbox_overview` Is Too Large By Default

`get-inbox-overview` returned successfully in about `10s`, but produced about `8.7KB` of text. It always includes multiple sections that agents may not need.

Recommended fix:

- Add compact mode.
- Add JSON mode.
- Add account scoping.
- Add toggles for mailbox counts, recent previews, and suggested actions.
- Default agent-facing calls to compact metadata.

### Generated Wrapper JSON Shape Is Inconsistent

Some wrapper tools emit clean structured JSON arrays/dicts. Others return nested structures like:

```json
{
  "content": [...],
  "structuredContent": {
    "result": "large text payload"
  },
  "isError": false
}
```

This makes automation harder because agents have to special-case output parsing per tool.

Recommended fix:

- Prefer structured dict/list returns from Python tools where possible.
- Keep human-readable formatting as an explicit `output_format="text"` mode.
- Normalize wrapper-facing tools to return consistent objects for `output_format="json"`.

## Recommended Next Work

1. Fix `inbox_dashboard` timeout.
2. Add explicit unknown-account validation and structured errors.
3. Expand the repo-owned CLI so agents can avoid the generated wrapper for most safe testing.
4. Add `perf-test` to the repo CLI with redacted timing summaries and pass/fail thresholds.
5. Normalize JSON output across wrapper-facing tools.
6. Add timing telemetry to slow tools.
7. Optimize `get_statistics`, `get_needs_response`, `get_awaiting_reply`, and `get_top_senders`.

## Safe Commands Used

Representative safe commands from the sweep:

```bash
.venv/bin/python -m pytest -q
.venv/bin/apple-mail accounts --json
.venv/bin/apple-mail addresses --json
.venv/bin/apple-mail inbox --account ai.openclaw --limit 2 --json
.venv/bin/apple-mail inbox --account ai.openclaw --limit 1 --content --json
.venv/bin/apple-mail search --account ai.openclaw --query "Run failed" --limit 2 --json
.venv/bin/apple-mail search --account ai.openclaw --query NO_SUCH_SUBJECT_APPLE_MAIL_CLI_SMOKE_20991231 --limit 2 --json
.venv/bin/apple-mail smoke-test --account ai.openclaw --json
apple-mail -o json move-email --account ai.openclaw --to-mailbox Archive --subject-keyword NO_SUCH_SUBJECT_APPLE_MAIL_CLI_SMOKE_20991231 --dry-run true --max-moves 3
apple-mail -o json manage-trash --account ai.openclaw --action move_to_trash --subject-keyword NO_SUCH_SUBJECT_APPLE_MAIL_CLI_SMOKE_20991231 --dry-run true --max-deletes 3
```

## Current Branch State

The actionable backlog from this testing pass has been added to `tasks/todo.md`.

One unrelated untracked file was present during this sweep and was not included in the testing backlog commit:

```text
tasks/plugin-audit-and-action-plan-2026-05-21.md
```

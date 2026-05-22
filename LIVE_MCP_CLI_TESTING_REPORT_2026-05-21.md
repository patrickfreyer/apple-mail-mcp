# Live MCP + CLI Testing Report

**Date:** 2026-05-21  
**Branch:** `improve-speed-and-tools`  
**Scope:** Safe live testing against local Mail.app using both the repo-owned CLI (`.venv/bin/apple-mail`) and the generated MCP wrapper (`apple-mail`).  
**Safety:** Read-only commands and dry-run/no-hit mutation previews only. No mail was sent, moved, deleted, flagged, marked read/unread, or synchronized.

## Current Baseline

The working tree has substantial uncommitted implementation work from another agent. This report tests that current working tree as-is.

Validation gates:

- Unit tests: `206 passed, 27 subtests passed in 1.02s`
- Manifest validation: `validate_manifests.sh: OK (version=3.1.5, tools=27)`
- Registered tools: `27`
- Test account used for live probes: `ai.openclaw`

## Executive Summary

The new work materially improves the live agent experience.

Core agent workflows are now fast and stable through both surfaces:

- account/address discovery
- limited inbox reads
- no-hit and matching search
- compact overview
- dashboard metadata
- no-hit dry-run move/trash
- bad-account handling
- smoke/perf batteries

The old severe failures are fixed:

- `inbox-dashboard` no longer times out; wrapper default returned in about `1.4s` to `2.8s`.
- bad account lookup no longer hangs; wrapper `list-inbox-emails` returned structured `account_not_found` in about `1.0s`.
- `move-email --dry-run` and `manage-trash --dry-run` no-hit cases stay around `1.1s` through the MCP wrapper.

Remaining issues are concentrated in analysis/statistics tools and generated wrapper command exposure.

## Non-Live Gates

```bash
.venv/bin/python -m pytest -q
# 206 passed, 27 subtests passed

bash tools/validate_manifests.sh
# validate_manifests.sh: OK (version=3.1.5, tools=27)
```

## Repo-Owned CLI Results

The repo-owned CLI is now a strong primary testing surface for agents.

| Command group | Result | Timing |
|---|---:|---:|
| `quick-check --json` | pass | `~2.0s` wall |
| `perf-test --json` | pass | `~5.7s` wall |
| `smoke-test --json` | pass | `~1.3s` |
| compact JSON overview | pass | `~1.8s` |
| needs-response JSON wrapper | pass, slow | `~14.5s` |
| awaiting-reply JSON wrapper | pass, slow | `~6.5s` |
| top-senders JSON wrapper | pass, slow | `~6.4s` |
| statistics JSON | pass, slow | `~23.7s` |

Notes:

- `perf-test` currently passes because it exercises the fast core paths, not the slower analysis tools.
- `statistics --json` now returns structured JSON, which is good, but it is still slow.
- `needs-response`, `awaiting-reply`, and `top-senders` invoked via the repo CLI still return text wrapped as `{"result": "..."}` when `--json` is used. That is better than raw stdout, but not yet a fully structured schema.

## MCP Wrapper Results

The generated wrapper was tested through the `apple-mail` command. This is the path many agents will hit when using the shared MCP tool.

### Fast / Good

| MCP wrapper command | Result | Timing |
|---|---:|---:|
| `list-accounts` | pass | `~1.2s` |
| `list-account-addresses` | pass | `~1.0s` |
| `list-mailboxes --include-counts false` | pass | `~1.5s` |
| `get-mailbox-unread-counts --summary-only true` | pass | `~1.3s` |
| `list-inbox-emails` metadata, 2 messages | pass | `~1.2s` |
| `list-inbox-emails` content preview, 1 message | pass | `~1.2s` |
| `search-emails` no-hit | pass | `~1.1s` |
| `search-emails` matching subject, 2 results | pass | `~2.0s` |
| `get-email-thread` no-hit, 48h window | pass | `~2.0s` |
| compact `get-inbox-overview` via `--raw` | pass | `~2.3s` |
| `inbox-dashboard` metadata | pass | `~1.4s` |
| attachment lookup no-hit | pass | `~1.0s` |
| drafts list | pass | `~1.0s` |
| move dry-run no-hit | pass | `~1.1s` |
| trash dry-run no-hit | pass | `~1.1s` |
| invalid account inbox | pass, structured error | `~1.0s` |

### Slow But Working

| MCP wrapper command | Result | Timing |
|---|---:|---:|
| `get-needs-response --days-back 2 --max-results 3` | pass, slow | `~14.9s` |
| `get-awaiting-reply --days-back 2 --max-results 3` | pass, slow | `~7.7s` |
| `get-top-senders --days-back 2 --top-n 3` | pass, slow | `~7.2s` |
| `get-statistics` JSON, 2-day account overview | pass, slow | `~24.4s` |

These are now the main performance targets.

## Problems Found

### 1. Generated Wrapper Does Not Expose `get_email_by_id`

The Python tool and manifests now include `get_email_by_id`, but the generated wrapper command list does not expose a `get-email-by-id` command.

Observed:

```bash
apple-mail -o json get-email-by-id --raw '{"account":"ai.openclaw","message_id":"42031","include_content":false,"output_format":"json"}'
# error: unknown command 'get-email-by-id'
```

The wrapper help lists `get-email-thread`, `get-inbox-overview`, and other tools, but not `get-email-by-id`.

Likely cause:

- The shared generated wrapper command metadata is stale even though the embedded plugin path points to the repo.
- Manifest validation can be green while the generated wrapper CLI still lacks a newly added command.

Recommended fix:

- Regenerate/reinstall the generated `apple-mail` wrapper after manifest/tool sync.
- Add a wrapper smoke check that asserts important commands are present, especially `get-email-by-id`.
- Prefer the repo CLI `show` command for exact-id reads until the wrapper is regenerated.

### 2. Analysis Tools Are Still Too Slow

The analysis tools work, but they are slow enough that agents will avoid them in tight loops:

- `get-needs-response`: about `15s`
- `get-awaiting-reply`: about `7s`
- `get-top-senders`: about `7s`
- `get-statistics`: about `24s`

Recommended fixes:

- Add an optional `analysis-perf-test` or `perf-test --include-analysis` so this class of slowdown is visible in the standard gate.
- Push more filtering into AppleScript before property extraction.
- Reduce default scan windows/caps for agent-facing calls.
- Add structured JSON output for `needs-response`, `awaiting-reply`, and `top-senders` rather than wrapping text in `{"result": "..."}`.
- Consider returning partial timing metadata: scanned count, returned count, AppleScript duration, parse duration.

### 3. Wrapper Flags Differ From Repo CLI Flags

One initial wrapper command failed because I passed a repo-CLI-only flag:

```bash
apple-mail -o json list-mailboxes --account ai.openclaw --include-counts false --output-format json
# error: unknown option '--output-format'
```

The correct wrapper command works:

```bash
apple-mail -o json list-mailboxes --account ai.openclaw --include-counts false
```

This is not a server bug, but it is a usability issue: the repo CLI and generated wrapper expose different flag surfaces.

Recommended fix:

- Document the difference in `docs/AGENT_LIVE_TESTING.md`.
- Where possible, align names and flags between the repo CLI and wrapper.
- Keep `--raw` examples for wrapper-only advanced options like compact overview.

### 4. Wrapper `get-inbox-overview` Only Shows `--raw`

The wrapper help for `get-inbox-overview` exposes only:

```text
Usage: get-inbox-overview [--raw <json>]
```

The raw JSON call works, but discoverability is poor:

```bash
apple-mail -o json get-inbox-overview --raw '{"account":"ai.openclaw","output_format":"json","compact":true,"include_mailboxes":false,"include_recent":false,"include_suggestions":false}'
```

Recommended fix:

- Improve generated wrapper metadata/signature exposure if possible.
- Add copy-paste raw examples to the live testing doc.

## What Needs To Be Addressed In The Codebase

Priority order:

1. **Regenerate or repair the shared generated wrapper** so `get-email-by-id` is available.
2. **Add wrapper command-surface tests**: generated help should include all 27 registered tools or at least a critical subset.
3. **Add analysis tools to a live perf gate** behind an explicit flag, e.g. `perf-test --include-analysis`.
4. **Optimize slow analysis/statistics tools**: `get_statistics`, `get_needs_response`, `get_awaiting_reply`, `get_top_senders`.
5. **Make JSON truly structured for analysis tools**, not text inside `{"result": "..."}`.
6. **Document repo CLI vs MCP wrapper differences**, especially `--raw` and unsupported repo-only flags.
7. **Keep exact-id reads available through repo CLI** (`show`) until the MCP wrapper command is fixed.

## Recommended Agent Workflow Right Now

Use the repo CLI for reliable iterative testing:

```bash
.venv/bin/apple-mail quick-check --account ai.openclaw --json
.venv/bin/apple-mail perf-test --account ai.openclaw --json
.venv/bin/apple-mail show --account ai.openclaw --id <message_id> --no-content --json
```

Use the MCP wrapper for tool parity checks:

```bash
apple-mail -o json list-accounts
apple-mail -o json list-inbox-emails --account ai.openclaw --max-emails 2 --output-format json
apple-mail -o json search-emails --account ai.openclaw --subject-keyword "Run failed" --limit 2 --output-format json
apple-mail -o json inbox-dashboard --raw '{"account":"ai.openclaw","max_total":5,"max_per_account":2,"include_preview":false}'
apple-mail -o json move-email --account ai.openclaw --to-mailbox Archive --subject-keyword NO_SUCH_SUBJECT_APPLE_MAIL_CLI_SMOKE_20991231 --dry-run true --max-moves 3
```

Avoid relying on the generated wrapper for exact-id reads until `get-email-by-id` is exposed there.

## Process Hygiene

No stale AppleScript/MCP runner processes were left after the live sweep. The only unrelated process observed was Cursor's extension host for the repo.

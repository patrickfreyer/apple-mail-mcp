# Live test baseline — 2026-05-21

Consolidated results from repo CLI (`.venv/bin/apple-mail`) and generated MCP wrapper (`apple-mail`) on branch `improve-speed-and-tools` after 3.1.6 hardening. **Historical snapshot** — unit test count was 206 at capture time; suite is now **221 tests**. **Use `cayman@agenticassets.ai` as the production perf gate** — it reflects real mailbox depth (194 mailboxes, heavy Exchange/Gmail-style layout). Use `ai.openclaw` only as a light smoke/regression account.

## Accounts

| Account | Mailboxes | Role |
|---------|-----------|------|
| `cayman@agenticassets.ai` | **194** | **Production gate** — primary account for perf work |
| `ai.openclaw` | 9 | Light smoke account — fast path regression only |

Set for local testing:

```bash
export DEFAULT_MAIL_ACCOUNT="cayman@agenticassets.ai"
```

## Unit / CI (no Mail.app)

| Check | Result |
|-------|--------|
| `pytest tests/ -q` | **206 passed**, 27 subtests *(221 tests as of plugin skill suite work)* |
| `tools/validate_manifests.py` | OK (version=3.1.5, tools=27) |

Latest safe wrapper/CLI sweep: root [`LIVE_MCP_CLI_TESTING_REPORT_2026-05-21.md`](../LIVE_MCP_CLI_TESTING_REPORT_2026-05-21.md).

## Core path — PASS on both accounts

| Tool / probe | `ai.openclaw` | `cayman@agenticassets.ai` | Notes |
|--------------|---------------|---------------------------|-------|
| `quick-check` | ~2.1s ✅ | ~8.1s ❌ | cayman fails **metadata** only |
| `perf-test` (full) | ~5.7s ✅ | ~21.6s ❌ | cayman fails **metadata** + **overview** |
| `smoke-test` | ~0.9–2.4s ✅ | ~2.4s ✅ | All functional checks pass |
| `inbox-dashboard` (wrapper) | ~2.8s ✅ | ~1.3s (metadata case) ✅ | Fixed vs earlier timeout |
| invalid account | ~1.1s ✅ | ~0.4s ✅ | Structured `account_not_found` |
| `overview --format json` | ~2.1s ✅ | ~10.8s ❌ (in full battery) | Over 10s threshold on production |
| dry-run move/trash | ✅ | ✅ | Sub-second |

## Analysis path — NOT in `perf-test` today (main gap)

Measured via individual CLI probes on **`ai.openclaw`** (other agent, same branch):

| Command | Wall time | Target (draft) |
|---------|-----------|----------------|
| `needs-response --days 2` | **~14.5s** | &lt; 8s |
| `awaiting-reply --days 7` | **~6.6s** | &lt; 5s |
| `top-senders --days 30` | **~6.4s** | &lt; 5s |
| `statistics --scope account_overview --days 2 --json` | **~23.8s** | &lt; 12s |

`perf-test` passes today because it **does not exercise analysis tools** — a false green for triage workflows.

The latest generated-wrapper sweep saw the same pattern:

| Wrapper command | Wall time |
|-----------------|-----------|
| `get-needs-response --days-back 2 --max-results 3` | **~14.9s** |
| `get-awaiting-reply --days-back 2 --max-results 3` | **~7.7s** |
| `get-top-senders --days-back 2 --top-n 3` | **~7.2s** |
| `get-statistics` 2-day account overview JSON | **~24.4s** |

## Root causes (code-informed)

1. **`list_mailboxes` + `include_counts=True`** (metadata probe) — one AppleScript round-trip per mailbox for `count of messages` + `unread count`. At 194 mailboxes → ~7s on production account. Light account (9 boxes) → ~1s.
2. **`get_statistics` / `account_overview`** — up to 20 mailboxes × 500 messages, per-message property reads (read/flagged/attachments/sender). Worst-case ~10k Apple Event round-trips in one script.
3. **`get_needs_response`** — inbox unread scan + sent-subject lookup table + **`content of aMessage`** (500 chars) for `?` detection + nested reply-matching loops.
4. **`get_awaiting_reply`** — dual mailbox scan (inbox + sent) with subject/sender correlation loops.
5. **`get_top_senders`** — capped scan but O(unique senders²) aggregation still in AppleScript for large slices.

## Wrapper / agent ergonomics

- Generated mcporter wrapper: `get-inbox-overview` help only shows `--raw`; repo CLI exposes full flags. Raw JSON path works (~2.7s).
- Generated wrapper currently **does not expose `get-email-by-id`** even though the Python `@mcp.tool`, MCPB `tools[]`, README, and tests include `get_email_by_id`. Manifest validation is necessary but not sufficient for wrapper parity.
- The wrapper is generated at `/Users/cayman-mac-mini/.local/bin/apple-mail` by `mcporter@0.11.3`; `apple-mail --help` is the command-surface source of truth for wrapper availability.
- Some wrapper tools still wrap JSON under `content`/`structuredContent.result` vs direct dict — automation inconsistency.

## Recommended gates going forward

| Gate | Command | Account |
|------|---------|---------|
| Fast post-edit | `quick-check --json` | `cayman@agenticassets.ai` (after threshold fix) |
| Core perf | `perf-test --json` | `cayman@agenticassets.ai` |
| Analysis perf | `perf-test --include-analysis --json` *(to build)* | `cayman@agenticassets.ai` |
| Wrapper parity | `apple-mail --help` includes `get-email-by-id` *(to automate)* | n/a |
| Functional smoke | `smoke-test --json` | either account |

## References

- Agent workflow: [`docs/AGENT_LIVE_TESTING.md`](../docs/AGENT_LIVE_TESTING.md)
- Prior audit archive: [`archive/2026-05-21/`](archive/2026-05-21/)

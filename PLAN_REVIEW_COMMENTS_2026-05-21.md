# Plan Review Comments

**Date:** 2026-05-21  
**Reviewer:** Forge  
**Reviewed files:** `tasks/plugin-audit-and-action-plan-2026-05-21.md`, `tasks/phase-plan-3.1.6.md`, and the linked `tasks/todo.md` update  
**Branch:** `improve-speed-and-tools`  
**Current baseline:** `113` tests passing; latest pushed repo commit before this review was `e4a7670`

## Status (updated 2026-05-21, post Phase 0+A)

Resolution tracking lives in **[`tasks/plan-review-status-2026-05-21.md`](tasks/plan-review-status-2026-05-21.md)**.

| Area | Summary |
|------|---------|
| Phase 0 manifest sync | ✅ Done (27 tools, mcpb `get_email_by_id`, SKILL typo) |
| Phase A live fixes | 🟡 Core landed (dashboard async/preview default, account validation on 3 tools, overview compact/JSON, smart_inbox caps); expand validation wiring + tighter dashboard gate still open |
| Tests | ✅ 119 passing (`tests/test_phase_a_fixes.py` added) |
| Still open | Split-PR discipline for *future* work, grep/wc-l command, audit hotspot cleanup, CLAUDE.md/build-mcpb Python text, CI non-live guardrails, FastMCP API verify, staged JSON, perf gates, plugin-validator fallback wording |
| Deferred | `include_timing` (not implemented — defer to Phase B); hybrid SQLite (after A/B/2 benchmarked) |

---

## Bottom Line

The plan is directionally right and is much better than a generic hardening backlog. It correctly shifts priority toward the live-measured problems: `inbox_dashboard`, unknown account handling, `get_inbox_overview`, analysis-tool latency, CLI coverage, manifest drift, and CI guardrails.

I would not start coding from it blindly yet. A few items should be corrected so the next agent does not chase stale findings, mix unrelated work into one risky PR, or rely on validation commands that do not actually check what they claim.

## Changes I Recommend

### 1. Split Phase 0 and Phase A into separate PRs

The phase plan says:

> Next PR: Phase 0 + Phase A items 1-2 — manifest sync + dashboard + account validation.

I would split that into two PRs:

1. **PR 1: Phase 0 only**
   - Manifest/tool-count sync
   - Skill doc typo
   - stale todo cleanup
   - validator/manifest script checks if quick

2. **PR 2: Phase A live fixes**
   - dashboard timeout
   - account validation
   - overview/analysis performance

Reason: Phase 0 is mechanical release metadata. Phase A touches AppleScript behavior and live Mail.app performance. Combining them makes review harder and increases the chance that a functional regression blocks a straightforward manifest correction.

### 2. Fix the tool-count verification command

The plan uses:

```bash
grep -c "^@mcp.tool" plugin/apple_mail_mcp/tools/*.py
```

That command prints per-file counts, not a total. In this repo it returns multiple lines like:

```text
plugin/apple_mail_mcp/tools/analytics.py:4
plugin/apple_mail_mcp/tools/compose.py:5
plugin/apple_mail_mcp/tools/inbox.py:6
...
```

Use one of these instead:

```bash
grep -h "^@mcp.tool" plugin/apple_mail_mcp/tools/*.py | wc -l
```

or:

```bash
rg '^@mcp\.tool' plugin/apple_mail_mcp/tools/*.py | wc -l
```

The current total is `27`.

### 3. Remove the stale `move_email --dry-run` critical hotspot

The full audit still lists this under critical performance hotspots:

> Live perf: `move_email --dry-run` no-hit ~61s vs `manage_trash --dry-run` ~1.2s

Later, the report correctly strikes it as resolved. The critical hotspot table should remove it entirely or mark it resolved inline.

Current live branch behavior:

- `move-email --dry-run` no-hit: about `0.61s`
- `manage-trash --dry-run` no-hit: about `0.62s`

Leaving the old 61s number in the hotspot table will confuse future agents.

### 4. Update stale Python-version text in `CLAUDE.md`

The plan correctly says `start_mcp.sh` already gates on Python 3.10+, but `CLAUDE.md` still says:

> `start_mcp.sh` currently still prints "Python 3.7 or later"

That is stale. Phase 0 should include updating this line, not just `README` / manifest counts.

Also update the stale Python 3.7 text in `apple-mail-mcpb/build-mcpb.sh` embedded README.

### 5. Be careful with account validation overhead

Adding `validate_account_name()` is the right fix, but wiring it naively into every account-scoped tool could add an extra AppleScript account-list call before every operation.

Recommended shape:

- Validate only when the caller passes an explicit `account`.
- Use a small timeout for account listing.
- Return a structured `account_not_found` error quickly.
- Avoid repeated account-list calls inside multi-account fan-out.
- Consider a tiny per-process cache with a short TTL if live timings show account listing overhead accumulating.

Goal:

- bad account: `<2s`, clean error
- good account fast path: no meaningful slowdown

### 6. Keep CI strictly non-live

The plan says CI should run on macOS, which is reasonable, but CI must not depend on real Mail.app data or Automation permissions.

CI should run:

- unit tests with mocked `subprocess.run`
- manifest drift validation
- package/import checks
- maybe CLI parser tests

CI should not run:

- live `apple-mail smoke-test`
- live `perf-test`
- anything requiring Mail.app permissions

Live tests should remain opt-in local commands.

### 7. Verify FastMCP annotation syntax before Phase 3

FastMCP annotations are a good MCP quality target, but the plan should explicitly say to confirm the installed `fastmcp` version supports the intended annotation API before editing all 27 tools.

Current dependency state:

- `pyproject.toml`: `fastmcp>=3.1.0`
- `plugin/requirements.txt`: `fastmcp==3.1.0`

If annotations require a newer FastMCP API, that dependency decision should happen before the annotation pass.

### 8. Normalize JSON in stages, not all at once

The plan is right that wrapper JSON is inconsistent. I would phase this carefully:

1. Add JSON modes to the worst agent-facing tools first:
   - `get_inbox_overview`
   - `inbox_dashboard`
   - `get_statistics`
   - `get_needs_response`
   - `get_awaiting_reply`
   - `get_top_senders`

2. Update repo CLI wrappers to consume those structured modes.

3. Only then consider changing existing JSON shapes like `list_inbox_emails`.

Reason: changing established return shapes can break existing agents. Keep backward-compatible text output and add structured modes before replacing anything.

### 9. Tighten `inbox_dashboard` target behavior

The plan says dashboard should be `<10s`. I would make the default target more aggressive:

- metadata-only default: `<3s` preferred, `<5s` acceptable
- preview-enabled mode: can be slower, but must expose timeout and partial results

The dashboard is a UX entry point. If it takes 9-10 seconds by default, agents will avoid it.

### 10. Add a small "do not do yet" note for the hybrid SQLite path

The hybrid SQLite read path could be a major win, but it should stay out of 3.1.6 unless AppleScript remains too slow after Phase A/B/2.

Suggested wording:

> Do not implement SQLite Envelope Index reads until dashboard/account validation/analysis caps are fixed and benchmarked. Treat SQLite as a spike behind a feature flag because Mail's internal schema is undocumented.

## Smaller Corrections

- The P1/P2 issue register has duplicated numbering around `#11`. Not a functional problem, but it makes cross-references messy.
- `plugin-validator`, `skill-reviewer`, and `plugin-dev:*` are referenced as if always callable. Add fallback wording: if those agents are unavailable, run the local manifest checks and document the missing validator.
- `tasks/phase-plan-3.1.6.md` says "Repo CLI + smoke-test" is done. That is true as a foundation, but CLI coverage is still partial. Keep wording as "repo CLI foundation + smoke-test done."
- `get_mailbox_unread_counts` lacks a timeout parameter and can enumerate a full mailbox tree. The plan mentions it in two places; keep it in Phase 2 or Phase A if overview/dashboard still call it.
- The audit says "10 of 27 tools lack meaningful coverage." Good finding. I would add a specific test target for `inbox_dashboard` because that is now a live failure.

## Suggested Updated Execution Order

1. **Phase 0A: Manifest and doc sync**
   - 27 tools everywhere
   - add `get_email_by_id` to mcpb manifest
   - fix `confirm_empty=True`
   - fix stale Python 3.7/3.10 docs
   - correct stale todo items

2. **Phase 0B: Guardrail script**
   - `tools/validate_manifests.sh`
   - local validation first
   - CI workflow after the script is proven

3. **Phase A1: Unknown account validation**
   - small, testable, likely quick
   - should improve both repo CLI and wrapper

4. **Phase A2: Dashboard default performance**
   - metadata-only default
   - async/partial results
   - preview toggle

5. **Phase B: Repo CLI expansion and perf-test**
   - add safe commands for the newly structured paths
   - make `perf-test` the standard local live gate

6. **Phase 2: Legacy scan hardening**
   - `get_email_thread`
   - compose reply/forward lookup
   - draft list caps
   - exact-id mutation paths

7. **Phase 3/4/5**
   - annotations
   - JSON normalization
   - helper dedup
   - skills and marketplace polish

## What I Would Add To The Plan

### Add Explicit Live Performance Gates

The phase plan already has some gates. I would make them concrete:

```text
accounts/addresses: <1s
limited inbox metadata: <2s
no-hit search: <2s
exact-id show no-content: <2s
bad account error: <2s
dashboard metadata-only: <5s
overview compact JSON: <5s
dry-run move/trash no-hit: <3s
statistics 2-day account overview: <10s
```

### Add Privacy/Redaction Rules For `perf-test`

`perf-test` should never print raw subjects, senders, body content, or addresses unless an explicit `--verbose-sensitive` style flag exists. Default output should be counts, timings, statuses, and redacted sample lengths only.

### Add Backward Compatibility Rule For Return Shapes

Before changing a tool from string output to dict/list output, add or preserve:

- `output_format="text"` for existing behavior
- `output_format="json"` for automation
- tests for both paths

This matters because Claude/OpenClaw agents may already rely on text-returning tools.

## Final Recommendation

Use the plan, but make the corrections above first. The biggest practical change is to split manifest sync from behavior changes. The next best work item is unknown-account validation because it is small, measurable, and currently causes bad timeouts. After that, fix `inbox_dashboard` defaults so the tool becomes usable rather than a 40-second trap.

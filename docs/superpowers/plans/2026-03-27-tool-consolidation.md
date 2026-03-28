# Apple Mail MCP Tool Consolidation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce 31 MCP tools to ~15 by merging overlapping tools while preserving all capabilities.

**Architecture:** Each tool group (search, inbox, manage, bulk) gets consolidated into fewer tools with richer parameter sets. Removed tools' unique capabilities are absorbed into the surviving tool. Existing tests are updated to target the new signatures. No new dependencies.

**Tech Stack:** Python, FastMCP, AppleScript

---

## File Structure

| File | Current Tools | After Consolidation | Changes |
|------|--------------|--------------------|---------|
| `search.py` | 10 tools | 2 tools | Remove 8 tools, merge capabilities into `search_emails` |
| `inbox.py` | 7 tools | 5 tools | Merge `get_recent_emails` into `list_inbox_emails`, merge `get_unread_count` into `get_mailbox_unread_counts` |
| `manage.py` | 7 tools | 3 tools | Merge `update_email_status_by_ids` into `update_email_status`, merge `bulk_move_emails`+`archive_emails` into `move_email`, merge `delete_emails` into `manage_trash` |
| `bulk.py` | 3 tools | 0 tools (DELETE FILE) | All capabilities merged into manage.py tools |
| `smart_inbox.py` | 3 tools | 3 tools | No changes |
| `analytics.py` | 4 tools | 4 tools | No changes |
| `compose.py` | 5 tools | 5 tools | No changes (already fixed in PR #32) |
| `tests/` | 3 files | 3 files | Update imports/assertions; remove bulk helpers test or redirect |

**Final tool count: ~22 tools** (down from 31)

---

## Task 1: Consolidate Search Tools (10 → 2)

**Files:**
- Modify: `apple_mail_mcp/tools/search.py`
- Test: `tests/test_mail_search_tools.py`

**Merge map:**
| Removed Tool | Unique Capability | Absorbed Into |
|---|---|---|
| `search_subjects` | Subject-only search | `search_emails` (already has `subject_keyword`) |
| `get_email_with_content` | Content preview | `search_emails` (already has `include_content`) |
| `search_by_sender` | Cross-account sender search | `search_emails` (make `account` optional) |
| `search_email_content` | Body text search | `search_emails` (add `body_text` param) |
| `get_recent_from_sender` | Time-range sender search | `search_emails` (already has `date_from`/`sender`) |
| `search_all_accounts` | Cross-account search | `search_emails` (make `account` optional) |
| `get_newsletters` | Newsletter detection | Remove entirely |
| `group_emails_by_subject_regex` | Regex grouping | Remove entirely |

**Surviving tools:** `search_emails`, `get_email_thread`

### Step-by-step

- [ ] **Step 1: Extend `search_emails` — make `account` optional for cross-account search**

In `search_emails` (line 518), change `account: str` to `account: Optional[str] = None`. When `account` is None, iterate all accounts (reuse the pattern from `search_all_accounts` line 1461 and `search_by_sender` line 691 which already loop accounts).

The `_search_mail_records` helper (line 161) already accepts `account` — update it to accept `Optional[str]` and loop all accounts when None.

Update the docstring to document cross-account behavior.

- [ ] **Step 2: Add `body_text` parameter to `search_emails`**

Add `body_text: Optional[str] = None` parameter. When provided, add body content search to the AppleScript filter logic inside `_search_mail_records`. Use the lowercase comparison pattern from `search_email_content` (line 912-920):

```python
# In _search_mail_records, when body_text is provided:
# 1. Include LOWERCASE_HANDLER in the script
# 2. Extract content of each message
# 3. Add condition: my lowercase(content of aMessage) contains "{escaped_body_text}"
```

This is slower than subject-only search, so document this in the docstring.

- [ ] **Step 3: Add `max_content_length` parameter to `search_emails`**

Add `max_content_length: int = 500` to `search_emails`. Pass through to `_search_mail_records`. This replaces the dedicated `get_email_with_content` tool's truncation behavior.

- [ ] **Step 4: Remove the 8 consolidated tools**

Delete these function definitions and their `@mcp.tool()` decorators from `search.py`:
- `search_subjects` (line 408)
- `get_email_with_content` (line 473)
- `search_by_sender` (line 691)
- `search_email_content` (line 887)
- `get_recent_from_sender` (line 1127)
- `search_all_accounts` (line 1461)
- `get_newsletters` (line 1000)
- `group_emails_by_subject_regex` (line 595)

Also remove any helper functions that are now unused (e.g., `_newsletter_filter_condition` in smart_inbox.py if only used by `get_newsletters`).

- [ ] **Step 5: Update tests**

In `tests/test_mail_search_tools.py`, update any tests that reference removed tools. Ensure existing `search_emails` tests still pass. Add a test for `account=None` cross-account behavior.

- [ ] **Step 6: Run tests and verify**

```bash
cd /Users/freyerpatrick/projects/apple-mail-mcp && python -m pytest tests/test_mail_search_tools.py -v
```

- [ ] **Step 7: Commit**

```bash
git add apple_mail_mcp/tools/search.py tests/test_mail_search_tools.py
git commit -m "refactor: consolidate 10 search tools into 2 (search_emails + get_email_thread)"
```

---

## Task 2: Consolidate Inbox Tools (7 → 5)

**Files:**
- Modify: `apple_mail_mcp/tools/inbox.py`

**Merge map:**
| Removed Tool | Unique Capability | Absorbed Into |
|---|---|---|
| `get_recent_emails` | Account-specific recent N emails with content | `list_inbox_emails` (add `count` param, already has `include_read`) |
| `get_unread_count` | Quick unread summary | `get_mailbox_unread_counts` (add `summary_only` param) |

**Surviving tools:** `list_inbox_emails`, `get_mailbox_unread_counts`, `list_accounts`, `list_mailboxes`, `get_inbox_overview`

### Step-by-step

- [ ] **Step 1: Merge `get_recent_emails` into `list_inbox_emails`**

Add parameters to `list_inbox_emails`:
- `count: int = 0` (0 = all, N = most recent N — mirrors `get_recent_emails`'s `count` param)
- `include_content: bool = False` (from `get_recent_emails`)

When `count > 0`, limit the loop to `count` messages (add early exit). When `include_content=True`, include content preview in output (use `content_preview_script` from core.py).

The existing `max_emails` param already does limiting — rename/unify: keep `max_emails` as the single limit param (default 0 = unlimited). Remove the separate `count` concept.

- [ ] **Step 2: Merge `get_unread_count` into `get_mailbox_unread_counts`**

Add `summary_only: bool = False` to `get_mailbox_unread_counts`. When True, return only per-account totals (matching `get_unread_count`'s output). When False, return the full per-mailbox breakdown.

Also make `account` optional in `get_mailbox_unread_counts` (it already is — `Optional[str] = None`), matching `get_unread_count`'s all-accounts behavior.

- [ ] **Step 3: Remove merged tools**

Delete `get_recent_emails` (line 351) and `get_unread_count` (line 183) including their `@mcp.tool()` decorators and helper `_get_recent_emails_json`.

- [ ] **Step 4: Update `get_inbox_overview` and `inbox_dashboard`**

`get_inbox_overview` (inbox.py:584) calls no other tools directly (it has its own AppleScript). But `inbox_dashboard` (analytics.py:747) calls `get_unread_count()` — update it to call `get_mailbox_unread_counts(summary_only=True)` instead.

- [ ] **Step 5: Commit**

```bash
git add apple_mail_mcp/tools/inbox.py apple_mail_mcp/tools/analytics.py
git commit -m "refactor: consolidate inbox tools — merge get_recent_emails and get_unread_count"
```

---

## Task 3: Consolidate Manage + Bulk Tools (10 → 5)

**Files:**
- Modify: `apple_mail_mcp/tools/manage.py`
- Delete: `apple_mail_mcp/tools/bulk.py`
- Modify: `apple_mail_mcp/tools/__init__.py` (if it imports bulk)
- Modify: `tests/test_bulk_helpers.py`

**Merge map:**
| Removed Tool | Unique Capability | Absorbed Into |
|---|---|---|
| `update_email_status_by_ids` | ID-based updates | `update_email_status` (add `message_ids` param) |
| `mark_emails` (bulk.py) | Batch mark with date filter | `update_email_status` (add `older_than_days` param) |
| `bulk_move_emails` (bulk.py) | Batch move with filters + dry_run | `move_email` (add `sender`, `older_than_days`, `dry_run` params) |
| `archive_emails` | Move to Archive with read-only + dry_run | `move_email` (archive is just `to_mailbox="Archive"`) |
| `delete_emails` (bulk.py) | Soft-delete with dry_run | `manage_trash` (already has `move_to_trash` action + filters) |

**Surviving tools:** `move_email`, `update_email_status`, `manage_trash`, `save_email_attachment`, `create_mailbox`

### Step-by-step

- [ ] **Step 1: Extend `update_email_status` with `message_ids` and `older_than_days`**

Add parameters:
- `message_ids: Optional[List[str]] = None` — when provided, use ID-based matching (from `update_email_status_by_ids` logic)
- `older_than_days: Optional[int] = None` — date cutoff filter (from `mark_emails` logic)

When `message_ids` is provided, use `equals_any_numeric_condition` for the filter (from current `update_email_status_by_ids`). When `older_than_days` is provided, add date cutoff using `build_date_filter` from core.py.

- [ ] **Step 2: Extend `move_email` with bulk capabilities**

Add parameters:
- `sender: Optional[str] = None` — filter by sender
- `older_than_days: Optional[int] = None` — date cutoff
- `dry_run: bool = False` — preview without moving
- `only_read: bool = False` — only move read emails (for archive use case)

Increase `max_moves` default from 1 to 50 when any bulk filter is provided (sender/older_than_days).

Reuse filter building from `bulk_move_emails` (bulk.py) and date handling from `archive_emails` (manage.py).

- [ ] **Step 3: Extend `manage_trash` with dry_run and older_than_days**

Add parameters:
- `older_than_days: Optional[int] = None`
- `dry_run: bool = True` (safe default, matching `delete_emails`)

- [ ] **Step 4: Remove merged tools and delete bulk.py**

Delete from manage.py:
- `update_email_status_by_ids` (line 385)
- `archive_emails` (line 824)

Delete entire file:
- `apple_mail_mcp/tools/bulk.py`

Update `apple_mail_mcp/tools/__init__.py` to remove bulk import.

- [ ] **Step 5: Move useful bulk.py helpers to core.py**

The `_build_filter_conditions`, `_date_filter_script`, `_mailbox_fallback_script` helpers in bulk.py may be useful. Check if core.py already has equivalents (`build_filter_condition`, `build_date_filter`, `build_mailbox_ref`). If so, just delete the bulk versions. If bulk versions are better, move them to core.py.

- [ ] **Step 6: Update tests**

Move/update `tests/test_bulk_helpers.py`:
- Tests for helpers that moved to core.py should be redirected
- Tests for removed tools should be removed
- Add tests for new `message_ids` param in `update_email_status`

- [ ] **Step 7: Run all tests**

```bash
cd /Users/freyerpatrick/projects/apple-mail-mcp && python -m pytest tests/ -v
```

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: consolidate manage + bulk tools — remove bulk.py, merge into manage.py"
```

---

## Task 4: Trim Verbose MCP Tool Responses

**Files:**
- Modify: `apple_mail_mcp/tools/compose.py`

The `compose_email`, `reply_to_email`, and `forward_email` tools return overly verbose confirmation messages that include the full email body echoed back. This wastes tokens and clutters the conversation.

### Step-by-step

- [ ] **Step 1: Slim down compose_email response**

In `compose_email`, reduce the success output to just:
```
Email sent successfully.
To: <recipients>
Subject: <subject>
```

Remove the echoed body text from the response.

- [ ] **Step 2: Slim down reply_to_email response**

In `reply_to_email`, reduce to:
```
Reply sent successfully.
To: <original sender>
Subject: Re: <subject>
```

Remove echoed reply body and original email details.

- [ ] **Step 3: Slim down forward_email response**

In `forward_email`, reduce to:
```
Email forwarded successfully.
To: <recipients>
Subject: Fwd: <subject>
```

- [ ] **Step 4: Commit**

```bash
git add apple_mail_mcp/tools/compose.py
git commit -m "refactor: trim verbose tool responses to reduce token waste"
```

---

## Task 5: Final Cleanup and PR

- [ ] **Step 1: Remove unused imports across all modified files**

Scan for unused imports in search.py, inbox.py, manage.py, analytics.py after removing tools.

- [ ] **Step 2: Run full test suite**

```bash
cd /Users/freyerpatrick/projects/apple-mail-mcp && python -m pytest tests/ -v
```

- [ ] **Step 3: Update README.md tool list if it documents individual tools**

Check if README lists tools — if so, update to reflect consolidated set.

- [ ] **Step 4: Merge PR #32 (reply fix) first, then create consolidation PR**

```bash
gh pr merge 32 --merge
git checkout main && git pull
git checkout -b refactor/consolidate-tools
git cherry-pick <commits>
gh pr create --title "refactor: consolidate 31 tools down to ~22" --body "..."
```

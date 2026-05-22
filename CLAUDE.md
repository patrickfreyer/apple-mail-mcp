# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

This repo ships **one Python MCP server in three distribution shapes** — pick the right one when you change something:

- `plugin/apple_mail_mcp/` — the actual Python package (source of truth for all tool logic). `pyproject.toml` packages this directory as `mcp-apple-mail` on PyPI.
- `plugin/` — Claude Code plugin wrapper. `plugin/.claude-plugin/plugin.json` registers the MCP server, and `plugin/start_mcp.sh` is the launcher that lazily creates `plugin/venv/` on first run.
- `apple-mail-mcpb/` — Claude Desktop `.mcpb` bundle build files.
- `.claude-plugin/marketplace.json` — top-level marketplace manifest that points at `./plugin`.

The `plugin/venv/` directory is created by `start_mcp.sh` at user-install time and is **not** the dev venv. The repo's dev venv is `.venv/` at the root.

## Common commands

```bash
# Dev setup (root venv, editable install)
python3 -m venv .venv
.venv/bin/pip install -e . pytest

# Run all tests
.venv/bin/pytest tests/

# Run a single test
.venv/bin/pytest tests/test_compose_tools.py::ComposeToolTests::test_create_rich_email_draft_writes_multipart_eml

# Run the MCP server locally (stdio)
.venv/bin/python plugin/apple_mail_mcp.py
.venv/bin/python plugin/apple_mail_mcp.py --read-only

# Install the plugin locally from this checkout
claude plugin marketplace add .
claude plugin install apple-mail@apple-mail-mcp
```

There is no lint/format config — don't introduce one without asking.

## Architecture

**Entry → registration → AppleScript bridge.** Understanding this flow is required before changing tool behavior:

1. **Entry** (`plugin/apple_mail_mcp/__main__.py`): parses `--read-only`, starts an **orphan watcher thread**, then imports `apple_mail_mcp` (which triggers tool registration) and calls `mcp.run()`. In read-only mode, the send tools (`compose_email`, `reply_to_email`, `forward_email`) are removed from the registered tool set via `mcp.remove_tool()` *after* import — keep that order.
2. **Tool registration** (`plugin/apple_mail_mcp/__init__.py`): importing the six modules under `tools/` (`inbox`, `search`, `compose`, `manage`, `analytics`, `smart_inbox`) is what registers `@mcp.tool()` decorators on the shared `mcp` instance from `server.py`. New tools must be in one of those modules **and** the module must be imported here, or they won't appear. Total registered tools = **26** (verify with `grep -c "^@mcp.tool" plugin/apple_mail_mcp/tools/*.py`).
3. **Shared server state** (`server.py`): the single `FastMCP` instance, the `USER_EMAIL_PREFERENCES` and `DEFAULT_MAIL_ACCOUNT` env-var strings, and the `READ_ONLY` flag live here. Tool modules import from `server`, not the other way around.
4. **AppleScript bridge** (`core.py`): every Mail.app interaction goes through `run_applescript()` (osascript via stdin pipe). All user-supplied strings going into AppleScript **must** flow through `escape_applescript()` — backslashes, quotes, newlines, tabs, and Unicode line/paragraph separators are all sources of injection or syntax errors. Output from AppleScript is run through `_sanitize_for_json()` to strip control chars while preserving Unicode. `run_applescript()` raises `core.AppleScriptTimeout` on `subprocess.TimeoutExpired` — public tools should catch it and return a structured error string rather than letting it propagate.
5. **Preference injection**: the `@inject_preferences` decorator in `core.py` appends `USER_EMAIL_PREFERENCES` to a tool's docstring at import time, so the model sees user context in the tool description. Apply it to user-facing tools that should respect preferences.

## Tool-implementation conventions (locked in 3.1.5)

The four anti-patterns below caused real production timeouts on a 24K-message Exchange inbox. Every new tool that touches Mail.app must follow these rules. The modernized modules (`search.py`, `inbox.py`, `smart_inbox.py`, `manage.py`, `analytics.py`, `compose.py`) are the templates.

### Performance defaults

- **Recent-window default**: any tool that searches or lists takes `recent_days: float = 2.0` (48h). Translate to a `date received >= cutoffDate` clause inside the `whose` filter. Pass `recent_days=0` to disable. `list_inbox_emails` uses `max_emails: int = 50` instead of `0` (unbounded).
- **AppleScript-side caps, not Python-side slicing.** Never write `every message of mailbox` and then `items startIndex thru endIndex` in Python. Either build a `whose` clause and `items 1 thru N of (every message of mailbox whose …)`, or use `messages 1 thru N of mailbox` directly. Mail returns inbox messages newest-first.
- **`ignoring case … end ignoring`** for case-insensitive comparisons. Never call out to `do shell script "echo … | tr '[:upper:]' '[:lower:]'"` per message — the deprecated `LOWERCASE_HANDLER` was removed in 3.1.5 for that exact reason. Don't reintroduce it.
- **Push date filters unconditionally** into the `whose` clause when the caller provides `date_from`/`date_to`. Don't gate them on the presence of other filters.

### Account scoping

- **`DEFAULT_MAIL_ACCOUNT`**: every tool that takes an `account` parameter must (a) default it to `Optional[str] = None`, (b) at the top of the function fall back to `_server.DEFAULT_MAIL_ACCOUNT` if `account is None`, (c) return a structured error if neither is set. `synchronize_account` is the documented exception — `account=None` there means "all accounts". `inbox_dashboard` is also exempt (always cross-account).
- **`all_accounts: bool = False`** is the explicit override for tools that need to span every configured account even when `DEFAULT_MAIL_ACCOUNT` is set.

### Async + per-account isolation

- Tools that fan out across accounts should be `async def` and dispatch each account via `asyncio.to_thread(run_applescript, …)` + `asyncio.gather(..., return_exceptions=True)`. Wall time becomes ≈ slowest single account, not sum.
- Pair this with a per-account `AppleScriptTimeout` catch and append failing accounts to an `errors: list[str]` field in the returned JSON. Partial results > total failure.
- Single-account tools (`compose_email`, `move_email`, `manage_drafts`, `get_top_senders`, etc.) stay sync. Don't add `async def` ceremony where it doesn't pay.

### Timeout exposure

- Every modernized tool takes `timeout: Optional[int] = None` and threads it into `run_applescript(..., timeout=timeout)`. The model can extend the budget when it knows an account is slow. Wrap the call in `try/except core.AppleScriptTimeout` and return a structured error message naming the account and the elapsed budget.

### Escaping

- User-supplied strings reaching AppleScript **always** go through `core.escape_applescript()`. This is non-negotiable — missing it is a script-injection and syntax-corruption bug regardless of where the string came from.

### What NOT to do

- Don't add `subprocess.run(["osascript", …])` calls that bypass `run_applescript()`. Two pre-existing call sites in `compose.py` (`_send_html_email`, the direct osascript paths for reply/forward) are tracked for migration; don't add new ones.
- Don't write `except: pass` or `except Exception: pass` — collect errors into a list the caller can see.
- Don't materialize a full mailbox into a Python list before filtering. If the audit logs in a future debug session show `every message of …` without a `whose` cap, that's the bug.

### Orphan watcher

`__main__._start_orphan_watcher` is a workaround for [modelcontextprotocol/python-sdk#526](https://github.com/modelcontextprotocol/python-sdk/issues/526): when the MCP client exits without closing stdin, the server keeps polling Mail.app via Apple Events and silently relaunches Mail after the user quits it. The watcher captures the initial PPID and self-terminates with `os._exit(0)` when reparented. `get_ppid` and `exit_fn` are injectable for the tests in `test_orphan_watcher.py` — keep those seams when editing.

### Read-only enforcement

`--read-only` removes send tools from the registry; it does **not** branch inside the tool implementations. `manage_drafts` stays registered but blocks the "send" action internally. If you add a new email-sending capability, extend the `SEND_TOOLS` list in `__main__.py` rather than adding a runtime check.

### Rich HTML drafts

`create_rich_email_draft` (in `tools/compose.py`) generates a multipart `.eml` file on disk and opens it with Mail.app, rather than injecting HTML into AppleScript's `content` property (which Mail stores as literal markup). When working on draft-related tools, prefer this approach for anything HTML.

## Versioning

Version is duplicated across **five** files — bump all of them together when releasing. Top-level marketplace `metadata.version` (1.0.0) is separate and describes the marketplace manifest itself; don't touch it.

- `pyproject.toml` → `[project].version`
- `plugin/.claude-plugin/plugin.json` → `version`
- `.claude-plugin/marketplace.json` → `plugins[0].version`
- `server.json` → both top-level `version` AND `packages[0].version`
- `apple-mail-mcpb/manifest.json` → `version`

Tool-count claims also drift. The description fields in `plugin.json`, `marketplace.json`, and `apple-mail-mcpb/manifest.json` advertise a tool count; the mcpb manifest also embeds the full `tools[]` array with descriptions. Both must stay in sync with `grep -c "^@mcp.tool" plugin/apple_mail_mcp/tools/*.py`. After adding/removing a tool, run the plugin-validator agent — it cross-references the array against the registry.

## Plugin-dev agents are the experts here

This repo **is** a Claude Code plugin (`plugin/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`). For any work that touches the plugin shell, MCP wiring, skills, agents, commands, hooks, or manifests, defer to the `plugin-dev:*` agents and skills — they hold current authoritative knowledge that overrides anything you remember about plugin authoring:

- **`plugin-dev:plugin-validator`** — run after any change to `plugin.json`, `marketplace.json`, `.mcp.json`, command/skill/agent frontmatter, or directory layout. Treat its findings as blocking before declaring work done.
- **`plugin-dev:skill-reviewer`** — run after creating or editing any skill under `plugin/skills/` (currently `email-management`, more planned). Use it on the description/frontmatter specifically — those are what determine whether the skill is ever triggered.
- **`plugin-dev:agent-creator`** — use when adding a new agent to the plugin. Don't hand-author agent frontmatter from memory.
- **`plugin-dev:*` skills** (`mcp-integration`, `skill-development`, `command-development`, `agent-development`, `hook-development`, `plugin-structure`, `plugin-settings`) — invoke the matching skill *before* designing or editing that kind of component. The MCP server logic itself (Python under `plugin/apple_mail_mcp/`) is normal Python work and doesn't need these — but the *wrapper* around it does.

Server-side performance/correctness (AppleScript, FastMCP tool implementations, timeouts) is plain Python engineering — use `Explore` / general agents for that, not plugin-dev.

## Skill authoring convention (lock in before adding new skills)

Every skill under `plugin/skills/` follows the same shape so the four planned skills (`email-management` shipped, `email-drafting`, `inbox-triage`, `email-attachments` planned) trigger crisply without competing:

- **Directory name == frontmatter `name`.** No `-expert` or marketing suffix. `email-management/` ↔ `name: email-management`.
- **`description` is third-person, scenario-rich, and ends with "Do NOT use for X (see <sibling>)".** The "Use when the user…" phrasing with 4-6 quoted trigger phrases is what determines if the skill triggers; the "Do NOT use for…" clause is the only reliable defense against sibling-skill collisions. Each description also names the 3-5 MCP tools most central to it so the model can pattern-match on tool intent, not just topic.
- **Body is imperative/infinitive.** "Start with `get_inbox_overview()`" — never "You should…" or "Claude should…". The body addresses a model executing the workflow, not a person reading a guide.
- **SKILL.md stays 1,500–2,000 words.** Detail goes to `references/<topic>.md`, working code to `examples/`, utility scripts to `scripts/`. Link them from a final "Additional Resources" section so the model knows they exist.
- **Top of body always has:** (1) purpose, (2) when-to-use / when-NOT-to-use block, (3) performance defaults the model must respect (e.g. `search_emails` defaults to last 48h, `DEFAULT_MAIL_ACCOUNT` scoping), (4) decision tree pointing to sibling skills, (5) red-flag table for destructive ops.
- **No persona openers.** Skip "You are an expert…". The skill is procedural knowledge, not a character.
- **Verify with the plugin-dev experts before merging a skill change.** Run `plugin-dev:skill-reviewer` on the description and body; the description quality is what makes or breaks triggering.

When in doubt, study the rewritten `email-management` skill — it is the template.

### Skills only — no new slash commands

For this plugin, **new entry points ship as skills only**. The existing `plugin/commands/email-management.md` stays since it shipped, but the three planned siblings (`email-drafting`, `inbox-triage`, `email-attachments`) and any future entry points are skill-only. Claude Code often auto-converts plugin commands to skills at install time, so authoring both is duplicative noise.

## Platform constraints

- macOS only. Tests that touch `run_applescript` should mock `subprocess.run` (see `tests/test_modernization_3_1_5.py` and `tests/test_mail_search_tools.py` for the established pattern: patch `subprocess.run` with a `side_effect` that captures the script via `kwargs["input"]`).
- Targets Python 3.10+ per `pyproject.toml`. `start_mcp.sh` currently still prints "Python 3.7 or later" — that's a stale check; bump when next touching the launcher.
- Apple Mail must be configured and granted Automation + Mail Data Access permissions — the server cannot grant these itself; surface a clear error rather than retrying.
- Async tools use `asyncio.to_thread` to run the synchronous `run_applescript` in a worker thread. Don't try to make `run_applescript` itself async — `subprocess.run` is the cleanest interface for stdin-piped osascript.

## Where to track work

- **In-conversation work** uses the `TaskCreate`/`TaskUpdate` task list — that's the ephemeral, current-session view.
- **Cross-session backlog** lives in `tasks/todo.md` at the repo root. Add new ideas there as they surface (architecture cleanups, deferred audits, sibling skills, hardening leftovers). Prune completed lines. This file is the source of truth for "what's next" between sessions.

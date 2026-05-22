# Agent Live Testing (Apple Mail MCP)

Use the repo-owned CLI (`.venv/bin/apple-mail`) to verify changes against real Mail.app immediately after edits. This bypasses the slow generated mcporter wrapper and calls the same Python tool functions as the MCP server.

## Setup

```bash
cd /path/to/apple-mail-mcp
python3 -m venv .venv
.venv/bin/pip install -e . pytest
```

Optional but recommended for faster iteration:

```bash
export DEFAULT_MAIL_ACCOUNT="Your Mail Account Name"
```

When set, `perf-test`, `quick-check`, and `smoke-test` use this account instead of the first configured account.

## Permissions (macOS)

Mail.app must be configured and the terminal (or IDE) running the CLI needs:

- **Automation** — allow control of Mail
- **Mail Data Access** — allow reading mail data

If a command hangs or returns permission errors, open **System Settings → Privacy & Security** and grant access to Terminal, iTerm, or Cursor.

## Safe commands (read-only / dry-run)

### Batteries

| Command | What it exercises |
|---------|-------------------|
| `quick-check` | metadata + no-hit search + inbox (~30s target) |
| `perf-test --quick` | same as `quick-check` |
| `perf-test` | full battery: dry-run move/trash, overview, bad-account fast-fail, dashboard metadata |
| `smoke-test` | accounts, inbox, no-hit search, invalid-account error, draft-safe send block |

Add `--verbose-sensitive` to `perf-test` / `quick-check` to include account names in perf samples (default output redacts them).

### Individual safe probes

```bash
.venv/bin/apple-mail accounts --json
.venv/bin/apple-mail addresses --json
.venv/bin/apple-mail mailboxes --account "$DEFAULT_MAIL_ACCOUNT" --json
.venv/bin/apple-mail unread --account "$DEFAULT_MAIL_ACCOUNT" --summary --json
.venv/bin/apple-mail inbox --account "$DEFAULT_MAIL_ACCOUNT" --limit 2 --json
.venv/bin/apple-mail search --account "$DEFAULT_MAIL_ACCOUNT" --query NO_SUCH_SUBJECT_APPLE_MAIL_CLI_SMOKE_20991231 --json
.venv/bin/apple-mail show --account "$DEFAULT_MAIL_ACCOUNT" --id 12345 --no-content --json
.venv/bin/apple-mail overview --account "$DEFAULT_MAIL_ACCOUNT" --format compact
.venv/bin/apple-mail needs-response --account "$DEFAULT_MAIL_ACCOUNT" --days 2
.venv/bin/apple-mail awaiting-reply --account "$DEFAULT_MAIL_ACCOUNT" --days 7
.venv/bin/apple-mail top-senders --account "$DEFAULT_MAIL_ACCOUNT" --days 30
.venv/bin/apple-mail statistics --account "$DEFAULT_MAIL_ACCOUNT" --scope account_overview --days 7
.venv/bin/apple-mail move-dry-run --account "$DEFAULT_MAIL_ACCOUNT" --to Archive --subject NO_SUCH_SUBJECT_APPLE_MAIL_CLI_SMOKE_20991231
.venv/bin/apple-mail trash-dry-run --account "$DEFAULT_MAIL_ACCOUNT" --subject NO_SUCH_SUBJECT_APPLE_MAIL_CLI_SMOKE_20991231
.venv/bin/apple-mail drafts list --account "$DEFAULT_MAIL_ACCOUNT"
```

## After each change

**Fast loop (~30–60s):**

```bash
.venv/bin/apple-mail quick-check --json
```

**Full performance gate:**

```bash
.venv/bin/apple-mail perf-test --account "$DEFAULT_MAIL_ACCOUNT" --json
```

Exit code is non-zero if any threshold is breached.

### Thresholds (full `perf-test`)

| Case | Threshold |
|------|-----------|
| metadata (accounts + addresses + mailboxes) | < 2s |
| no-hit search | < 3s |
| inbox (limit 2) | < 5s |
| dry-run move | < 5s |
| dry-run trash | < 5s |
| overview (compact, metadata-only) | < 10s |
| bad_account (invalid name fast-fail) | < 2s |
| dashboard_metadata (unread + recent, no preview) | < 5s |

Output is redacted by default: counts and char lengths only; account names, subjects, senders, and bodies are omitted unless `--verbose-sensitive` is set.

## Unit tests vs live Mail

CI runs mocked pytest + manifest validation only:

```bash
bash tools/validate_manifests.sh
.venv/bin/pytest tests/ -q
```

Optional local hook (manifest drift + pytest, no live Mail):

```bash
bash tools/pre-commit-validate.sh
# or: ln -sf ../../tools/pre-commit-validate.sh .git/hooks/pre-commit
```

Live Mail verification is manual on macOS with Mail.app running.

## MCP config for agents

### MCP env vars

The Claude plugin starts the server via `mcpServers.apple-mail` → `${CLAUDE_PLUGIN_ROOT}/start_mcp.sh` (see `plugin/.claude-plugin/plugin.json`). Optional environment variables:

| Variable | Purpose |
|----------|---------|
| `DEFAULT_MAIL_ACCOUNT` | Exact Mail account name (e.g. `Work`, `Gmail`). When set, most tools default to this account instead of fanning out across every account — largest perf win on multi-account mailboxes. |
| `USER_EMAIL_PREFERENCES` | Free-text workflow hints injected into preference-aware tool docstrings (e.g. "Prefer Archive over Trash, cap lists at 25"). |

Example `env` block for a manual MCP config (also emitted by `apple-mail mcp-config` if you add `env` yourself):

```json
"env": {
  "DEFAULT_MAIL_ACCOUNT": "Work",
  "USER_EMAIL_PREFERENCES": "Prefer Archive over Trash; default triage window 7 days"
}
```

Full setup examples: [README — Default Mail Account & User Preferences](../README.md#default-mail-account).

Generate draft-safe MCP wiring from the repo checkout:

```bash
.venv/bin/apple-mail mcp-config --repo "$(pwd)"
```

This adds `--draft-safe` so send tools stay blocked during agent testing.

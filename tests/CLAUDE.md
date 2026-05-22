# tests/ — pytest suite

Mocked unit tests for the Apple Mail MCP server. **221 tests** (`pytest tests/ --collect-only -q`). CI runs on Ubuntu with no Mail.app — every test mocks AppleScript or tests pure Python.

New tests and perf gates: delegate to a **`shell`** or **`generalPurpose`** subagent; parent runs full suite after merge. See root [`CLAUDE.md`](../CLAUDE.md) § Agent orchestration.

```bash
.venv/bin/pytest tests/
.venv/bin/pytest tests/test_cli.py -q
```

Dev venv: root `.venv/` (editable install). See root [`CLAUDE.md`](../CLAUDE.md).

## conftest.py — validate_account_name

Autouse fixture `_pass_through_known_test_accounts` patches `validate_account_name` in `core` and every tool module. `account='Work'` passes without real Mail; `account='Missing'` returns structured `account_not_found`. Most tool tests depend on this.

## Mock patterns

- **AppleScript capture** — patch `subprocess.run` with `side_effect` reading script from `kwargs["input"]`. Templates: `test_modernization_3_1_5.py` (`_ScriptCapture`), `test_mail_search_tools.py`, `test_compose_tools.py`.
- **Pure helpers** — `test_bulk_helpers.py`: `escape_applescript`, filters, mailbox refs (no subprocess mock).
- **Registry / CLI** — `test_read_only_registry.py`, `test_cli.py`, `test_cli_perf.py` (perf thresholds, `--include-analysis`, profiles; no live Mail).
- **Wrapper surface** — `test_wrapper_surface.py`: mocks `check_wrapper_surface.py` help parsing (no generated wrapper required).
- **Infra** — `test_orphan_watcher.py` (injectable seams); `test_validate_manifests.py`.

## Test files

`test_bulk_helpers` · `test_mail_search_tools` · `test_inbox_tools` · `test_compose_tools` · `test_modernization_3_1_5` · `test_phase_a_fixes` · `test_phase_2_scan_hardening` · `test_get_inbox_overview_json` · `test_get_statistics_json` · `test_read_only_registry` · `test_cli` · `test_cli_perf` · `test_wrapper_surface` · `test_orphan_watcher` · `test_validate_manifests`

## CI vs live Mail

`.github/workflows/ci.yml`: `validate_manifests.sh` + `pytest tests/ -q`. Live verification: [`docs/AGENT_LIVE_TESTING.md`](../docs/AGENT_LIVE_TESTING.md). Local hook: [`tools/pre-commit-validate.sh`](../tools/pre-commit-validate.sh).

## Related

[`docs/CLAUDE-conventions.md`](../docs/CLAUDE-conventions.md) · [`tools/CLAUDE.md`](../tools/CLAUDE.md) · [`plugin/apple_mail_mcp/`](../plugin/apple_mail_mcp/)

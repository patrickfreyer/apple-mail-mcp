"""Tests for perf-test / quick-check CLI logic (mocked, no live Mail)."""

import json
import time
import unittest
from unittest.mock import patch

from apple_mail_mcp import cli


class PerfThresholdTests(unittest.TestCase):
    def test_evaluate_perf_case_passes_under_threshold(self):
        case = cli.PerfCase(
            name="fast",
            category="metadata",
            threshold_ms=2000,
            runner=lambda: {"items": []},
        )
        with patch.object(cli, "_timed_call", return_value=({"items": []}, 150.0)):
            result = cli._evaluate_perf_case(case)

        self.assertTrue(result["pass"])
        self.assertEqual(result["duration_ms"], 150.0)
        self.assertEqual(result["threshold_ms"], 2000)
        self.assertEqual(result["sample"], {"items": {"count": 0}})

    def test_evaluate_perf_case_fails_over_threshold(self):
        case = cli.PerfCase(
            name="slow",
            category="inbox",
            threshold_ms=5000,
            runner=lambda: {"emails": []},
        )
        with patch.object(cli, "_timed_call", return_value=({"emails": []}, 6200.5)):
            result = cli._evaluate_perf_case(case)

        self.assertFalse(result["pass"])
        self.assertEqual(result["duration_ms"], 6200.5)

    def test_evaluate_perf_case_fails_on_tool_error_string(self):
        case = cli.PerfCase(
            name="bad_account",
            category="inbox",
            threshold_ms=5000,
            runner=lambda: "Error: account_not_found",
        )
        with patch.object(
            cli,
            "_timed_call",
            return_value=("Error: account_not_found", 100.0),
        ):
            result = cli._evaluate_perf_case(case)

        self.assertFalse(result["pass"])
        self.assertIn("error", result)

    def test_evaluate_perf_case_passes_expected_account_error(self):
        case = cli.PerfCase(
            name="bad_account",
            category="bad_account",
            threshold_ms=2000,
            runner=lambda: '{"error":"account_not_found"}',
            expect_error=True,
        )
        payload = {"error": "account_not_found", "account": "Missing"}
        with patch.object(cli, "_timed_call", return_value=(payload, 150.0)):
            result = cli._evaluate_perf_case(case)

        self.assertTrue(result["pass"])

    def test_redact_hides_account_names_by_default(self):
        sample = {
            "accounts": ["Work", "Gmail"],
            "addresses": {"Work": ["a@b.com"]},
            "account": "Work",
        }
        redacted = cli._redact(sample)
        self.assertEqual(redacted["accounts"], {"count": 2})
        self.assertEqual(redacted["addresses"], {"account_count": 1})
        self.assertEqual(redacted["account"], "(redacted)")

    def test_redact_verbose_sensitive_preserves_values(self):
        sample = {"accounts": ["Work"], "account": "Work"}
        self.assertEqual(cli._redact(sample, verbose_sensitive=True), sample)

    def test_evaluate_perf_case_catches_exceptions(self):
        case = cli.PerfCase(
            name="boom",
            category="metadata",
            threshold_ms=2000,
            runner=lambda: (_ for _ in ()).throw(RuntimeError("Mail unavailable")),
        )
        result = cli._evaluate_perf_case(case)
        self.assertFalse(result["pass"])
        self.assertIsNone(result["duration_ms"])
        self.assertIn("Mail unavailable", result["error"])


class PerfBatteryTests(unittest.TestCase):
    def test_build_perf_cases_quick_subset(self):
        with patch.object(cli, "_mailbox_count", return_value=9):
            cases = cli.build_perf_cases("Work", quick=True)
        self.assertEqual(len(cases), 3)
        self.assertEqual([case.name for case in cases], ["metadata", "no_hit_search", "inbox"])

    def test_build_perf_cases_full_battery(self):
        with patch.object(cli, "_mailbox_count", return_value=9):
            cases = cli.build_perf_cases("Work", quick=False)
        self.assertEqual(len(cases), 8)
        self.assertEqual(cases[-1].name, "dashboard_metadata")
        self.assertEqual(cases[-2].name, "bad_account")
        self.assertTrue(cases[-2].expect_error)

    def test_build_perf_cases_include_analysis(self):
        with patch.object(cli, "_mailbox_count", return_value=9):
            cases = cli.build_perf_cases("Work", quick=False, include_analysis=True)
        self.assertEqual(len(cases), 12)
        names = [case.name for case in cases]
        self.assertIn("needs_response", names)
        self.assertIn("awaiting_reply", names)
        self.assertIn("top_senders", names)
        self.assertIn("statistics_overview", names)

    def test_build_perf_cases_quick_ignores_analysis(self):
        with patch.object(cli, "_mailbox_count", return_value=9):
            cases = cli.build_perf_cases("Work", quick=True, include_analysis=True)
        self.assertEqual(len(cases), 3)

    def test_build_perf_cases_metadata_uses_scaled_threshold(self):
        with patch.object(cli, "_mailbox_count", return_value=194):
            cases = cli.build_perf_cases("Work", quick=True, mailbox_count=194)
        self.assertEqual(cases[0].threshold_ms, cli.metadata_threshold_ms(194))

    def test_metadata_threshold_ms(self):
        self.assertEqual(cli.metadata_threshold_ms(9), 2000)
        self.assertEqual(cli.metadata_threshold_ms(20), 2000)
        self.assertEqual(cli.metadata_threshold_ms(194), 8090)

    def test_resolve_perf_thresholds_production_overview(self):
        thresholds = cli.resolve_perf_thresholds("production")
        self.assertEqual(thresholds["overview"], 15000)

    def test_resolve_perf_thresholds_light_overview(self):
        thresholds = cli.resolve_perf_thresholds("light")
        self.assertEqual(thresholds["overview"], 10000)

    def test_run_perf_battery_aggregates_results(self):
        def fake_evaluate(case: cli.PerfCase, *, verbose_sensitive: bool = False) -> dict:
            durations = {
                "metadata": 100.0,
                "no_hit_search": 200.0,
                "inbox": 300.0,
            }
            return {
                "name": case.name,
                "category": case.category,
                "duration_ms": durations[case.name],
                "threshold_ms": case.threshold_ms,
                "pass": True,
                "sample": {},
            }

        with (
            patch.object(cli, "_resolve_test_account", return_value=("Work", None)),
            patch.object(cli, "build_perf_cases", return_value=[
                cli.PerfCase("metadata", "metadata", 2000, lambda: None),
                cli.PerfCase("no_hit_search", "no_hit_search", 3000, lambda: None),
                cli.PerfCase("inbox", "inbox", 5000, lambda: None),
            ]),
            patch.object(cli, "_evaluate_perf_case", side_effect=fake_evaluate),
        ):
            payload = cli.run_perf_battery("Work", quick=True)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["account"], "Work")
        self.assertTrue(payload["quick"])
        self.assertEqual(payload["total_duration_ms"], 600.0)
        self.assertEqual(len(payload["cases"]), 3)

    def test_run_perf_battery_fails_when_any_case_fails(self):
        with (
            patch.object(cli, "_resolve_test_account", return_value=("Work", None)),
            patch.object(cli, "build_perf_cases", return_value=[
                cli.PerfCase("metadata", "metadata", 2000, lambda: None),
            ]),
            patch.object(
                cli,
                "_evaluate_perf_case",
                return_value={
                    "name": "metadata",
                    "category": "metadata",
                    "duration_ms": 2500.0,
                    "threshold_ms": 2000,
                    "pass": False,
                    "sample": {},
                },
            ),
        ):
            payload = cli.run_perf_battery("Work", quick=True)

        self.assertFalse(payload["ok"])

    def test_run_perf_battery_no_account(self):
        with patch.object(cli, "_resolve_test_account", return_value=(None, "No Mail accounts configured")):
            payload = cli.run_perf_battery(None)

        self.assertFalse(payload["ok"])
        self.assertIsNone(payload["account"])
        self.assertEqual(payload["error"], "No Mail accounts configured")
        self.assertEqual(payload["cases"], [])


class PerfCliCommandTests(unittest.TestCase):
    def test_perf_test_json_exit_zero_on_pass(self):
        payload = {
            "ok": True,
            "account": "Work",
            "quick": False,
            "thresholds_ms": cli.PERF_THRESHOLDS_MS,
            "total_duration_ms": 900.0,
            "cases": [],
        }
        with (
            patch.object(cli, "run_perf_battery", return_value=payload),
            patch("builtins.print") as mock_print,
        ):
            code = cli.main(["perf-test", "--account", "Work", "--json"])

        self.assertEqual(code, 0)
        printed = json.loads(mock_print.call_args.args[0])
        self.assertTrue(printed["ok"])

    def test_perf_test_exit_one_on_failure(self):
        payload = {
            "ok": False,
            "account": "Work",
            "quick": True,
            "thresholds_ms": cli.PERF_THRESHOLDS_MS,
            "total_duration_ms": 4000.0,
            "cases": [
                {
                    "name": "inbox",
                    "category": "inbox",
                    "duration_ms": 6000.0,
                    "threshold_ms": 5000,
                    "pass": False,
                    "sample": {},
                }
            ],
        }
        with (
            patch.object(cli, "run_perf_battery", return_value=payload),
            patch("builtins.print"),
        ):
            code = cli.main(["perf-test", "--quick", "--json"])

        self.assertEqual(code, 1)

    def test_quick_check_runs_quick_battery(self):
        with (
            patch.object(cli, "run_perf_battery", return_value={"ok": True, "cases": []}) as mock_run,
            patch("builtins.print"),
        ):
            code = cli.main(["quick-check", "--account", "Work"])

        self.assertEqual(code, 0)
        mock_run.assert_called_once_with(
            "Work",
            quick=True,
            include_analysis=False,
            allow_heavy_mail_scan=False,
            profile="production",
            verbose_sensitive=False,
        )

    def test_perf_test_include_analysis_requires_heavy_scan_opt_in(self):
        with patch("builtins.print"):
            code = cli.main(["perf-test", "--include-analysis", "--profile", "light", "--json"])

        self.assertEqual(code, 1)

    def test_perf_test_include_analysis_flag_with_heavy_scan_opt_in(self):
        with (
            patch.object(cli, "run_perf_battery", return_value={"ok": True, "cases": []}) as mock_run,
            patch("builtins.print"),
        ):
            code = cli.main(
                [
                    "perf-test",
                    "--include-analysis",
                    "--allow-heavy-mail-scan",
                    "--profile",
                    "light",
                    "--json",
                ]
            )

        self.assertEqual(code, 0)
        mock_run.assert_called_once_with(
            None,
            quick=False,
            include_analysis=True,
            allow_heavy_mail_scan=True,
            profile="light",
            verbose_sensitive=False,
        )

    def test_resolve_test_account_prefers_explicit(self):
        with patch("apple_mail_mcp.tools.inbox.list_accounts", return_value=["Personal"]):
            account, err = cli._resolve_test_account("Work")
        self.assertEqual(account, "Work")
        self.assertIsNone(err)

    def test_resolve_test_account_uses_default_env(self):
        import apple_mail_mcp.server as server

        with (
            patch.object(server, "DEFAULT_MAIL_ACCOUNT", "Gmail"),
            patch("apple_mail_mcp.tools.inbox.list_accounts", return_value=["Personal"]),
        ):
            account, err = cli._resolve_test_account(None)

        self.assertEqual(account, "Gmail")
        self.assertIsNone(err)

    def test_timed_call_measures_elapsed(self):
        def slow_fn():
            time.sleep(0.01)
            return "done"

        result, elapsed_ms = cli._timed_call(slow_fn)
        self.assertEqual(result, "done")
        self.assertGreaterEqual(elapsed_ms, 10.0)

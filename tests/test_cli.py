"""Tests for the repo-owned apple-mail CLI."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apple_mail_mcp import cli


class AppleMailCliTests(unittest.TestCase):
    def test_accounts_json_prints_structured_output(self):
        with (
            patch(
                "apple_mail_mcp.tools.inbox.list_accounts",
                return_value=["Work", "Personal"],
            ),
            patch("builtins.print") as mock_print,
        ):
            code = cli.main(["accounts", "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(mock_print.call_args.args[0])
        self.assertEqual(payload, ["Work", "Personal"])

    def test_search_query_maps_to_subject_keyword(self):
        captured = {}

        def fake_search(**kwargs):
            captured.update(kwargs)
            return '{"items":[]}'

        with (
            patch("apple_mail_mcp.tools.search.search_emails", side_effect=fake_search),
            patch("builtins.print"),
        ):
            code = cli.main(
                [
                    "search",
                    "--account",
                    "Work",
                    "--query",
                    "invoice",
                    "--limit",
                    "3",
                    "--json",
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(captured["account"], "Work")
        self.assertEqual(captured["subject_keyword"], "invoice")
        self.assertEqual(captured["limit"], 3)
        self.assertEqual(captured["output_format"], "json")

    def test_show_calls_exact_id_tool(self):
        captured = {}

        def fake_show(**kwargs):
            captured.update(kwargs)
            return '{"item":null}'

        with (
            patch("apple_mail_mcp.tools.search.get_email_by_id", side_effect=fake_show),
            patch("builtins.print"),
        ):
            code = cli.main(
                [
                    "show",
                    "--account",
                    "Work",
                    "--id",
                    "123",
                    "--no-content",
                    "--json",
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(captured["message_id"], "123")
        self.assertFalse(captured["include_content"])

    def test_draft_reads_body_file_and_defaults_to_draft_mode(self):
        captured = {}

        def fake_compose(**kwargs):
            captured.update(kwargs)
            return "drafted"

        with tempfile.TemporaryDirectory() as tmpdir:
            body_file = Path(tmpdir) / "body.txt"
            body_file.write_text("Hello from file")
            with (
                patch(
                    "apple_mail_mcp.tools.compose.compose_email",
                    side_effect=fake_compose,
                ),
                patch("builtins.print"),
            ):
                code = cli.main(
                    [
                        "draft",
                        "--account",
                        "Work",
                        "--to",
                        "person@example.com",
                        "--subject",
                        "Subject",
                        "--body-file",
                        str(body_file),
                    ]
                )

        self.assertEqual(code, 0)
        self.assertEqual(captured["body"], "Hello from file")
        self.assertEqual(captured["mode"], "draft")

    def test_draft_forwards_signature_name_to_compose_email(self):
        captured = {}

        def fake_compose(**kwargs):
            captured.update(kwargs)
            return "drafted"

        with (
            patch("apple_mail_mcp.tools.compose.compose_email", side_effect=fake_compose),
            patch("builtins.print"),
        ):
            code = cli.main(
                [
                    "draft",
                    "--account",
                    "Work",
                    "--to",
                    "person@example.com",
                    "--subject",
                    "Subject",
                    "--body",
                    "Hello",
                    "--signature-name",
                    "TU",
                ]
            )

        self.assertEqual(code, 0)
        self.assertTrue(captured["include_signature"])
        self.assertEqual(captured["signature_name"], "TU")

    def test_draft_forwards_no_signature_to_compose_email(self):
        captured = {}

        def fake_compose(**kwargs):
            captured.update(kwargs)
            return "drafted"

        with (
            patch("apple_mail_mcp.tools.compose.compose_email", side_effect=fake_compose),
            patch("builtins.print"),
        ):
            code = cli.main(
                [
                    "draft",
                    "--account",
                    "Work",
                    "--to",
                    "person@example.com",
                    "--subject",
                    "Subject",
                    "--body",
                    "Hello",
                    "--no-signature",
                ]
            )

        self.assertEqual(code, 0)
        self.assertFalse(captured["include_signature"])
        self.assertIsNone(captured["signature_name"])

    def test_mcp_config_defaults_to_draft_safe(self):
        with patch("builtins.print") as mock_print:
            code = cli.main(["mcp-config", "--repo", "/tmp/apple-mail-mcp"])

        self.assertEqual(code, 0)
        payload = json.loads(mock_print.call_args.args[0])
        args = payload["mcpServers"]["apple-mail"]["args"]
        self.assertEqual(args[0], "/tmp/apple-mail-mcp/plugin/start_mcp.sh")
        self.assertIn("--draft-safe", args)

    def test_unread_summary_calls_tool(self):
        captured = {}

        def fake_unread(**kwargs):
            captured.update(kwargs)
            return {"Work": 3}

        with (
            patch(
                "apple_mail_mcp.tools.inbox.get_mailbox_unread_counts",
                side_effect=fake_unread,
            ),
            patch("builtins.print"),
        ):
            code = cli.main(["unread", "--account", "Work", "--summary", "--json"])

        self.assertEqual(code, 0)
        self.assertTrue(captured["summary_only"])
        self.assertEqual(captured["account"], "Work")

    def test_move_dry_run_forwards_dry_run_flag(self):
        captured = {}

        def fake_move(**kwargs):
            captured.update(kwargs)
            return "preview"

        with (
            patch("apple_mail_mcp.tools.manage.move_email", side_effect=fake_move),
            patch("builtins.print"),
        ):
            code = cli.main(
                [
                    "move-dry-run",
                    "--account",
                    "Work",
                    "--to",
                    "Archive",
                    "--subject",
                    cli.NO_HIT_SUBJECT,
                ]
            )

        self.assertEqual(code, 0)
        self.assertTrue(captured["dry_run"])

    def test_smoke_test_checks_invalid_account_and_draft_safe(self):
        with (
            patch(
                "apple_mail_mcp.tools.inbox.list_accounts",
                return_value=["Work"],
            ),
            patch(
                "apple_mail_mcp.tools.inbox.list_inbox_emails",
                side_effect=lambda **kwargs: (
                    '{"error":"account_not_found","account":"'
                    + kwargs["account"]
                    + '"}'
                    if kwargs["account"] == cli.INVALID_ACCOUNT
                    else '{"emails":[]}'
                ),
            ),
            patch(
                "apple_mail_mcp.tools.search.search_emails",
                return_value='{"items":[]}',
            ),
            patch(
                "apple_mail_mcp.tools.compose._send_blocked",
                return_value="Error: Sending is disabled in draft-safe mode.",
            ),
            patch("builtins.print"),
        ):
            code = cli.main(["smoke-test", "--account", "Work", "--json"])

        self.assertEqual(code, 0)


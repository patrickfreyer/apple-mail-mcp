"""JSON output tests for get_statistics (Phase 3 staged normalization)."""

import unittest
from unittest.mock import patch

from apple_mail_mcp import server as _server
from apple_mail_mcp.core import AppleScriptTimeout
from apple_mail_mcp.tools import analytics as analytics_tools

ACCOUNT_OVERVIEW_TEXT = """\
╔══════════════════════════════════════════╗
║      EMAIL STATISTICS - Work       ║
╚══════════════════════════════════════════╝

📊 VOLUME METRICS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total Emails: 10
Unread: 2 (20%)
Read: 8 (80%)
Flagged: 1
With Attachments: 3 (30%)

👥 TOP SENDERS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
alice@example.com: 5 emails
bob@example.com: 3 emails

📁 MAILBOX DISTRIBUTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INBOX: 7 (70%)
Archive: 3 (30%)
"""

SENDER_STATS_TEXT = """\
SENDER STATISTICS

Sender: alice@example.com
Account: Work

Total emails: 4
Unread: 1
With attachments: 2
"""

MAILBOX_BREAKDOWN_TEXT = """\
MAILBOX STATISTICS

Mailbox: INBOX
Account: Work

Total messages: 100
Unread: 20
Read: 80
"""


class GetStatisticsJsonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._saved_default = _server.DEFAULT_MAIL_ACCOUNT
        _server.DEFAULT_MAIL_ACCOUNT = "Work"

    @classmethod
    def tearDownClass(cls):
        _server.DEFAULT_MAIL_ACCOUNT = cls._saved_default

    def test_invalid_output_format_returns_text_error(self):
        result = analytics_tools.get_statistics(output_format="xml")
        self.assertIsInstance(result, str)
        self.assertEqual(result, "Error: Invalid output_format. Use: text, json")

    def test_text_mode_preserves_applescript_output(self):
        with patch(
            "apple_mail_mcp.tools.analytics.run_applescript",
            return_value=ACCOUNT_OVERVIEW_TEXT,
        ):
            result = analytics_tools.get_statistics(
                account="Work",
                scope="account_overview",
                days_back=7,
            )
        self.assertIsInstance(result, str)
        self.assertEqual(result, ACCOUNT_OVERVIEW_TEXT)

    def test_account_overview_json_shape(self):
        with patch(
            "apple_mail_mcp.tools.analytics.run_applescript",
            return_value=ACCOUNT_OVERVIEW_TEXT,
        ):
            result = analytics_tools.get_statistics(
                account="Work",
                scope="account_overview",
                days_back=7,
                output_format="json",
            )

        self.assertIsInstance(result, dict)
        self.assertEqual(result["account"], "Work")
        self.assertEqual(result["scope"], "account_overview")
        self.assertEqual(result["days_back"], 7)
        self.assertEqual(result["recent_days_applied"], 7.0)
        self.assertEqual(result["errors"], [])

        stats = result["statistics"]
        self.assertEqual(stats["total_emails"], 10)
        self.assertEqual(stats["unread"], 2)
        self.assertEqual(stats["unread_percent"], 20)
        self.assertEqual(stats["read"], 8)
        self.assertEqual(stats["read_percent"], 80)
        self.assertEqual(stats["flagged"], 1)
        self.assertEqual(stats["with_attachments"], 3)
        self.assertEqual(stats["with_attachments_percent"], 30)
        self.assertEqual(
            stats["top_senders"],
            [
                {"sender": "alice@example.com", "count": 5},
                {"sender": "bob@example.com", "count": 3},
            ],
        )
        self.assertEqual(
            stats["mailbox_distribution"],
            [
                {"mailbox": "INBOX", "count": 7, "percent": 70},
                {"mailbox": "Archive", "count": 3, "percent": 30},
            ],
        )

    def test_sender_stats_json_shape(self):
        with patch(
            "apple_mail_mcp.tools.analytics.run_applescript",
            return_value=SENDER_STATS_TEXT,
        ):
            result = analytics_tools.get_statistics(
                account="Work",
                scope="sender_stats",
                sender="alice@example.com",
                days_back=14,
                output_format="json",
            )

        self.assertEqual(result["scope"], "sender_stats")
        self.assertEqual(result["sender"], "alice@example.com")
        self.assertEqual(result["recent_days_applied"], 14.0)
        self.assertEqual(
            result["statistics"],
            {
                "total_emails": 4,
                "unread": 1,
                "with_attachments": 2,
            },
        )

    def test_mailbox_breakdown_json_shape(self):
        with patch(
            "apple_mail_mcp.tools.analytics.run_applescript",
            return_value=MAILBOX_BREAKDOWN_TEXT,
        ):
            result = analytics_tools.get_statistics(
                account="Work",
                scope="mailbox_breakdown",
                mailbox="INBOX",
                days_back=30,
                output_format="json",
            )

        self.assertEqual(result["scope"], "mailbox_breakdown")
        self.assertEqual(result["mailbox"], "INBOX")
        self.assertEqual(result["recent_days_applied"], 0.0)
        self.assertEqual(
            result["statistics"],
            {
                "total_messages": 100,
                "unread": 20,
                "read": 80,
            },
        )

    def test_json_unknown_account_returns_structured_error(self):
        result = analytics_tools.get_statistics(
            account="Missing",
            output_format="json",
        )
        self.assertEqual(result["error"], "account_not_found")
        self.assertEqual(result["account"], "Missing")
        self.assertEqual(result["errors"], [])

    def test_json_missing_account_without_default(self):
        saved = _server.DEFAULT_MAIL_ACCOUNT
        _server.DEFAULT_MAIL_ACCOUNT = ""
        try:
            result = analytics_tools.get_statistics(output_format="json")
        finally:
            _server.DEFAULT_MAIL_ACCOUNT = saved

        self.assertEqual(result["error"], "account_required")
        self.assertEqual(result["errors"], [])

    def test_json_sender_required_error(self):
        result = analytics_tools.get_statistics(
            account="Work",
            scope="sender_stats",
            output_format="json",
        )
        self.assertEqual(result["error"], "sender_required")
        self.assertEqual(result["account"], "Work")

    def test_json_timeout_error(self):
        with patch(
            "apple_mail_mcp.tools.analytics.run_applescript",
            side_effect=AppleScriptTimeout(120),
        ):
            result = analytics_tools.get_statistics(
                account="Work",
                output_format="json",
            )

        self.assertEqual(result["error"], "timeout")
        self.assertEqual(result["account"], "Work")
        self.assertIn("timed out", result["message"])

    def test_json_applescript_error(self):
        with patch(
            "apple_mail_mcp.tools.analytics.run_applescript",
            return_value="Error: Mailbox not found",
        ):
            result = analytics_tools.get_statistics(
                account="Work",
                scope="mailbox_breakdown",
                output_format="json",
            )

        self.assertEqual(result["error"], "applescript_error")
        self.assertEqual(result["message"], "Error: Mailbox not found")


if __name__ == "__main__":
    unittest.main()

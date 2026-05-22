"""JSON output tests for get_inbox_overview (Stage 2 normalization)."""

import asyncio
import unittest
from unittest.mock import patch

from apple_mail_mcp.core import AppleScriptTimeout
from apple_mail_mcp.tools import inbox as inbox_tools

OVERVIEW_WORK_PAYLOAD = "\n".join(
    [
        "HEADER|||Work|||2|||10",
        "MAILBOX|||INBOX|||2",
        "RECENT|||Quarterly report|||alice@example.com|||Thursday, May 15, 2026 at 9:00:00 AM|||false",
        "RECENT|||Standup notes|||bob@example.com|||Wednesday, May 14, 2026 at 8:30:00 AM|||true",
    ]
)


def _run(coro):
    return asyncio.run(coro)


class GetInboxOverviewJsonTests(unittest.TestCase):
    def test_invalid_output_format_returns_text_error(self):
        result = _run(inbox_tools.get_inbox_overview(output_format="xml"))
        self.assertIsInstance(result, str)
        self.assertEqual(result, "Error: Invalid output_format. Use: text, compact, json")

    def test_text_mode_preserves_formatted_output(self):
        with patch(
            "apple_mail_mcp.tools.inbox.run_applescript",
            return_value=OVERVIEW_WORK_PAYLOAD,
        ):
            result = _run(
                inbox_tools.get_inbox_overview(
                    account="Work",
                    output_format="text",
                    include_suggestions=False,
                )
            )

        self.assertIsInstance(result, str)
        self.assertIn("EMAIL INBOX OVERVIEW", result)
        self.assertIn("Work: 2 unread (10 total)", result)
        self.assertIn("Quarterly report", result)

    def test_compact_mode_preserves_shorter_text(self):
        with patch(
            "apple_mail_mcp.tools.inbox.run_applescript",
            return_value=OVERVIEW_WORK_PAYLOAD,
        ):
            result = _run(
                inbox_tools.get_inbox_overview(
                    account="Work",
                    output_format="compact",
                    include_mailboxes=False,
                    include_recent=False,
                    include_suggestions=False,
                )
            )

        self.assertIsInstance(result, str)
        self.assertNotIn("EMAIL INBOX OVERVIEW", result)
        self.assertIn("Work: 2 unread", result)
        self.assertNotIn("(10 total)", result)

    def test_json_mode_returns_dict_with_stable_keys(self):
        with patch(
            "apple_mail_mcp.tools.inbox.run_applescript",
            return_value=OVERVIEW_WORK_PAYLOAD,
        ):
            result = _run(
                inbox_tools.get_inbox_overview(
                    account="Work",
                    output_format="json",
                    include_mailboxes=True,
                    include_recent=True,
                    include_suggestions=True,
                    max_recent=5,
                )
            )

        self.assertIsInstance(result, dict)
        self.assertEqual(result["output_format"], "json")
        self.assertEqual(result["account"], "Work")
        self.assertTrue(result["include_mailboxes"])
        self.assertTrue(result["include_recent"])
        self.assertTrue(result["include_suggestions"])
        self.assertEqual(result["max_recent"], 5)
        self.assertEqual(result["total_unread"], 2)
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["suggestions"])

        account_row = result["accounts"][0]
        self.assertEqual(account_row["account"], "Work")
        self.assertEqual(account_row["unread"], 2)
        self.assertEqual(account_row["total"], 10)
        self.assertEqual(account_row["mailboxes"][0]["path"], "INBOX")
        self.assertEqual(account_row["recent"][0]["subject"], "Quarterly report")
        self.assertFalse(account_row["recent"][0]["is_read"])

    def test_json_mode_omits_optional_sections_when_disabled(self):
        with patch(
            "apple_mail_mcp.tools.inbox.run_applescript",
            return_value=OVERVIEW_WORK_PAYLOAD,
        ):
            result = _run(
                inbox_tools.get_inbox_overview(
                    account="Work",
                    output_format="json",
                    include_mailboxes=False,
                    include_recent=False,
                    include_suggestions=False,
                )
            )

        account_row = result["accounts"][0]
        self.assertNotIn("mailboxes", account_row)
        self.assertNotIn("recent", account_row)
        self.assertEqual(result["suggestions"], [])

    def test_json_unknown_account_returns_structured_error(self):
        result = _run(
            inbox_tools.get_inbox_overview(
                account="Missing",
                output_format="json",
            )
        )

        self.assertEqual(result["error"], "account_not_found")
        self.assertEqual(result["account"], "Missing")
        self.assertEqual(result["accounts"], [])
        self.assertEqual(result["errors"], [])

    def test_json_account_listing_timeout(self):
        with patch(
            "apple_mail_mcp.tools.inbox._list_mail_accounts",
            side_effect=AppleScriptTimeout(30),
        ):
            result = _run(inbox_tools.get_inbox_overview(output_format="json"))

        self.assertEqual(result["error"], "account_listing_timeout")
        self.assertEqual(result["accounts"], [])
        self.assertEqual(result["errors"], ["__account_listing__"])

    def test_json_partial_timeout_records_account_in_errors(self):
        def fake_run(script, timeout=180):
            if 'account "Work"' in script:
                return OVERVIEW_WORK_PAYLOAD
            raise AppleScriptTimeout(180)

        with patch(
            "apple_mail_mcp.tools.inbox._list_mail_accounts",
            return_value=["Work", "Slow"],
        ), patch(
            "apple_mail_mcp.tools.inbox.run_applescript",
            side_effect=fake_run,
        ):
            result = _run(inbox_tools.get_inbox_overview(output_format="json"))

        self.assertEqual(result["total_unread"], 2)
        self.assertEqual(result["accounts"][0]["account"], "Work")
        self.assertEqual(result["errors"], ["Slow"])

    def test_json_empty_account_list(self):
        with patch(
            "apple_mail_mcp.tools.inbox._list_mail_accounts",
            return_value=[],
        ):
            result = _run(inbox_tools.get_inbox_overview(output_format="json"))

        self.assertEqual(result["total_unread"], 0)
        self.assertEqual(result["accounts"], [])
        self.assertEqual(result["errors"], [])


if __name__ == "__main__":
    unittest.main()

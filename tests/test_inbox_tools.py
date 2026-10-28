"""Tests for inbox listing — identity-field parity with search_emails."""

import json
import unittest
from unittest.mock import patch

from apple_mail_mcp.tools import inbox as inbox_tools


def _inbox_record(
    subject,
    sender="sender@example.com",
    date="2026-03-07T10:00:00",
    is_read=False,
    account="Work",
    message_id="123",
    internet_message_id="<abc@example.com>",
):
    return "|||".join(
        [
            subject,
            sender,
            date,
            "true" if is_read else "false",
            account,
            message_id,
            internet_message_id,
        ]
    )


class ListInboxIdentityTests(unittest.TestCase):
    def test_list_inbox_json_surfaces_message_id_and_mail_link(self):
        def fake_run(script, timeout=120):
            return _inbox_record(
                "Quarterly report",
                message_id="456",
                internet_message_id="<QwcH6OP9REaEX0pi8aR6-g@geopod-ismtpd-60>",
            )

        with patch("apple_mail_mcp.tools.inbox.run_applescript", side_effect=fake_run):
            items = json.loads(inbox_tools.list_inbox_emails(output_format="json"))

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["message_id"], "456")
        self.assertEqual(
            item["internet_message_id"], "<QwcH6OP9REaEX0pi8aR6-g@geopod-ismtpd-60>"
        )
        self.assertEqual(
            item["mail_link"],
            "message://%3CQwcH6OP9REaEX0pi8aR6-g@geopod-ismtpd-60%3E",
        )

    def test_list_inbox_json_mail_link_normalizes_missing_angle_brackets(self):
        """AppleScript returns the Message-ID without angle brackets; the
        mail_link should still wrap it (percent-encoded), like search_emails."""

        def fake_run(script, timeout=120):
            return _inbox_record("Unbracketed", internet_message_id="abc@example.com")

        with patch("apple_mail_mcp.tools.inbox.run_applescript", side_effect=fake_run):
            items = json.loads(inbox_tools.list_inbox_emails(output_format="json"))

        self.assertEqual(items[0]["internet_message_id"], "abc@example.com")
        self.assertEqual(items[0]["mail_link"], "message://%3Cabc@example.com%3E")

    def test_list_inbox_json_tolerates_legacy_records_without_identity(self):
        """A 5-field record (pre-identity format) must still parse cleanly."""

        def fake_run(script, timeout=120):
            return "Subject|||sender@example.com|||2026-03-07T10:00:00|||false|||Work"

        with patch("apple_mail_mcp.tools.inbox.run_applescript", side_effect=fake_run):
            items = json.loads(inbox_tools.list_inbox_emails(output_format="json"))

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["subject"], "Subject")
        self.assertNotIn("message_id", items[0])
        self.assertNotIn("mail_link", items[0])

    def test_list_inbox_json_script_reads_both_ids(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return ""

        with patch("apple_mail_mcp.tools.inbox.run_applescript", side_effect=fake_run):
            inbox_tools.list_inbox_emails(output_format="json")

        self.assertIn("id of aMessage", captured["script"])
        self.assertIn("message id of aMessage", captured["script"])

    def test_list_inbox_text_script_builds_mail_link(self):
        """Text output surfaces the message:// deep link too (mirrors #44)."""
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return "INBOX EMAILS - ALL ACCOUNTS"

        with patch("apple_mail_mcp.tools.inbox.run_applescript", side_effect=fake_run):
            inbox_tools.list_inbox_emails(output_format="text")

        self.assertIn("message id of aMessage", captured["script"])
        self.assertIn('"   Link: message://%3C"', captured["script"])


class AccountNameWithPipeTests(unittest.TestCase):
    """Account names may contain "|", which used to be the record delimiter."""

    NAME = "Jane Doe | Example Corp"

    def test_list_accounts_keeps_pipe_in_name(self):
        with patch(
            "apple_mail_mcp.tools.inbox.run_applescript",
            return_value="Work\n" + self.NAME + "\nGoogle",
        ) as mock_run:
            result = inbox_tools.list_accounts()

        self.assertEqual(result, ["Work", self.NAME, "Google"])
        self.assertIn("delimiters to linefeed", mock_run.call_args[0][0])

    def test_list_accounts_empty_result(self):
        with patch("apple_mail_mcp.tools.inbox.run_applescript", return_value=""):
            self.assertEqual(inbox_tools.list_accounts(), [])

    def test_list_account_addresses_keeps_pipe_in_name(self):
        with patch(
            "apple_mail_mcp.tools.inbox.run_applescript",
            return_value=self.NAME + "|||jane@example.com,j.doe@example.com",
        ):
            result = inbox_tools.list_account_addresses()

        self.assertEqual(
            result, {self.NAME: ["jane@example.com", "j.doe@example.com"]}
        )

    def test_unread_summary_keeps_pipe_and_colon_in_name(self):
        name_with_colon = "Team: Support | Example"
        with patch(
            "apple_mail_mcp.tools.inbox.run_applescript",
            return_value=(
                "Work:0\n" + self.NAME + ":7\n" + name_with_colon + ":ERROR"
            ),
        ):
            result = inbox_tools.get_mailbox_unread_counts(summary_only=True)

        self.assertEqual(
            result, {"Work": 0, self.NAME: 7, name_with_colon: -1}
        )


class InboxAccountFilterTests(unittest.TestCase):
    def test_list_inbox_text_filters_account(self):
        with patch(
            "apple_mail_mcp.tools.inbox.run_applescript", return_value=""
        ) as mock_run:
            inbox_tools.list_inbox_emails(account="Work")
        mock_run.assert_called_once()
        script = mock_run.call_args[0][0]
        self.assertIn('if accountName is "Work" then', script)
        self.assertLess(
            script.index('if accountName is "Work" then'),
            script.index("set inboxMessages to every message of inboxMailbox"),
        )
        self.assertIn("end try\n            end if\n        end repeat", script)

    def test_list_inbox_text_without_account_has_no_filter(self):
        with patch(
            "apple_mail_mcp.tools.inbox.run_applescript", return_value=""
        ) as mock_run:
            inbox_tools.list_inbox_emails()
        script = mock_run.call_args[0][0]
        self.assertNotIn("if accountName is", script)

    def test_unread_summary_filters_account(self):
        with patch(
            "apple_mail_mcp.tools.inbox.run_applescript", return_value=""
        ) as mock_run:
            inbox_tools.get_mailbox_unread_counts(account="Work", summary_only=True)
        mock_run.assert_called_once()
        script = mock_run.call_args[0][0]
        self.assertIn('if accountName is not "Work" then', script)
        self.assertIn("set shouldIncludeAccount to true", script)
        self.assertIn("set shouldIncludeAccount to false", script)
        self.assertLess(
            script.index('if accountName is not "Work" then'),
            script.index("if shouldIncludeAccount then"),
        )
        self.assertLess(
            script.index("if shouldIncludeAccount then"),
            script.index("set unreadCount to unread count of inboxMailbox"),
        )


if __name__ == "__main__":
    unittest.main()

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


if __name__ == "__main__":
    unittest.main()

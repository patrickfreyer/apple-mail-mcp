"""Tests for structured email search and bulk update helpers."""

import json
import unittest
from unittest.mock import patch

from apple_mail_mcp.tools import manage as manage_tools
from apple_mail_mcp.tools import search as search_tools


def _record_line(
    message_id,
    subject,
    internet_message_id="<abc@example.com>",
    sender="sender@example.com",
    mailbox="INBOX",
    account="Work",
    is_read=False,
    received_date="2026-03-07T10:00:00",
    content_preview="",
):
    return "|||".join(
        [
            str(message_id),
            internet_message_id,
            subject,
            sender,
            mailbox,
            account,
            "true" if is_read else "false",
            received_date,
            content_preview,
        ]
    )


class SearchToolTests(unittest.TestCase):
    def test_search_emails_pagination_consistency(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return "\n".join(
                [
                    _record_line(
                        100,
                        "Ticket 100",
                        received_date="2026-03-07T12:00:00",
                    ),
                    _record_line(
                        101,
                        "Ticket 101",
                        received_date="2026-03-07T11:00:00",
                    ),
                    _record_line(
                        102,
                        "Ticket 102",
                        received_date="2026-03-07T10:00:00",
                    ),
                ]
            )

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            response = json.loads(
                search_tools.search_emails(
                    account="Work",
                    output_format="json",
                    offset=1,
                    limit=2,
                    max_results=None,
                )
            )

        self.assertEqual(response["offset"], 1)
        self.assertEqual(response["returned"], 2)
        self.assertTrue(response["has_more"])
        self.assertEqual(response["next_offset"], 3)
        self.assertEqual(
            response["items"][0]["mail_link"],
            "message://%3Cabc@example.com%3E",
        )
        self.assertIn("set offsetRemaining to 1", captured["script"])
        self.assertIn("set collectLimit to 3", captured["script"])

    def test_search_emails_unread_only_filter(self):
        """Test that read_status='unread' adds the correct whose clause."""
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return _record_line(201, "Unread Ticket", is_read=False)

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            response = json.loads(
                search_tools.search_emails(
                    account="Work",
                    subject_keyword="Ticket",
                    read_status="unread",
                    output_format="json",
                    limit=1,
                )
            )

        self.assertEqual(len(response["items"]), 1)
        self.assertFalse(response["items"][0]["is_read"])
        self.assertIn("read status is false", captured["script"])

    def test_search_emails_builds_real_date_filters(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return _record_line(
                301,
                "Dated Ticket",
                received_date="2026-03-05T09:00:00",
            )

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            response = json.loads(
                search_tools.search_emails(
                    account="Work",
                    subject_keyword="Ticket",
                    date_from="2026-03-01",
                    date_to="2026-03-07",
                    output_format="json",
                    limit=1,
                    max_results=None,
                )
            )

        self.assertEqual(response["items"][0]["message_id"], "301")
        self.assertIn("set year of fromDate to 2026", captured["script"])
        self.assertIn("set month of fromDate to March", captured["script"])
        self.assertIn("date received >= fromDate", captured["script"])
        self.assertIn("date received <= toDate", captured["script"])

    def test_large_mailbox_search_uses_prefiltered_selection(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return ""

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            response = json.loads(
                search_tools.search_emails(
                    account="Work",
                    subject_keywords=["INC-1", "INC-2"],
                    include_content=False,
                    output_format="json",
                    limit=50,
                    max_results=None,
                )
            )

        self.assertEqual(response["items"], [])
        self.assertIn(
            "set matchingMessages to every message of currentMailbox whose",
            captured["script"],
        )
        self.assertNotIn(
            "set mailboxMessages to every message of currentMailbox", captured["script"]
        )

    def test_search_emails_returns_mail_link_from_internet_message_id(self):
        def fake_run(script, timeout=120):
            return _record_line(
                401,
                "Linked Ticket",
                internet_message_id="<QwcH6OP9REaEX0pi8aR6-g@geopod-ismtpd-60>",
            )

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            response = json.loads(
                search_tools.search_emails(
                    account="Work",
                    subject_keyword="Linked",
                    output_format="json",
                    limit=1,
                    max_results=None,
                )
            )

        self.assertEqual(
            response["items"][0]["internet_message_id"],
            "<QwcH6OP9REaEX0pi8aR6-g@geopod-ismtpd-60>",
        )
        self.assertEqual(
            response["items"][0]["mail_link"],
            "message://%3CQwcH6OP9REaEX0pi8aR6-g@geopod-ismtpd-60%3E",
        )

    def test_search_emails_mail_link_normalizes_missing_angle_brackets(self):
        """AppleScript sometimes returns the Message-ID without angle brackets;
        the mail_link should still include them (percent-encoded)."""

        def fake_run(script, timeout=120):
            return _record_line(
                402,
                "Unbracketed Ticket",
                internet_message_id="abc@example.com",
            )

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            response = json.loads(
                search_tools.search_emails(
                    account="Work",
                    subject_keyword="Unbracketed",
                    output_format="json",
                    limit=1,
                    max_results=None,
                )
            )

        self.assertEqual(
            response["items"][0]["internet_message_id"],
            "abc@example.com",
        )
        self.assertEqual(
            response["items"][0]["mail_link"],
            "message://%3Cabc@example.com%3E",
        )

    def test_search_emails_account_none_iterates_all_accounts(self):
        """When account is None, the script should iterate all accounts."""
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return ""

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            search_tools.search_emails(
                account=None,
                subject_keyword="Test",
                output_format="json",
                limit=5,
            )

        self.assertIn("set searchAccounts to every account", captured["script"])

    def test_get_email_by_id_returns_exact_message_json(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return _record_line(
                12345,
                "Exact Ticket",
                content_preview="Full body preview",
            )

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            response = json.loads(
                search_tools.get_email_by_id(
                    account="Work",
                    message_id="12345",
                    output_format="json",
                )
            )

        self.assertEqual(response["item"]["message_id"], "12345")
        self.assertEqual(response["item"]["subject"], "Exact Ticket")
        self.assertEqual(response["item"]["content_preview"], "Full body preview")
        self.assertIn("whose id is 12345", captured["script"])

    def test_get_email_by_id_rejects_non_numeric_ids(self):
        result = search_tools.get_email_by_id(
            account="Work",
            message_id="abc",
            output_format="json",
        )

        self.assertIn("message_id must be a numeric", result)

    def test_search_emails_body_text_uses_lowercase_handler(self):
        """When body_text is provided, the script should include LOWERCASE_HANDLER."""
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return ""

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            search_tools.search_emails(
                account="Work",
                body_text="invoice",
                output_format="json",
                limit=5,
            )

        self.assertIn("on lowercase(str)", captured["script"])
        self.assertIn('lowerContent contains "invoice"', captured["script"])


class ManageToolTests(unittest.TestCase):
    def test_move_email_dry_run_uses_search_helper(self):
        with patch(
            "apple_mail_mcp.tools.manage._search_mail_records",
            return_value=[
                {
                    "subject": "Ticket",
                    "sender": "sender@example.com",
                    "received_date": "2026-03-07T10:00:00",
                }
            ],
        ) as mock_search, patch(
            "apple_mail_mcp.tools.manage.run_applescript"
        ) as mock_run:
            result = manage_tools.move_email(
                account="Work",
                to_mailbox="Archive",
                subject_keyword="Ticket",
                dry_run=True,
                max_moves=1,
            )

        mock_search.assert_called_once()
        mock_run.assert_not_called()
        self.assertIn("DRY RUN - PREVIEW MOVE", result)
        self.assertIn("Would move: Ticket", result)

    def test_manage_trash_dry_run_uses_search_helper(self):
        with patch(
            "apple_mail_mcp.tools.manage._search_mail_records",
            return_value=[],
        ) as mock_search, patch(
            "apple_mail_mcp.tools.manage.run_applescript"
        ) as mock_run:
            result = manage_tools.manage_trash(
                account="Work",
                action="move_to_trash",
                subject_keyword="Ticket",
                dry_run=True,
                max_deletes=1,
            )

        mock_search.assert_called_once()
        mock_run.assert_not_called()
        self.assertIn("DRY RUN - PREVIEW TRASH", result)
        self.assertIn("TOTAL: 0", result)

    def test_update_email_status_with_message_ids_uses_exact_id_condition(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return "updated"

        with patch("apple_mail_mcp.tools.manage.run_applescript", side_effect=fake_run):
            result = manage_tools.update_email_status(
                account="Work",
                mailbox="INBOX",
                message_ids=["101", "202"],
                action="mark_read",
            )

        self.assertEqual(result, "updated")
        self.assertIn("id is 101", captured["script"])
        self.assertIn("id is 202", captured["script"])
        self.assertIn("set read status of targetMessages to true", captured["script"])


if __name__ == "__main__":
    unittest.main()

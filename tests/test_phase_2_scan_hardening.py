"""Phase 2 scan-path hardening: compose caps, timeouts."""

import unittest
from unittest.mock import patch

from apple_mail_mcp.core import AppleScriptTimeout
from apple_mail_mcp.tools import compose as compose_tools
from apple_mail_mcp.tools import inbox as inbox_tools
from apple_mail_mcp.tools import manage as manage_tools
from apple_mail_mcp.tools import search as search_tools


def _make_subprocess_result(returncode=0, stdout=b"ok", stderr=b""):
    from unittest.mock import MagicMock

    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


class ComposeScanCapTests(unittest.TestCase):
    def test_manage_drafts_list_caps_draft_enumeration(self):
        captured = []

        def fake_run(script, timeout=120):
            captured.append(script)
            return "Found 0 draft(s)"

        with patch("apple_mail_mcp.tools.compose.run_applescript", side_effect=fake_run):
            compose_tools.manage_drafts(account="Work", action="list")

        self.assertEqual(len(captured), 1)
        self.assertIn("messages 1 thru 100", captured[0])
        self.assertNotIn("every message of draftsMailbox", captured[0])

    def test_reply_to_email_subject_lookup_uses_whose_and_cap(self):
        captured = []

        def fake_run(script, timeout=120):
            captured.append(script)
            return "ok"

        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            side_effect=fake_run,
        ):
            compose_tools.reply_to_email(
                account="Work",
                subject_keyword="Invoice",
                reply_body="Thanks",
            )

        self.assertIn("items 1 thru 100", captured[0])
        self.assertIn("date received >= recentCutoffDate", captured[0])
        self.assertIn('subject contains "Invoice"', captured[0])

    def test_reply_to_email_message_id_skips_subject_scan(self):
        captured = []

        def fake_run(script, timeout=120):
            captured.append(script)
            return "ok"

        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            side_effect=fake_run,
        ):
            compose_tools.reply_to_email(
                account="Work",
                message_id="12345",
                reply_body="Thanks",
            )

        self.assertIn("whose id is 12345", captured[0])
        self.assertNotIn("items 1 thru 100", captured[0])

    def test_forward_email_subject_lookup_uses_whose_and_cap(self):
        captured = []

        def fake_run(script, timeout=120):
            captured.append(script)
            return "ok"

        with patch("apple_mail_mcp.tools.compose.run_applescript", side_effect=fake_run):
            compose_tools.forward_email(
                account="Work",
                subject_keyword="Invoice",
                to="other@example.com",
            )

        self.assertIn("items 1 thru 100", captured[0])
        self.assertIn("date received >= recentCutoffDate", captured[0])

    def test_forward_email_forwards_timeout_to_run_applescript(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["timeout"] = timeout
            return "ok"

        with patch("apple_mail_mcp.tools.compose.run_applescript", side_effect=fake_run):
            compose_tools.forward_email(
                account="Work",
                subject_keyword="Invoice",
                to="other@example.com",
                timeout=240,
            )

        self.assertEqual(captured["timeout"], 240)


class MessageIdsTests(unittest.TestCase):
    def test_move_email_with_message_ids_uses_exact_id_condition(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return "moved"

        with patch("apple_mail_mcp.tools.manage.run_applescript", side_effect=fake_run):
            result = manage_tools.move_email(
                account="Work",
                to_mailbox="Archive",
                message_ids=["101", "202"],
                dry_run=True,
            )

        self.assertEqual(result, "moved")
        self.assertIn("id is 101", captured["script"])
        self.assertIn("id is 202", captured["script"])
        self.assertIn("DRY RUN - PREVIEW MOVE BY IDS", captured["script"])
        self.assertNotIn("move aMessage to destMailbox", captured["script"])

    def test_manage_trash_with_message_ids_uses_exact_id_condition(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return "trashed"

        with patch("apple_mail_mcp.tools.manage.run_applescript", side_effect=fake_run):
            result = manage_tools.manage_trash(
                account="Work",
                action="move_to_trash",
                message_ids=["555"],
                dry_run=False,
            )

        self.assertEqual(result, "trashed")
        self.assertIn("id is 555", captured["script"])
        self.assertIn("MOVING EMAILS TO TRASH BY IDS", captured["script"])
        self.assertIn("move aMessage to trashMailbox", captured["script"])

    def test_save_email_attachment_with_message_ids_uses_exact_id_condition(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return "saved"

        home = __import__("os").path.expanduser("~")
        save_path = f"{home}/Downloads/test-file.bin"

        with patch("apple_mail_mcp.tools.manage.run_applescript", side_effect=fake_run):
            manage_tools.save_email_attachment(
                account="Work",
                attachment_name="file.bin",
                save_path=save_path,
                message_ids=["777"],
            )

        self.assertIn("id is 777", captured["script"])
        self.assertNotIn("subject contains", captured["script"])


class TimeoutForwardingTests(unittest.TestCase):
    def test_get_email_by_id_forwards_timeout(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["timeout"] = timeout
            return ""

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            search_tools.get_email_by_id(
                account="Work",
                message_id="99",
                timeout=180,
            )

        self.assertEqual(captured["timeout"], 180)

    def test_get_email_by_id_handles_timeout(self):
        with patch(
            "apple_mail_mcp.tools.search.run_applescript",
            side_effect=AppleScriptTimeout("slow"),
        ):
            result = search_tools.get_email_by_id(
                account="Work",
                message_id="99",
            )

        self.assertIn("timed out", result.lower())

    def test_save_email_attachment_forwards_timeout(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["timeout"] = timeout
            return "saved"

        home = __import__("os").path.expanduser("~")
        save_path = f"{home}/Downloads/test-file.bin"

        with patch("apple_mail_mcp.tools.manage.run_applescript", side_effect=fake_run):
            manage_tools.save_email_attachment(
                account="Work",
                subject_keyword="Invoice",
                attachment_name="file.bin",
                save_path=save_path,
                timeout=90,
            )

        self.assertEqual(captured["timeout"], 90)

    def test_save_email_attachment_handles_timeout(self):
        home = __import__("os").path.expanduser("~")
        save_path = f"{home}/Downloads/test-file.bin"

        with patch(
            "apple_mail_mcp.tools.manage.run_applescript",
            side_effect=AppleScriptTimeout("slow"),
        ):
            result = manage_tools.save_email_attachment(
                account="Work",
                subject_keyword="Invoice",
                attachment_name="file.bin",
                save_path=save_path,
            )

        self.assertIn("timed out", result.lower())

    def test_get_mailbox_unread_counts_forwards_timeout(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["timeout"] = timeout
            return "Work:3"

        with patch("apple_mail_mcp.tools.inbox.run_applescript", side_effect=fake_run):
            inbox_tools.get_mailbox_unread_counts(summary_only=True, timeout=60)

        self.assertEqual(captured["timeout"], 60)

    def test_get_mailbox_unread_counts_handles_timeout(self):
        with patch(
            "apple_mail_mcp.tools.inbox.run_applescript",
            side_effect=AppleScriptTimeout("slow"),
        ):
            result = inbox_tools.get_mailbox_unread_counts(summary_only=True)

        self.assertEqual(result.get("error"), "timed_out")


if __name__ == "__main__":
    unittest.main()

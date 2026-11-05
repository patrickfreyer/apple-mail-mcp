"""Tests for manage_trash: report what Mail actually removed."""

import unittest
from unittest.mock import patch

from apple_mail_mcp.tools import manage as manage_tools


def _script_for(**kwargs):
    with patch(
        "apple_mail_mcp.tools.manage.run_applescript", return_value=""
    ) as mock_run:
        manage_tools.manage_trash(account="Work", **kwargs)
    mock_run.assert_called_once()
    return mock_run.call_args[0][0]


class EmptyTrashTests(unittest.TestCase):
    def setUp(self):
        self.script = _script_for(action="empty_trash", confirm_empty=True)

    def test_iterates_forward_over_the_captured_list(self):
        # trashMessages is captured up front, so a forward index loop is safe
        # and max_deletes takes the first N messages, not the last N.
        self.assertIn("repeat with msgIndex from 1 to messageCount", self.script)
        self.assertNotIn("repeat with aMessage in trashMessages", self.script)

    def test_confirmation_error_does_not_promise_permanent_deletion(self):
        result = manage_tools.manage_trash(account="Work", action="empty_trash")
        self.assertIn("attempts to delete", result)
        self.assertNotIn("permanently deletes", result)

    def test_reports_the_measured_mailbox_count(self):
        self.assertIn("set remainingCount to count of messages of trashMailbox", self.script)
        self.assertIn("Actually removed: ", self.script)
        self.assertNotIn("Emptied trash for account", self.script)

    def test_warns_when_nothing_was_removed(self):
        self.assertIn("if removedCount is 0 then", self.script)


class DeletePermanentTests(unittest.TestCase):
    def setUp(self):
        self.script = _script_for(
            action="delete_permanent", subject_keyword="x", dry_run=False
        )

    def test_reports_the_measured_mailbox_count(self):
        # Mail's `delete` is a no-op on a message already in Trash, so counting
        # delete calls reported deletions that never happened.
        self.assertIn("set trashBefore to count of messages of trashMailbox", self.script)
        self.assertIn("set trashAfter to count of messages of trashMailbox", self.script)
        self.assertIn("ACTUALLY REMOVED", self.script)
        self.assertNotIn("TOTAL DELETED", self.script)
        self.assertNotIn("Permanently deleted: ", self.script)

    def test_iterates_over_the_captured_list(self):
        self.assertIn(
            "repeat with msgIndex from (count of targetMessages) to 1 by -1",
            self.script,
        )


if __name__ == "__main__":
    unittest.main()


class InvalidActionTests(unittest.TestCase):
    def test_an_unknown_action_is_rejected_before_any_script_runs(self):
        # An unrecognised action used to fall through to the move_to_trash
        # branch, so action="list" with dry_run=False moved matches to Trash.
        with patch("apple_mail_mcp.tools.manage.run_applescript") as mock_run:
            result = manage_tools.manage_trash(
                account="Work",
                action="list",
                subject_keyword="Invoice",
                dry_run=False,
            )
        mock_run.assert_not_called()
        self.assertTrue(result.startswith("Error: Invalid action 'list'"))


class AgeFilterBeforeCapTests(unittest.TestCase):
    """With older_than_days, the cap used to be applied before the age check,
    so nothing was acted on when the newest matches were too recent. A
    `whose` on the date is not the fix: on a 75k-message Gmail INBOX it timed
    out after 120 s and left Mail unresponsive. Age-filtered calls walk the
    mailbox newest-first by index, count only qualifying messages toward the
    cap, and stop after AGE_SCAN_MAX_MESSAGES examined, saying so."""

    def _script(self, fn, **kwargs):
        with patch(
            "apple_mail_mcp.tools.manage.run_applescript", return_value=""
        ) as mock_run:
            fn(account="Work", **kwargs)
        return mock_run.call_args[0][0]

    def _assert_bounded_walk(self, script, counter, cap):
        self.assertNotIn("whose date received", script)
        self.assertIn("repeat with msgIndex from 1 to totalMessageCount", script)
        self.assertIn(f"if {counter} >= {cap} then exit repeat", script)
        self.assertIn(
            f"if scannedCount > {manage_tools.AGE_SCAN_MAX_MESSAGES} then", script
        )
        self.assertIn("NOTE: scan_limited", script)
        self.assertIn("(date received of aMessage) < cutoffDate", script)
        self.assertLess(script.index("set cutoffDate to"), script.index("repeat with msgIndex"))

    def test_update_status_walks_by_index_and_caps_qualifying_messages(self):
        script = self._script(
            manage_tools.update_email_status,
            action="mark_read", older_than_days=30, max_updates=10,
        )
        self._assert_bounded_walk(script, "updateCount", 10)
        walk = script[script.index("repeat with msgIndex"):]
        condition = walk.index("read status of aMessage is false")
        action = walk.index("set read status of aMessage to true")
        self.assertLess(condition, action)

    def test_update_status_without_age_keeps_the_whose_path(self):
        script = self._script(
            manage_tools.update_email_status,
            action="mark_read", sender="news@example.com", max_updates=10,
        )
        self.assertIn(
            'every message of targetMailbox whose read status is false and sender contains "news@example.com"',
            script,
        )
        self.assertNotIn("repeat with msgIndex", script)

    def test_trash_collects_by_index_then_acts(self):
        script = self._script(
            manage_tools.manage_trash,
            action="move_to_trash", subject_keyword="Invoice",
            older_than_days=30, max_deletes=10, dry_run=False,
        )
        self._assert_bounded_walk(script, "matchedCount", 10)
        self.assertIn('subject of aMessage contains "Invoice"', script)
        # Moving inside the walk would shift the indexes still to be visited.
        walk_end = script.index("end repeat", script.index("repeat with msgIndex"))
        self.assertLess(walk_end, script.index("move aMessage to trashMailbox"))
        self.assertIn("set end of targetMessages to aMessage", script)

    def test_trash_with_age_alone_has_no_whole_mailbox_whose(self):
        script = self._script(
            manage_tools.manage_trash,
            action="move_to_trash", older_than_days=30, apply_to_all=True,
            max_deletes=5, dry_run=True,
        )
        self._assert_bounded_walk(script, "matchedCount", 5)
        self.assertNotIn("set matchingMessages to every message of sourceMailbox", script)

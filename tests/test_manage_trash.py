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
    """The age check used to run per message after the list was cut to the
    cap, so when the newest matches were too recent nothing was acted on even
    though older qualifying messages existed. It now sits in the `whose`
    clause, so the cap applies to qualifying messages only."""

    def _whose_line(self, script):
        return next(
            line for line in script.splitlines()
            if "set matchingMessages to every message of" in line
        )

    def test_update_status_filters_by_age_before_the_cap(self):
        with patch(
            "apple_mail_mcp.tools.manage.run_applescript", return_value=""
        ) as mock_run:
            manage_tools.update_email_status(
                account="Work", action="mark_read", older_than_days=30, max_updates=10
            )
        script = mock_run.call_args[0][0]
        self.assertIn("date received < cutoffDate", self._whose_line(script))
        self.assertNotIn("(date received of aMessage) < cutoffDate", script)
        self.assertLess(
            script.index("set cutoffDate to"), script.index("set matchingMessages to")
        )

    def test_move_to_trash_filters_by_age_before_the_cap(self):
        with patch(
            "apple_mail_mcp.tools.manage.run_applescript", return_value=""
        ) as mock_run:
            manage_tools.manage_trash(
                account="Work", action="move_to_trash", subject_keyword="Invoice",
                older_than_days=30, max_deletes=10, dry_run=False,
            )
        script = mock_run.call_args[0][0]
        whose = self._whose_line(script)
        self.assertIn("date received < cutoffDate", whose)
        self.assertIn('subject contains "Invoice"', whose)
        self.assertNotIn("(date received of aMessage) < cutoffDate", script)

    def test_age_alone_still_uses_a_whose_clause_for_trash(self):
        with patch(
            "apple_mail_mcp.tools.manage.run_applescript", return_value=""
        ) as mock_run:
            manage_tools.manage_trash(
                account="Work", action="move_to_trash", older_than_days=30,
                max_deletes=10, dry_run=False,
            )
        script = mock_run.call_args[0][0]
        self.assertIn(
            "every message of sourceMailbox whose date received < cutoffDate", script
        )

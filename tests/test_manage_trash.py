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

    def test_iterates_backwards_over_the_captured_list(self):
        # Deleting inside a forward loop shifts later indices, so every
        # second message was skipped and the loop eventually read past the end.
        self.assertIn("repeat with msgIndex from messageCount to 1 by -1", self.script)
        self.assertNotIn("repeat with aMessage in trashMessages", self.script)

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

    def test_iterates_backwards_over_the_captured_list(self):
        self.assertIn(
            "repeat with msgIndex from (count of targetMessages) to 1 by -1",
            self.script,
        )


if __name__ == "__main__":
    unittest.main()

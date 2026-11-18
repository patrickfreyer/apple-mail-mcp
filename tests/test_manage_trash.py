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


class MoveToTrashByIdsTests(unittest.TestCase):
    def test_dry_run_previews_without_moving(self):
        script = _script_for(action="move_to_trash", message_ids=["12", "34"])
        self.assertIn("DRY RUN - PREVIEW TRASH BY IDS", script)
        self.assertIn("set targetIds to {12, 34}", script)
        self.assertIn("Would trash: ", script)
        self.assertNotIn("move aMessage to trashMailbox", script)
        self.assertNotIn("STILL PRESENT", script)

    def test_real_run_moves_and_verifies(self):
        script = _script_for(
            action="move_to_trash", message_ids=["12"], dry_run=False
        )
        self.assertIn("move aMessage to trashMailbox", script)
        self.assertIn("STILL PRESENT: ", script)

    def test_each_id_is_resolved_inside_the_loop_and_rechecked(self):
        # A list captured up front can go stale as messages leave the mailbox,
        # so each id is looked up on its own and its id re-read before moving.
        script = _script_for(
            action="move_to_trash", message_ids=["12"], dry_run=False
        )
        loop = script.index("repeat with rawId in targetIds")
        self.assertGreater(
            script.index("«class mssg» id targetId of sourceMailbox"), loop
        )
        self.assertLess(
            script.index("if resolvedId is targetId then"),
            script.index("move aMessage to trashMailbox"),
        )

    def test_uses_direct_id_lookup_not_whose(self):
        # `whose` over a whole mailbox is slow on large mailboxes (#41).
        script = _script_for(
            action="move_to_trash", message_ids=["12"], dry_run=False
        )
        self.assertNotIn("whose", script)

    def test_other_filters_are_ignored(self):
        script = _script_for(
            action="move_to_trash",
            message_ids=["12"],
            sender="someone",
            subject_keyword="hello",
        )
        self.assertNotIn("someone", script)
        self.assertNotIn("hello", script)

    def test_ids_are_normalized(self):
        script = _script_for(
            action="move_to_trash", message_ids=[" 12 ", "12", 34, "abc"]
        )
        self.assertIn("set targetIds to {12, 34}", script)

    def _error(self, **kwargs):
        with patch("apple_mail_mcp.tools.manage.run_applescript") as mock_run:
            result = manage_tools.manage_trash(account="Work", **kwargs)
        mock_run.assert_not_called()
        return result

    def test_rejects_empty_or_non_numeric_ids(self):
        self.assertIn("must contain", self._error(action="move_to_trash", message_ids=[]))
        self.assertIn("must contain", self._error(action="move_to_trash", message_ids=["x"]))

    def test_rejects_more_ids_than_max_deletes(self):
        result = self._error(
            action="move_to_trash", message_ids=[str(i) for i in range(6)]
        )
        self.assertIn("exceed max_deletes=5", result)

    def test_only_for_move_to_trash(self):
        result = self._error(
            action="delete_permanent", message_ids=["12"], dry_run=False
        )
        self.assertIn("only supported with action='move_to_trash'", result)

"""Tests for move_email's safety guard."""

import unittest
from unittest.mock import patch

from apple_mail_mcp.tools import manage as manage_tools


class MoveFilterGuardTests(unittest.TestCase):
    def test_a_non_positive_age_is_not_a_filter(self):
        # older_than_days=-1 passed the "at least one filter" guard but
        # produced no date condition, so it moved the newest max_moves
        # messages regardless of age. update_email_status and manage_trash
        # already count only a positive age as a filter.
        for days in (-1, 0):
            with self.subTest(older_than_days=days):
                with patch("apple_mail_mcp.tools.manage.run_applescript") as mock_run:
                    result = manage_tools.move_email(
                        account="Work", to_mailbox="Archive", older_than_days=days
                    )
                mock_run.assert_not_called()
                self.assertTrue(result.startswith("Error: At least one filter is required"))

    def test_a_positive_age_is_still_a_filter(self):
        with patch(
            "apple_mail_mcp.tools.manage.run_applescript", return_value=""
        ) as mock_run:
            manage_tools.move_email(account="Work", to_mailbox="Archive", older_than_days=30)
        script = mock_run.call_args[0][0]
        self.assertIn("set cutoffDate to (current date) - (30 * days)", script)

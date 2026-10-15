"""Tests for save_email_attachment's mailbox parameter."""

import os
import unittest
from unittest.mock import patch

from apple_mail_mcp.tools import manage as manage_tools


def _script_for(**kwargs):
    save_path = os.path.join(os.path.expanduser("~"), "Downloads", "invoice.pdf")
    with patch(
        "apple_mail_mcp.tools.manage.run_applescript", return_value="OK"
    ) as mock_run:
        manage_tools.save_email_attachment(
            account="Work",
            subject_keyword="Invoice",
            attachment_name="invoice.pdf",
            save_path=save_path,
            **kwargs,
        )
    mock_run.assert_called_once()
    return mock_run.call_args[0][0]


class SaveEmailAttachmentMailboxTests(unittest.TestCase):
    def test_defaults_to_the_inbox(self):
        script = _script_for()
        # INBOX goes through the localized-name fallback, as before.
        self.assertIn("set inboxMailbox to missing value", script)
        self.assertIn("repeat with __mailboxLookupName in", script)

    def test_searches_the_requested_mailbox(self):
        script = _script_for(mailbox="Archive")
        self.assertIn('set inboxMailbox to mailbox "Archive" of targetAccount', script)
        self.assertIn("Searched mailbox: Archive", script)

    def test_resolves_nested_mailboxes(self):
        script = _script_for(mailbox="Projects/2026")
        self.assertIn(
            'set inboxMailbox to mailbox "2026" of mailbox "Projects" of targetAccount',
            script,
        )


if __name__ == "__main__":
    unittest.main()

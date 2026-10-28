"""Tests for save_email_attachment's mailbox parameter."""

import os
import unittest
from unittest.mock import patch
from pathlib import Path

import pytest

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
        self.assertIn("set targetMailbox to missing value", script)
        self.assertIn("repeat with __mailboxLookupName in", script)

    def test_searches_the_requested_mailbox(self):
        script = _script_for(mailbox="Archive")
        self.assertIn('set targetMailbox to mailbox "Archive" of targetAccount', script)
        self.assertIn("Searched mailbox: Archive", script)

    def test_resolves_nested_mailboxes(self):
        script = _script_for(mailbox="Projects/2026")
        self.assertIn(
            'set targetMailbox to mailbox "2026" of mailbox "Projects" of targetAccount',
            script,
        )


def test_subject_script_snapshot():
    with patch.object(manage_tools, "run_applescript", return_value="OK") as run:
        manage_tools.save_email_attachment("Work", "Invoice", "invoice.pdf",
                                          "/tmp/invoice.pdf", "Archive")
    # /tmp resolves to /private/tmp on macOS but not on Linux CI.
    expected = (
        Path(__file__).parent / "fixtures/save_attachments_subject.applescript"
    ).read_text().replace("{SAVE_PATH}", os.path.realpath("/tmp/invoice.pdf"))
    assert run.call_args.args[0] == expected


def test_save_by_id():
    with patch.object(manage_tools, "run_applescript", return_value="saved") as run:
        result = manage_tools.save_email_attachment(
            "Work", subject_keyword="IGNORED", attachment_name='inv"oice.pdf',
            save_path='~/Downloads/inv"oice.pdf', mailbox="Projects/2026",
            message_id=" 777 ")
    assert result == "saved"
    script = run.call_args.args[0]
    assert "«class mssg» id 777 of targetMailbox" in script
    for forbidden in ("whose", "every message", "messages of", "IGNORED"):
        assert forbidden not in script
    assert 'mailbox "2026" of mailbox "Projects" of targetAccount' in script
    assert 'attachmentFileName to name of anAttachment' in script
    assert 'attachmentFileName contains "inv\\"oice.pdf"' in script
    expanded = os.path.expanduser('~/Downloads/inv"oice.pdf').replace('"', '\\"')
    assert f'save anAttachment in POSIX file "{expanded}"' in script
    assert "Error: message 777 not found in mailbox Projects/2026 of account Work" in script


@pytest.mark.parametrize("kwargs", [
    dict(message_id="7x"), dict(message_id=""), dict(message_id="７７７"),
    {}, dict(message_id="777", save_path="~/.zshrc"),
    dict(message_id="777", attachment_name=""),
    dict(message_id="777", save_path=""),
])
def test_invalid_save_does_not_run_applescript(kwargs):
    params = dict(account="Work", attachment_name="invoice.pdf",
                  save_path="/tmp/invoice.pdf")
    params.update(kwargs)
    with patch.object(manage_tools, "run_applescript") as run:
        assert manage_tools.save_email_attachment(**params).startswith("Error:")
    run.assert_not_called()

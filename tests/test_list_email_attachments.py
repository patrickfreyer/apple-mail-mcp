"""Direct message-id attachment listing and legacy script regression tests."""

from pathlib import Path
from unittest.mock import patch

import pytest

from apple_mail_mcp.tools import analytics


def test_subject_script_snapshot():
    with patch.object(analytics, "run_applescript", return_value="OK") as run:
        analytics.list_email_attachments("Work", "Invoice", 2)
    assert run.call_args.args[0] == (
        Path(__file__).parent / "fixtures/list_attachments_subject.applescript"
    ).read_text()


@pytest.mark.parametrize("kwargs", [{}, dict(message_id=""), dict(message_id="7x"),
                                    dict(message_id="７７７")])
def test_invalid_lookup_does_not_run_applescript(kwargs):
    with patch.object(analytics, "run_applescript") as run:
        assert analytics.list_email_attachments("Work", **kwargs).startswith("Error:")
    run.assert_not_called()


def test_list_by_id_with_unavailable_mime_type():
    # Mail formats the result itself; an unavailable MIME type must not suppress
    # either the attachment or its available name/size.
    output = ("ATTACHMENTS FOR: Invoice\n\n✉ Invoice\n"
              "   From: sender@example.com\n   Date: today\n\n"
              "   Attachments (1):\n   📎 invoice.pdf (2 KB)\n\n"
              "========================================\n"
              "FOUND: 1 matching email(s)\n"
              "========================================\n")
    with patch.object(analytics, "run_applescript", return_value=output) as run:
        assert analytics.list_email_attachments(
            "Work", "IGNORED", message_id=" 777 ", mailbox="Archive"
        ) == output
    script = run.call_args.args[0]
    assert "«class mssg» id 777 of targetMailbox" in script
    assert 'set targetMailbox to mailbox "Archive" of targetAccount' in script
    for forbidden in ("whose", "every message", "messages of", "IGNORED"):
        assert forbidden not in script
    # MIME type isn't shown, and Mail raises -10000 for it on some Exchange
    # attachments, so it isn't read at all.
    assert "MIME type" not in script
    for variable, prop in (("attachmentName", "name"),
                           ("attachmentSize", "file size")):
        assert f'set {variable} to ""\n                        try\n                            set {variable} to {prop} of anAttachment\n                        end try' in script
    assert "Error: message 777 not found in mailbox Archive of account Work" in script
    assert 'set sizeInKB to (attachmentSize / 1024) as integer' in script
    assert '"   📎 " & attachmentName' in script
    assert '"FOUND: 1 matching email(s)"' in script

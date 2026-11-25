"""Drafts saved without a window, forward modes, and drafts addressed by id."""

import os
import re
import unittest
from unittest.mock import patch

from apple_mail_mcp.tools import compose as compose_tools

# Anything that would open a window or take over the user's screen.
FOREGROUND_MARKERS = (
    "activate",
    "keystroke",
    "System Events",
    "NSPasteboard",
    "close window",
    "with opening window",
)


def _capture(call, return_value="OK"):
    """Run a tool with run_applescript mocked; return (result, scripts)."""
    scripts = []

    def fake_run(script, timeout=120):
        scripts.append(script)
        return return_value

    with (
        patch(
            "apple_mail_mcp.tools.compose.run_applescript", side_effect=fake_run
        ),
        patch("apple_mail_mcp.tools.compose.subprocess.run") as mock_subprocess,
        patch(
            "apple_mail_mcp.tools.compose._account_default_alias_if_single",
            return_value=None,
        ),
    ):
        result = call()
    mock_subprocess.assert_not_called()
    return result, scripts


class WindowlessDraftMixin:
    def assertWindowless(self, script):
        for marker in FOREGROUND_MARKERS:
            self.assertNotIn(marker, script)
        self.assertIn("visible:false", script)

    def assertSavesAndLocates(self, script, message_var):
        snapshot = script.index("set priorDraftIDs to id of every message of drafts mailbox")
        made = script.index(f"set {message_var} to make new outgoing message")
        saved = script.index(f"save {message_var}")
        self.assertLess(snapshot, made)
        self.assertLess(made, saved)
        self.assertIn("savedDraftID", script)
        self.assertNotIn(f"send {message_var}", script)


class ComposeDraftTests(WindowlessDraftMixin, unittest.TestCase):
    def test_draft_is_saved_without_a_window(self):
        _, scripts = _capture(
            lambda: compose_tools.compose_email(
                account="Work",
                to="someone@example.com",
                subject="Test",
                body="Body",
                mode="draft",
            )
        )
        script = scripts[-1]
        self.assertWindowless(script)
        self.assertSavesAndLocates(script, "newMessage")
        self.assertIn('"Draft id: " & savedDraftID', script)

    def test_send_mode_is_unchanged(self):
        _, scripts = _capture(
            lambda: compose_tools.compose_email(
                account="Work", to="someone@example.com", subject="Test", body="Body"
            )
        )
        self.assertIn("send newMessage", scripts[-1])
        self.assertNotIn("priorDraftIDs", scripts[-1])


class ManageDraftsByIdTests(WindowlessDraftMixin, unittest.TestCase):
    def test_list_shows_draft_ids(self):
        _, scripts = _capture(
            lambda: compose_tools.manage_drafts(account="Work", action="list")
        )
        self.assertIn('"   ID: " & (id of aDraft)', scripts[-1])

    def test_create_saves_and_reports_id(self):
        _, scripts = _capture(
            lambda: compose_tools.manage_drafts(
                account="Work",
                action="create",
                subject="Test",
                to="someone@example.com",
                body="Body",
            )
        )
        script = scripts[-1]
        self.assertWindowless(script)
        self.assertSavesAndLocates(script, "newDraft")

    def test_open_delete_and_send_look_up_by_id(self):
        for action in ("open", "delete", "send"):
            with self.subTest(action=action):
                _, scripts = _capture(
                    lambda action=action: compose_tools.manage_drafts(
                        account="Work", action=action, draft_id=" 123 "
                    )
                )
                script = scripts[-1]
                self.assertIn("«class mssg» id 123 of draftsMailbox", script)
                self.assertIn("get id of foundDraft", script)
                self.assertNotIn("every message of draftsMailbox", script)
                self.assertIn("No draft found matching: id 123", script)

    def test_subject_lookup_still_works(self):
        _, scripts = _capture(
            lambda: compose_tools.manage_drafts(
                account="Work", action="delete", draft_subject='Say "hi"'
            )
        )
        script = scripts[-1]
        self.assertIn('contains "Say \\"hi\\""', script)
        self.assertNotIn("«class mssg»", script)

    def test_rejects_non_numeric_draft_id(self):
        result, scripts = _capture(
            lambda: compose_tools.manage_drafts(
                account="Work", action="delete", draft_id="12 or 1"
            )
        )
        self.assertEqual(scripts, [])
        self.assertEqual(result, "Error: draft_id must contain digits only")

    def test_requires_subject_or_id(self):
        for action in ("open", "delete", "send"):
            with self.subTest(action=action):
                result, scripts = _capture(
                    lambda action=action: compose_tools.manage_drafts(
                        account="Work", action=action
                    )
                )
                self.assertEqual(scripts, [])
                self.assertIn("'draft_subject' or 'draft_id' is required", result)


class ForwardDraftTests(WindowlessDraftMixin, unittest.TestCase):
    def _forward(self, **overrides):
        kwargs = dict(
            account="Work",
            to="a@example.com, b@example.com",
            message_id="42",
            mode="draft",
        )
        kwargs.update(overrides)
        return _capture(lambda: compose_tools.forward_email(**kwargs))

    def test_draft_is_saved_without_a_window(self):
        _, scripts = self._forward(message="FYI", cc="c@example.com")
        self.assertEqual(len(scripts), 1)
        script = scripts[0]
        self.assertWindowless(script)
        self.assertSavesAndLocates(script, "forwardMessage")
        self.assertNotIn("forward foundMessage", script)
        self.assertIn("«class mssg» id 42 of targetMailbox", script)
        self.assertIn('{address:"b@example.com"}', script)
        self.assertIn("make new cc recipient", script)
        self.assertIn('"FYI\\n\\nBegin forwarded message:"', script)

    def test_draft_copies_original_attachments_then_removes_the_copies(self):
        _, scripts = self._forward()
        script = scripts[0]
        self.assertIn("repeat with anAttachment in (mail attachments of foundMessage)", script)
        self.assertIn("save anAttachment in (POSIX file attachmentPath)", script)
        self.assertIn("make new attachment with properties {file name:(POSIX file attachmentPath)}", script)
        folder = re.search(r'set attachmentFolder to "([^"]+)/"', script).group(1)
        self.assertFalse(os.path.exists(folder))

    def test_draft_keeps_attachment_names_inside_the_temp_folder(self):
        # Attachment names come from the incoming mail; a "/" in one must not
        # let `save` write outside the per-attachment temp folder.
        _, scripts = self._forward()
        script = scripts[0]
        sanitize = script.index('set AppleScript\'s text item delimiters to "/"')
        replace = script.index('set AppleScript\'s text item delimiters to "_"')
        path = script.index('set attachmentPath to attachmentFolder & "/" & attachmentName')
        save = script.index("save anAttachment in (POSIX file attachmentPath)")
        self.assertLess(sanitize, replace)
        self.assertLess(replace, path)
        self.assertLess(path, save)
        self.assertIn('attachmentName is ".." then set attachmentName to "attachment"', script)

    def test_draft_by_subject_keyword(self):
        _, scripts = self._forward(message_id=None, subject_keyword="Invoice")
        self.assertIn('contains "Invoice"', scripts[0])

    def test_open_mode_does_not_send(self):
        _, scripts = self._forward(mode="open")
        script = scripts[-1]
        self.assertIn("forward foundMessage with opening window", script)
        self.assertNotIn("send forwardMessage", script)
        self.assertIn("«class mssg» id 42 of targetMailbox", script)

    def test_send_mode_still_sends(self):
        _, scripts = self._forward(mode="send", message_id=None, subject_keyword="x")
        self.assertIn("send forwardMessage", scripts[-1])

    def test_rejects_bad_mode_and_id(self):
        for overrides, expected in (
            ({"mode": "later"}, "Error: Invalid mode 'later'. Use: send, draft, open"),
            ({"message_id": "4x"}, "Error: message_id must contain digits only"),
            (
                {"message_id": None},
                "Error: subject_keyword or message_id is required",
            ),
        ):
            with self.subTest(overrides=overrides):
                result, scripts = self._forward(**overrides)
                self.assertEqual(scripts, [])
                self.assertEqual(result, expected)


class ForwardReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self._previous = compose_tools.server.READ_ONLY
        compose_tools.server.READ_ONLY = True

    def tearDown(self):
        compose_tools.server.READ_ONLY = self._previous

    def test_draft_and_open_stay_available(self):
        for mode in ("draft", "open"):
            with self.subTest(mode=mode):
                result, scripts = _capture(
                    lambda mode=mode: compose_tools.forward_email(
                        account="Work",
                        to="a@example.com",
                        message_id="42",
                        mode=mode,
                    )
                )
                self.assertEqual(result, "OK")
                self.assertNotIn("send forwardMessage", scripts[-1])


if __name__ == "__main__":
    unittest.main()

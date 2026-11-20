"""Drafts saved without a window, and drafts addressed by id."""

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


if __name__ == "__main__":
    unittest.main()

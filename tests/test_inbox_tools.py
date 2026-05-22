"""Tests for inbox listing helpers."""

import asyncio
import json
import unittest
from unittest.mock import patch

from apple_mail_mcp.tools import inbox as inbox_tools


def _run(coro):
    """Synchronously drive an async tool inside a test."""
    if asyncio.iscoroutine(coro):
        return asyncio.run(coro)
    return coro


class InboxToolTests(unittest.TestCase):
    def test_text_list_inbox_honors_account_filter(self):
        # In the 3.1.5 modernized list_inbox_emails, an explicit `account`
        # triggers the single-account fast path: the AppleScript looks up
        # `account "Work"` directly instead of iterating every account.
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return "ok"

        with patch("apple_mail_mcp.tools.inbox.run_applescript", side_effect=fake_run):
            _run(inbox_tools.list_inbox_emails(account="Work", max_emails=5))

        self.assertIn('account "Work"', captured["script"])
        # max_emails=5 should appear as a cap inside the script.
        self.assertIn("1 thru 5", captured["script"])

    def test_json_list_inbox_can_include_content_preview(self):
        # The JSON-format inbox listing should request a content preview when
        # include_content=True and parse the pipe-delimited script output.
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return "Subject|||sender@example.com|||Thu, Jan 1, 2026|||false|||Work|||Hello | world"

        with patch("apple_mail_mcp.tools.inbox.run_applescript", side_effect=fake_run):
            response = json.loads(
                _run(
                    inbox_tools.list_inbox_emails(
                        account="Work",
                        max_emails=1,
                        include_content=True,
                        output_format="json",
                    )
                )
            )

        self.assertIn("content of aMessage", captured["script"])
        self.assertEqual(response[0]["content_preview"], "Hello | world")

    def test_parser_preserves_delimiters_in_content_preview(self):
        records = inbox_tools._parse_pipe_delimited_emails(
            "Subject|||sender@example.com|||Date|||true|||Work|||Hello ||| still content"
        )

        self.assertEqual(records[0]["content_preview"], "Hello ||| still content")


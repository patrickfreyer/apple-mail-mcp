"""Tests for inbox listing helpers."""

import json
import unittest
from unittest.mock import patch

from apple_mail_mcp.tools import inbox as inbox_tools


class InboxToolTests(unittest.TestCase):
    def test_text_list_inbox_honors_account_filter(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return "ok"

        with patch("apple_mail_mcp.tools.inbox.run_applescript", side_effect=fake_run):
            inbox_tools.list_inbox_emails(account="Work", max_emails=5)

        self.assertIn('if accountName is not "Work"', captured["script"])
        self.assertIn("set shouldIncludeAccount to false", captured["script"])
        self.assertIn('set outputText to "INBOX EMAILS - Work"', captured["script"])

    def test_json_list_inbox_can_include_content_preview(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return "Subject|||sender@example.com|||Thu, Jan 1, 2026|||false|||Work|||Hello | world"

        with patch("apple_mail_mcp.tools.inbox.run_applescript", side_effect=fake_run):
            response = json.loads(
                inbox_tools.list_inbox_emails(
                    account="Work",
                    max_emails=1,
                    include_content=True,
                    output_format="json",
                )
            )

        self.assertIn("on sanitize_field(value)", captured["script"])
        self.assertIn("content of aMessage", captured["script"])
        self.assertEqual(response[0]["content_preview"], "Hello | world")

    def test_parser_preserves_delimiters_in_content_preview(self):
        records = inbox_tools._parse_pipe_delimited_emails(
            "Subject|||sender@example.com|||Date|||true|||Work|||Hello ||| still content"
        )

        self.assertEqual(records[0]["content_preview"], "Hello ||| still content")


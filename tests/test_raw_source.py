"""Tests for get_email_source — identifier resolution and error paths.

These tests mock ``run_applescript`` so they exercise the script-construction
and error-handling logic without needing a live Mail.app.
"""

import unittest
from unittest.mock import patch

from apple_mail_mcp.tools import raw_source as raw_source_tools


class GetEmailSourceTests(unittest.TestCase):
    def test_subject_keyword_resolves_and_returns_source(self):
        sample_source = (
            "From: alice@example.com\n"
            "Subject: Test message\n"
            'Message-Id: <abc@example.com>\n'
            "\n"
            "Body with a link: https://example.com/path\n"
        )

        with patch.object(
            raw_source_tools, "run_applescript", return_value=sample_source
        ) as mock_run:
            result = raw_source_tools.get_email_source(
                account="Work",
                subject_keyword="Test message",
            )

        self.assertEqual(result, sample_source)
        script = mock_run.call_args[0][0]
        self.assertIn("subject contains", script)
        self.assertIn("Test message", script)
        self.assertIn("source of", script)

    def test_message_id_preferred_when_both_provided(self):
        with patch.object(
            raw_source_tools, "run_applescript", return_value="raw"
        ) as mock_run:
            raw_source_tools.get_email_source(
                account="Work",
                subject_keyword="ignored",
                message_id="<abc@example.com>",
            )

        script = mock_run.call_args[0][0]
        # The property is ``message id`` (RFC 822 Message-Id), not
        # ``internet message id`` — the latter is not a valid AppleScript
        # property on ``message`` and would fail at runtime with error -2741.
        self.assertIn('message id is "<abc@example.com>"', script)
        self.assertNotIn("internet message id", script)
        self.assertNotIn("subject contains", script)

    def test_missing_identifier_returns_error_without_calling_applescript(self):
        with patch.object(
            raw_source_tools, "run_applescript"
        ) as mock_run:
            result = raw_source_tools.get_email_source(account="Work")

        self.assertTrue(result.startswith("Error:"))
        self.assertIn("subject_keyword", result)
        self.assertIn("message_id", result)
        mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

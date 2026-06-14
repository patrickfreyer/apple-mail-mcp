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


class SizeCapTests(unittest.TestCase):
    def test_under_cap_returns_source_unchanged(self):
        sample = "From: a@example.com\n\nshort body\n"
        with patch.object(
            raw_source_tools, "run_applescript", return_value=sample
        ):
            result = raw_source_tools.get_email_source(
                account="Work",
                subject_keyword="x",
                max_bytes=1024,
            )
        self.assertEqual(result, sample)
        self.assertNotIn("truncated", result)

    def test_over_cap_truncates_with_marker(self):
        # Build a payload safely over a small cap.
        big_body = "x" * 5000
        sample = f"From: a@example.com\n\n{big_body}\n"
        cap = 1024

        with patch.object(
            raw_source_tools, "run_applescript", return_value=sample
        ):
            result = raw_source_tools.get_email_source(
                account="Work",
                subject_keyword="x",
                max_bytes=cap,
            )

        self.assertIn("[... truncated:", result)
        self.assertIn(f"cap {cap} bytes", result)
        self.assertIn(f"original size {len(sample.encode('utf-8'))} bytes", result)
        # Prefix is preserved.
        self.assertTrue(result.startswith("From: a@example.com\n\n"))

    def test_default_cap_is_256kb(self):
        self.assertEqual(raw_source_tools.DEFAULT_MAX_BYTES, 256 * 1024)


class HeadersOnlyTests(unittest.TestCase):
    def test_headers_only_strips_body(self):
        sample = (
            "From: alice@example.com\r\n"
            "Subject: Hello\r\n"
            "Message-Id: <abc@example.com>\r\n"
            "\r\n"
            "Body with a link: https://example.com/path\r\n"
        )

        with patch.object(
            raw_source_tools, "run_applescript", return_value=sample
        ):
            result = raw_source_tools.get_email_source(
                account="Work",
                subject_keyword="Hello",
                headers_only=True,
            )

        self.assertIn("From: alice@example.com", result)
        self.assertIn("Subject: Hello", result)
        self.assertNotIn("Body with a link", result)
        # Header block ends with the separating blank line.
        self.assertTrue(result.endswith("\r\n\r\n"))

    def test_headers_only_with_lf_only_separator(self):
        sample = (
            "From: alice@example.com\n"
            "Subject: Hello\n"
            "\n"
            "body\n"
        )

        with patch.object(
            raw_source_tools, "run_applescript", return_value=sample
        ):
            result = raw_source_tools.get_email_source(
                account="Work",
                subject_keyword="x",
                headers_only=True,
            )

        self.assertNotIn("body", result)
        self.assertTrue(result.endswith("\n\n"))

    def test_headers_only_with_no_blank_line_returns_full_payload(self):
        sample = "From: alice@example.com\nSubject: stub\n"
        with patch.object(
            raw_source_tools, "run_applescript", return_value=sample
        ):
            result = raw_source_tools.get_email_source(
                account="Work",
                subject_keyword="x",
                headers_only=True,
            )
        self.assertEqual(result, sample)


class ErrorPassthroughTests(unittest.TestCase):
    def test_applescript_error_returns_are_not_post_processed(self):
        # AppleScript-layer error returns should pass straight through
        # without being subjected to cap or headers_only.
        with patch.object(
            raw_source_tools,
            "run_applescript",
            return_value="Error: account not found: Work",
        ):
            result = raw_source_tools.get_email_source(
                account="Work",
                subject_keyword="x",
                headers_only=True,
                max_bytes=10,
            )

        self.assertEqual(result, "Error: account not found: Work")


if __name__ == "__main__":
    unittest.main()

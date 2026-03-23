"""Tests for compose and rich draft helpers."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apple_mail_mcp.tools import compose as compose_tools


class ComposeToolTests(unittest.TestCase):
    def test_create_rich_email_draft_writes_multipart_eml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "weekly-update.eml"

            with (
                patch(
                    "apple_mail_mcp.tools.compose.run_applescript",
                    return_value="sender@example.com",
                ),
                patch("apple_mail_mcp.tools.compose.subprocess.run") as mock_run,
            ):
                result = compose_tools.create_rich_email_draft(
                    account="Work",
                    subject="Weekly Update",
                    to="team@example.com",
                    text_body="Plain fallback",
                    html_body="<html><body><h1>Weekly Update</h1></body></html>",
                    output_path=str(output_path),
                    open_in_mail=True,
                )

            payload = output_path.read_text()
            self.assertIn("multipart/alternative", payload)
            self.assertIn("<h1>Weekly Update</h1>", payload)
            self.assertIn("Subject: Weekly Update", payload)
            self.assertIn("Opened in Mail: yes", result)
            mock_run.assert_called_once_with(
                ["open", "-a", "Mail", str(output_path)], check=True
            )

    def test_create_rich_email_draft_allows_partial_details(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "partial.eml"

            with (
                patch(
                    "apple_mail_mcp.tools.compose.run_applescript",
                    return_value="sender@example.com",
                ),
                patch("apple_mail_mcp.tools.compose.subprocess.run"),
            ):
                result = compose_tools.create_rich_email_draft(
                    account="Work",
                    output_path=str(output_path),
                    open_in_mail=False,
                )

            payload = output_path.read_text()
            self.assertIn("Draft outline", payload)
            self.assertIn("Missing details: subject, to, body", result)
            self.assertIn("Opened in Mail: no", result)

    def test_create_rich_email_draft_can_save_to_drafts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "saved.eml"
            run_results = ["sender@example.com", "saved"]

            def fake_run_applescript(script, timeout=120):
                return run_results.pop(0)

            with (
                patch(
                    "apple_mail_mcp.tools.compose.run_applescript",
                    side_effect=fake_run_applescript,
                ),
                patch("apple_mail_mcp.tools.compose.subprocess.run"),
            ):
                result = compose_tools.create_rich_email_draft(
                    account="Work",
                    subject="Saved Draft",
                    output_path=str(output_path),
                    open_in_mail=True,
                    save_as_draft=True,
                )

            self.assertIn("Saved in Drafts: yes", result)


if __name__ == "__main__":
    unittest.main()

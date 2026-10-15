"""Tests for compose and rich draft helpers."""

import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from apple_mail_mcp.tools import compose as compose_tools


def _make_subprocess_result(returncode=0, stdout=b"", stderr=b""):
    """Build a MagicMock shaped like subprocess.CompletedProcess."""
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


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

    def test_create_rich_email_draft_reports_save_as_draft_honestly(self):
        # An opened `.eml` is a read-only Mail viewer, not a compose object, so
        # save_as_draft can never actually succeed (#83) — the tool must say so
        # plainly instead of implying the draft was saved.
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "saved.eml"

            with (
                patch(
                    "apple_mail_mcp.tools.compose.run_applescript",
                    return_value="sender@example.com",
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

            self.assertIn("Saved in Drafts: no", result)
            self.assertIn("save_as_draft could not be honored", result)

    def test_create_rich_email_draft_omits_save_note_when_not_requested(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "unsaved.eml"

            with (
                patch(
                    "apple_mail_mcp.tools.compose.run_applescript",
                    return_value="sender@example.com",
                ),
                patch("apple_mail_mcp.tools.compose.subprocess.run"),
            ):
                result = compose_tools.create_rich_email_draft(
                    account="Work",
                    subject="Unsaved Draft",
                    output_path=str(output_path),
                    open_in_mail=True,
                )

            self.assertIn("Saved in Drafts: no", result)
            self.assertNotIn("save_as_draft could not be honored", result)


class StripCdataTests(unittest.TestCase):
    def test_none_passes_through(self):
        self.assertIsNone(compose_tools._strip_cdata_wrappers(None))

    def test_empty_passes_through(self):
        self.assertEqual("", compose_tools._strip_cdata_wrappers(""))

    def test_unwraps_symmetric_block(self):
        self.assertEqual(
            "<p>Hello</p>",
            compose_tools._strip_cdata_wrappers("<![CDATA[<p>Hello</p>]]>"),
        )

    def test_unwraps_multiline_block(self):
        self.assertEqual(
            "\n<p>Hi</p>\n",
            compose_tools._strip_cdata_wrappers("<![CDATA[\n<p>Hi</p>\n]]>"),
        )

    def test_strips_stray_closing_marker(self):
        # This is the symptom users actually see — HTML parsers hide the
        # opening `<![CDATA[`, but the trailing `]]>` renders as text.
        self.assertEqual(
            "<p>Hello</p>",
            compose_tools._strip_cdata_wrappers("<p>Hello</p>]]>"),
        )

    def test_strips_stray_opening_marker(self):
        self.assertEqual(
            "<p>Hello</p>",
            compose_tools._strip_cdata_wrappers("<![CDATA[<p>Hello</p>"),
        )

    def test_leaves_normal_html_untouched(self):
        html = '<html><body><h1>Weekly Update</h1></body></html>'
        self.assertEqual(html, compose_tools._strip_cdata_wrappers(html))


class CreateRichEmailDraftCdataTests(unittest.TestCase):
    def test_cdata_wrapped_html_body_is_stripped_in_eml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "cdata.eml"

            with (
                patch(
                    "apple_mail_mcp.tools.compose.run_applescript",
                    return_value="sender@example.com",
                ),
                patch("apple_mail_mcp.tools.compose.subprocess.run"),
            ):
                compose_tools.create_rich_email_draft(
                    account="Work",
                    subject="CDATA Test",
                    to="team@example.com",
                    text_body="Plain fallback",
                    html_body="<![CDATA[<html><body><h1>Hi</h1></body></html>]]>",
                    output_path=str(output_path),
                    open_in_mail=False,
                )

            payload = output_path.read_text()
            self.assertIn("<h1>Hi</h1>", payload)
            self.assertNotIn("<![CDATA[", payload)
            self.assertNotIn("]]>", payload)


class ValidateFromAddressTests(unittest.TestCase):
    def test_none_skips_lookup(self):
        with patch("apple_mail_mcp.tools.compose.run_applescript") as mock_run:
            override, error = compose_tools._validate_from_address("Work", None)
        self.assertIsNone(override)
        self.assertIsNone(error)
        mock_run.assert_not_called()

    def test_blank_skips_lookup(self):
        with patch("apple_mail_mcp.tools.compose.run_applescript") as mock_run:
            override, error = compose_tools._validate_from_address("Work", "   ")
        self.assertIsNone(override)
        self.assertIsNone(error)
        mock_run.assert_not_called()

    def test_matches_case_insensitively_and_trims(self):
        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            return_value="Default@Example.com\nSecondary@Example.org",
        ):
            override, error = compose_tools._validate_from_address(
                "Work", "  SECONDARY@example.ORG "
            )
        self.assertEqual(override, "Secondary@Example.org")
        self.assertIsNone(error)

    def test_unknown_alias_returns_error(self):
        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            return_value="default@example.com",
        ):
            override, error = compose_tools._validate_from_address(
                "Work", "other@example.com"
            )
        self.assertIsNone(override)
        self.assertIn("is not configured on account", error)
        self.assertIn("default@example.com", error)

    def test_missing_aliases_returns_error(self):
        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            return_value="",
        ):
            override, error = compose_tools._validate_from_address(
                "Work", "anything@example.com"
            )
        self.assertIsNone(override)
        self.assertIn("Could not read email addresses", error)


class ComposeEmailSenderOverrideTests(unittest.TestCase):
    def test_default_emits_single_alias_fallback_block(self):
        captured = []

        def fake_run(script, timeout=120):
            captured.append(script)
            return "✓ Email sent successfully!"

        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            side_effect=fake_run,
        ):
            compose_tools.compose_email(
                account="Work",
                to="self@example.com",
                subject="Test",
                body="Body",
                mode="draft",
            )

        self.assertEqual(len(captured), 1)
        script = captured[0]
        self.assertIn("email addresses of targetAccount", script)
        self.assertIn("if (count of emailAddrs) is 1 then", script)
        self.assertIn(
            "set sender of newMessage to item 1 of emailAddrs", script
        )
        self.assertNotIn('set sender of newMessage to "', script)

    def test_injects_sender_when_from_address_is_valid(self):
        scripts = []

        def fake_run(script, timeout=120):
            scripts.append(script)
            if len(scripts) == 1:
                return "default@example.com\nsecondary@example.org"
            return "✓ Email sent successfully!"

        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            side_effect=fake_run,
        ):
            compose_tools.compose_email(
                account="Work",
                to="self@example.com",
                subject="Test",
                body="Body",
                mode="draft",
                from_address="secondary@example.org",
            )

        self.assertEqual(len(scripts), 2)
        main_script = scripts[1]
        self.assertIn(
            'set sender of newMessage to "secondary@example.org"', main_script
        )
        self.assertNotIn("if (count of emailAddrs) is 1 then", main_script)

    def test_rejects_invalid_from_address_without_sending(self):
        scripts = []

        def fake_run(script, timeout=120):
            scripts.append(script)
            return "default@example.com"

        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            side_effect=fake_run,
        ):
            result = compose_tools.compose_email(
                account="Work",
                to="self@example.com",
                subject="Test",
                body="Body",
                mode="draft",
                from_address="unknown@example.com",
            )

        self.assertEqual(len(scripts), 1)
        self.assertTrue(result.startswith("Error: 'from_address'"))


class AccountDefaultAliasIfSingleTests(unittest.TestCase):
    def test_returns_sole_alias(self):
        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            return_value="solo@example.com",
        ):
            self.assertEqual(
                compose_tools._account_default_alias_if_single("Solo"),
                "solo@example.com",
            )

    def test_returns_none_when_empty(self):
        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            return_value="",
        ):
            self.assertIsNone(
                compose_tools._account_default_alias_if_single("Multi")
            )


class ComposeSenderScriptTests(unittest.TestCase):
    def test_override_sets_sender_directly(self):
        script = compose_tools._compose_sender_script(
            "newMessage", "targetAccount", "chosen@example.com"
        )
        self.assertEqual(
            script, 'set sender of newMessage to "chosen@example.com"'
        )

    def test_without_override_emits_single_alias_fallback(self):
        script = compose_tools._compose_sender_script(
            "newMessage", "targetAccount", None
        )
        self.assertIn("email addresses of targetAccount", script)
        self.assertIn("if (count of emailAddrs) is 1 then", script)
        self.assertIn(
            "set sender of newMessage to item 1 of emailAddrs", script
        )

    def test_override_value_is_escaped(self):
        script = compose_tools._compose_sender_script(
            "newMessage", "targetAccount", 'weird"quote@example.com'
        )
        self.assertIn(r'\"quote@example.com', script)


class CreateRichEmailDraftFromAddressTests(unittest.TestCase):
    def test_omits_from_header_for_multi_alias_account(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "multi.eml"
            with (
                patch(
                    "apple_mail_mcp.tools.compose.run_applescript",
                    return_value="",
                ),
                patch("apple_mail_mcp.tools.compose.subprocess.run"),
            ):
                compose_tools.create_rich_email_draft(
                    account="Multi",
                    subject="No From",
                    to="team@example.com",
                    text_body="Body",
                    output_path=str(output_path),
                    open_in_mail=False,
                )

            payload = output_path.read_text()
            header_block = payload.split("\n\n", 1)[0]
            self.assertNotIn("From:", header_block)

    def test_stamps_from_header_for_single_alias_account(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "single.eml"
            with (
                patch(
                    "apple_mail_mcp.tools.compose.run_applescript",
                    return_value="solo@example.com",
                ),
                patch("apple_mail_mcp.tools.compose.subprocess.run"),
            ):
                compose_tools.create_rich_email_draft(
                    account="Solo",
                    subject="Single",
                    to="team@example.com",
                    text_body="Body",
                    output_path=str(output_path),
                    open_in_mail=False,
                )

            payload = output_path.read_text()
            self.assertIn("From: solo@example.com", payload)

    def test_stamps_from_header_when_address_is_valid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "stamped.eml"
            with (
                patch(
                    "apple_mail_mcp.tools.compose.run_applescript",
                    return_value="default@example.com\nsecondary@example.org",
                ),
                patch("apple_mail_mcp.tools.compose.subprocess.run"),
            ):
                compose_tools.create_rich_email_draft(
                    account="Work",
                    subject="Stamped",
                    to="team@example.com",
                    text_body="Body",
                    output_path=str(output_path),
                    open_in_mail=False,
                    from_address="secondary@example.org",
                )

            payload = output_path.read_text()
            self.assertIn("From: secondary@example.org", payload)


class ReplyToEmailSenderOverrideTests(unittest.TestCase):
    def test_default_emits_single_alias_fallback_for_reply_message(self):
        with (
            patch(
                "apple_mail_mcp.tools.compose.subprocess.run",
                return_value=_make_subprocess_result(),
            ) as mock_run,
            patch(
                "apple_mail_mcp.tools.compose.run_applescript"
            ) as mock_applescript,
            # send=False maps to draft mode, which now reads the saved draft
            # back for verification (#71). Mocked here so this test -- which
            # is about the sender-alias fallback, not verification -- stays
            # isolated from Mail.app rather than issuing a real AppleScript
            # account lookup for an account ("Work") that doesn't exist on
            # whatever machine runs the suite.
            patch(
                "apple_mail_mcp.tools.compose.get_email_source",
                return_value="Error: account not found: Work",
            ),
        ):
            compose_tools.reply_to_email(
                account="Work",
                subject_keyword="test",
                reply_body="Reply body",
                send=False,
            )

        mock_applescript.assert_not_called()
        script = mock_run.call_args.kwargs["input"].decode("utf-8")
        self.assertIn("if (count of emailAddrs) is 1 then", script)
        self.assertIn(
            "set sender of replyMessage to item 1 of emailAddrs", script
        )
        self.assertNotIn('set sender of replyMessage to "', script)

    def test_injects_sender_when_from_address_is_valid(self):
        with (
            patch(
                "apple_mail_mcp.tools.compose.subprocess.run",
                return_value=_make_subprocess_result(),
            ) as mock_run,
            patch(
                "apple_mail_mcp.tools.compose.run_applescript",
                return_value="default@example.com\nsecondary@example.org",
            ),
            patch(
                "apple_mail_mcp.tools.compose.get_email_source",
                return_value="Error: account not found: Work",
            ),
        ):
            compose_tools.reply_to_email(
                account="Work",
                subject_keyword="test",
                reply_body="Reply body",
                from_address="secondary@example.org",
                send=False,
            )

        script = mock_run.call_args.kwargs["input"].decode("utf-8")
        self.assertIn(
            'set sender of replyMessage to "secondary@example.org"', script
        )
        self.assertNotIn("if (count of emailAddrs) is 1 then", script)

    def test_rejects_invalid_from_address_without_running_main_script(self):
        with (
            patch(
                "apple_mail_mcp.tools.compose.subprocess.run"
            ) as mock_run,
            patch(
                "apple_mail_mcp.tools.compose.run_applescript",
                return_value="default@example.com",
            ),
        ):
            result = compose_tools.reply_to_email(
                account="Work",
                subject_keyword="test",
                reply_body="Reply body",
                from_address="unknown@example.com",
                send=False,
            )

        mock_run.assert_not_called()
        self.assertTrue(result.startswith("Error: 'from_address'"))


class ForwardEmailSenderOverrideTests(unittest.TestCase):
    def test_default_emits_single_alias_fallback_for_forward_message(self):
        captured = []

        def fake_run(script, timeout=120):
            captured.append(script)
            return "✓ Forwarded"

        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            side_effect=fake_run,
        ):
            compose_tools.forward_email(
                account="Work",
                subject_keyword="test",
                to="recipient@example.com",
            )

        self.assertEqual(len(captured), 1)
        script = captured[0]
        self.assertIn("if (count of emailAddrs) is 1 then", script)
        self.assertIn(
            "set sender of forwardMessage to item 1 of emailAddrs", script
        )
        self.assertNotIn('set sender of forwardMessage to "', script)

    def test_injects_sender_when_from_address_is_valid(self):
        scripts = []

        def fake_run(script, timeout=120):
            scripts.append(script)
            if len(scripts) == 1:
                return "default@example.com\nsecondary@example.org"
            return "✓ Forwarded"

        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            side_effect=fake_run,
        ):
            compose_tools.forward_email(
                account="Work",
                subject_keyword="test",
                to="recipient@example.com",
                from_address="secondary@example.org",
            )

        self.assertEqual(len(scripts), 2)
        main_script = scripts[1]
        self.assertIn(
            'set sender of forwardMessage to "secondary@example.org"',
            main_script,
        )
        self.assertNotIn("if (count of emailAddrs) is 1 then", main_script)

    def test_rejects_invalid_from_address_without_running_main_script(self):
        scripts = []

        def fake_run(script, timeout=120):
            scripts.append(script)
            return "default@example.com"

        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            side_effect=fake_run,
        ):
            result = compose_tools.forward_email(
                account="Work",
                subject_keyword="test",
                to="recipient@example.com",
                from_address="unknown@example.com",
            )

        self.assertEqual(len(scripts), 1)
        self.assertTrue(result.startswith("Error: 'from_address'"))


class ManageDraftsCreateSenderOverrideTests(unittest.TestCase):
    def test_default_emits_single_alias_fallback_for_new_draft(self):
        captured = []

        def fake_run(script, timeout=120):
            captured.append(script)
            return "✓ Draft created"

        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            side_effect=fake_run,
        ):
            compose_tools.manage_drafts(
                account="Work",
                action="create",
                subject="Draft",
                to="recipient@example.com",
                body="Body",
            )

        self.assertEqual(len(captured), 1)
        script = captured[0]
        self.assertIn("if (count of emailAddrs) is 1 then", script)
        self.assertIn(
            "set sender of newDraft to item 1 of emailAddrs", script
        )
        self.assertNotIn('set sender of newDraft to "', script)

    def test_injects_sender_when_from_address_is_valid(self):
        scripts = []

        def fake_run(script, timeout=120):
            scripts.append(script)
            if len(scripts) == 1:
                return "default@example.com\nsecondary@example.org"
            return "✓ Draft created"

        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            side_effect=fake_run,
        ):
            compose_tools.manage_drafts(
                account="Work",
                action="create",
                subject="Draft",
                to="recipient@example.com",
                body="Body",
                from_address="secondary@example.org",
            )

        self.assertEqual(len(scripts), 2)
        main_script = scripts[1]
        self.assertIn(
            'set sender of newDraft to "secondary@example.org"', main_script
        )
        self.assertNotIn("if (count of emailAddrs) is 1 then", main_script)

    def test_rejects_invalid_from_address_without_running_main_script(self):
        scripts = []

        def fake_run(script, timeout=120):
            scripts.append(script)
            return "default@example.com"

        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            side_effect=fake_run,
        ):
            result = compose_tools.manage_drafts(
                account="Work",
                action="create",
                subject="Draft",
                to="recipient@example.com",
                body="Body",
                from_address="unknown@example.com",
            )

        self.assertEqual(len(scripts), 1)
        self.assertTrue(result.startswith("Error: 'from_address'"))


class PasteFocusHardeningTests(unittest.TestCase):
    """Regression guard for the silent empty-send bug.

    The HTML body is inserted via a blind Cmd+V into the compose window, which
    only lands if Mail is frontmost when the keystroke fires. The original code
    relied on a single `activate` + fixed `delay`, which intermittently sent an
    empty message when the window had not yet gained focus. The fix polls until
    Mail is genuinely frontmost before pasting. These tests assert the poll is
    present in the generated AppleScript and runs BEFORE the paste keystroke.

    They also lock in the deliberate decision NOT to verify via
    `content of <message>`: Mail's GUI editor buffer is decoupled from the
    scriptable `content` property, so a content-read-back guard would
    false-fail every send.
    """

    FOCUS_POLL = (
        'repeat until (frontmost of process "Mail") '
        "or (focusWaited is greater than or equal to 40)"
    )
    PASTE = 'keystroke "v" using command down'

    def _render_reply(self, **overrides):
        kwargs = dict(
            account="Work",
            subject_keyword="test",
            reply_body="Reply body text",
            body_html="<p>Reply body text</p>",
            send=True,
        )
        kwargs.update(overrides)
        with (
            patch(
                "apple_mail_mcp.tools.compose.subprocess.run",
                return_value=_make_subprocess_result(),
            ) as mock_run,
            patch(
                "apple_mail_mcp.tools.compose.run_applescript",
                return_value="a@b.com",
            ),
        ):
            compose_tools.reply_to_email(**kwargs)
        return mock_run.call_args.kwargs["input"].decode("utf-8")

    def _render_compose_html(self):
        with (
            patch(
                "apple_mail_mcp.tools.compose.subprocess.run",
                return_value=_make_subprocess_result(),
            ) as mock_run,
            patch(
                "apple_mail_mcp.tools.compose.run_applescript",
                return_value="a@b.com",
            ),
        ):
            compose_tools.compose_email(
                account="Work",
                to="x@example.com",
                subject="s",
                body="Body text",
                body_html="<p>Body text</p>",
                mode="send",
            )
        return mock_run.call_args.kwargs["input"].decode("utf-8")

    def test_reply_polls_for_focus_before_pasting(self):
        script = self._render_reply()
        self.assertIn(self.FOCUS_POLL, script)
        self.assertLess(
            script.index(self.FOCUS_POLL),
            script.index(self.PASTE),
            "focus poll must run before the paste keystroke",
        )

    def test_reply_drops_fragile_fixed_predelay(self):
        # The fragile original inserted a single `delay 1.5` between `activate`
        # and the paste, with no frontmost re-assertion. The fix replaces that
        # fixed gamble with a focus poll, so the 1.5s pre-paste delay is gone.
        script = self._render_reply()
        self.assertNotIn("delay 1.5", script)

    def test_reply_does_not_read_back_content_as_guard(self):
        # Mail's `content` property does not reflect a GUI paste, so any
        # `content of replyMessage` verification would false-fail every send.
        script = self._render_reply()
        self.assertNotIn("content of replyMessage", script)

    def test_compose_html_polls_for_focus_before_pasting(self):
        script = self._render_compose_html()
        self.assertIn(self.FOCUS_POLL, script)
        self.assertLess(
            script.index(self.FOCUS_POLL),
            script.index(self.PASTE),
            "focus poll must run before the paste keystroke",
        )


class HtmlBodyNoDuplicatePasteTests(unittest.TestCase):
    """Regression guard for the dual-body bug (#reported 2026-06-23).

    When both a plain body and ``body_html`` were supplied, the clipboard
    paste path wrote the raw HTML *source* under ``NSPasteboardTypeHTML``.
    For anything but a complete HTML document, Mail rendered a best-effort
    version AND surfaced the literal ``<p>``/``<b>`` markup, so the message
    appeared twice — once rendered, once as source. The fix converts the
    HTML to an NSAttributedString and writes it back as RTF (a single
    unambiguous rich-text flavor) plus a *rendered* plain-text fallback.

    These tests assert, at the script-generation level, that:
      * the raw-HTML flavor (``NSPasteboardTypeHTML``) is no longer written;
      * RTF is written via NSAttributedString -> RTFFromRange;
      * the plain body is never injected as a second visible paste.
    """

    BODY_PLAIN = "Plain fallback text"
    BODY_HTML = "<p>Rendered <b>HTML</b></p>"

    def _render_reply(self):
        with (
            patch(
                "apple_mail_mcp.tools.compose.subprocess.run",
                return_value=_make_subprocess_result(),
            ) as mock_run,
            patch(
                "apple_mail_mcp.tools.compose.run_applescript",
                return_value="a@b.com",
            ),
        ):
            compose_tools.reply_to_email(
                account="Work",
                subject_keyword="test",
                reply_body=self.BODY_PLAIN,
                body_html=self.BODY_HTML,
                mode="open",
            )
        return mock_run.call_args.kwargs["input"].decode("utf-8")

    def _render_compose(self):
        with (
            patch(
                "apple_mail_mcp.tools.compose.subprocess.run",
                return_value=_make_subprocess_result(),
            ) as mock_run,
            patch(
                "apple_mail_mcp.tools.compose.run_applescript",
                return_value="a@b.com",
            ),
        ):
            compose_tools.compose_email(
                account="Work",
                to="x@example.com",
                subject="s",
                body=self.BODY_PLAIN,
                body_html=self.BODY_HTML,
                mode="open",
            )
        return mock_run.call_args.kwargs["input"].decode("utf-8")

    def _render_forward(self):
        captured = {}

        def fake_run(*args, **kwargs):
            captured["input"] = kwargs.get("input")
            return _make_subprocess_result()

        with (
            patch(
                "apple_mail_mcp.tools.compose.subprocess.run",
                side_effect=fake_run,
            ),
            patch(
                "apple_mail_mcp.tools.compose.run_applescript",
                return_value="a@b.com",
            ),
        ):
            compose_tools.forward_email(
                account="Work",
                subject_keyword="test",
                to="x@example.com",
                message="A note before the forward",
            )
        return captured["input"].decode("utf-8")

    def _assert_rtf_not_raw_html(self, script):
        self.assertNotIn(
            "setData:htmlData forType:(current application's NSPasteboardTypeHTML)",
            script,
            "raw HTML source must not be placed on the pasteboard",
        )
        self.assertIn("NSPasteboardTypeRTF", script)
        self.assertIn("RTFFromRange", script)
        self.assertIn("NSAttributedString", script)
        # The HTML importer must be pinned to UTF-8, otherwise Cocoa auto-detects
        # the charset and defaults to Latin-1/Windows-1252, double-decoding the
        # UTF-8 bytes for ä/ö/ü/ß/emoji into mojibake (e.g. "Grüße" -> "GrÃ¼ÃŸe").
        self.assertIn("NSCharacterEncodingDocumentAttribute", script)
        self.assertIn("NSUTF8StringEncoding", script)

    def test_reply_uses_rtf_not_raw_html(self):
        self._assert_rtf_not_raw_html(self._render_reply())

    def test_compose_uses_rtf_not_raw_html(self):
        self._assert_rtf_not_raw_html(self._render_compose())

    def test_forward_uses_rtf_not_raw_html(self):
        self._assert_rtf_not_raw_html(self._render_forward())

    def test_reply_pastes_body_only_once(self):
        # Exactly one Cmd+V paste of the body — never the plain text as a
        # second visible paste alongside the HTML.
        script = self._render_reply()
        self.assertEqual(script.count('keystroke "v" using command down'), 1)

    def test_reply_plain_body_not_injected_as_content(self):
        # The plain reply_body must not be set as the message `content`
        # (which would render as a second body under the pasted HTML).
        script = self._render_reply()
        self.assertNotIn(f'content:"{self.BODY_PLAIN}"', script)


class PasteboardUtf8EncodingTests(unittest.TestCase):
    """Guards the multibyte-UTF-8 fix in _html_to_pasteboard_script.

    Regression: without NSCharacterEncodingDocumentAttribute -> NSUTF8StringEncoding,
    the Cocoa HTML importer defaulted to Latin-1 and turned German umlauts/ß and
    emoji into mojibake when relaying a body to Mail (reply/compose/forward).
    """

    def test_helper_pins_html_importer_to_utf8(self):
        snippet = compose_tools._html_to_pasteboard_script("/tmp/example.html")
        self.assertIn("NSCharacterEncodingDocumentAttribute", snippet)
        self.assertIn("NSUTF8StringEncoding", snippet)
        # Both the document-type and the encoding key must be in the options dict.
        self.assertIn("NSDocumentTypeDocumentAttribute", snippet)
        self.assertIn("NSHTMLTextDocumentType", snippet)
        self.assertIn("dictionaryWithObjects:", snippet)


class ClipboardRestoreTests(unittest.TestCase):
    """Regression for #106: the reply script returned before the code that
    restores the user's clipboard, so every reply left the body on it."""

    RESTORE = "pb's setString:oldClip forType:(current application's NSPasteboardTypeString)"

    def _render(self, func, **kwargs):
        with (
            patch(
                "apple_mail_mcp.tools.compose.subprocess.run",
                return_value=_make_subprocess_result(),
            ) as mock_run,
            patch(
                "apple_mail_mcp.tools.compose.run_applescript",
                return_value="a@b.com",
            ),
        ):
            func(account="Work", subject_keyword="test", **kwargs)
        return mock_run.call_args.kwargs["input"].decode("utf-8")

    @staticmethod
    def _return_lines(text):
        # AppleScript `return` statements; `& return &` (a newline) doesn't count.
        return [ln for ln in text.splitlines() if ln.strip().startswith("return ")]

    def test_reply_restores_clipboard_before_any_return(self):
        for mode in ("send", "draft", "open"):
            with self.subTest(mode=mode):
                script = self._render(
                    compose_tools.reply_to_email, reply_body="Hi", mode=mode
                )
                restore_at = script.rfind(self.RESTORE)
                self.assertNotEqual(restore_at, -1)
                self.assertEqual(self._return_lines(script[:restore_at]), [])
                self.assertEqual(
                    [ln.strip() for ln in self._return_lines(script[restore_at:])],
                    ["return outputText"],
                )

    def test_reply_waits_at_least_one_second_after_paste_before_restore(self):
        paste = 'keystroke "v" using command down'
        for mode in ("send", "draft", "open"):
            with self.subTest(mode=mode):
                script = self._render(
                    compose_tools.reply_to_email, reply_body="Hi", mode=mode
                )
                between = script[script.index(paste):script.rfind(self.RESTORE)]
                waited = sum(
                    float(m) for m in re.findall(r"^\s*delay ([0-9.]+)\s*$", between, re.M)
                )
                self.assertGreaterEqual(waited, 1.0)

    def test_forward_error_path_restores_clipboard(self):
        script = self._render(
            compose_tools.forward_email,
            to="x@example.com",
            message="A note",
        )
        error_block = script[script.index("on error errMsg"):]
        self.assertLess(
            error_block.index(self.RESTORE),
            error_block.index('return "Error: " & errMsg'),
        )

    def test_forward_without_message_has_no_clipboard_code(self):
        with (
            patch(
                "apple_mail_mcp.tools.compose.run_applescript",
                return_value="a@b.com",
            ) as mock_applescript,
        ):
            compose_tools.forward_email(
                account="Work", subject_keyword="test", to="x@example.com"
            )
        script = mock_applescript.call_args.args[0]
        self.assertNotIn("oldClip", script)


class ReplyDraftVerificationTests(unittest.TestCase):
    """Integration coverage for `_verify_saved_reply_body` (#71): the draft
    path reads the just-saved reply back and reports whether the body
    landed outside Mail's quoted original, rather than reporting success
    from the AppleScript's text presence alone."""

    def _run_reply(
        self, get_email_source_return, run_applescript_return="",
        saved_output=b"Reply saved as draft!\nSaved draft Message-ID: new@example.com",
        **overrides
    ):
        kwargs = dict(
            account="Work",
            subject_keyword="test",
            reply_body="Yes, 3pm works.",
            send=False,
        )
        kwargs.update(overrides)
        with (
            patch(
                "apple_mail_mcp.tools.compose.subprocess.run",
                return_value=_make_subprocess_result(
                    stdout=saved_output
                ),
            ),
            patch(
                "apple_mail_mcp.tools.compose.run_applescript",
                return_value=run_applescript_return,
            ),
            patch(
                "apple_mail_mcp.tools.compose.get_email_source",
                return_value=get_email_source_return,
            ) as mock_get_source,
        ):
            result = compose_tools.reply_to_email(**kwargs)
        return result, mock_get_source

    def test_missing_draft_identity_fails_without_subject_fallback(self):
        result, mock_get_source = self._run_reply(
            "Content-Type: text/plain\r\n\r\nYes, 3pm works.",
            saved_output=b"Reply saved as draft!",
        )
        self.assertTrue(result.startswith("Status: FAILED"), result)
        mock_get_source.assert_not_called()

    def test_draft_script_excludes_existing_ids_and_rejects_ambiguity(self):
        with (
            patch("apple_mail_mcp.tools.compose.subprocess.run",
                  return_value=_make_subprocess_result()) as mock_run,
            patch("apple_mail_mcp.tools.compose.run_applescript", return_value=""),
        ):
            compose_tools.reply_to_email("Work", "test", "Reply", send=False)
        script = mock_run.call_args.kwargs["input"].decode("utf-8")
        self.assertIn("set priorDraftIDs to id of every message of draftMailbox", script)
        self.assertLess(script.index("set priorDraftIDs"), script.index("set replyMessage to reply"))
        self.assertIn("whose subject is savedReplySubject", script)
        self.assertIn("priorDraftIDs does not contain", script)
        self.assertIn("if (count of newDraftMessageIDs) is greater than 1 then exit repeat", script)
        self.assertIn("set candidateMessageID to message id of candidate", script)
        self.assertIn("Saved draft Message-ID: ", script)

    def _draft_script(self):
        with (
            patch("apple_mail_mcp.tools.compose.subprocess.run",
                  return_value=_make_subprocess_result()) as mock_run,
            patch("apple_mail_mcp.tools.compose.run_applescript", return_value=""),
        ):
            compose_tools.reply_to_email("Work", "test", "Reply", send=False)
        return mock_run.call_args.kwargs["input"].decode("utf-8")

    def test_drafts_snapshot_has_its_own_try(self):
        """A missing "Drafts" mailbox must not abort the reply itself."""
        script = self._draft_script()
        snapshot = script.index("set priorDraftIDs to id of every message of draftMailbox")
        # The bare "try" line that opens the snapshot's guarded block.
        own_try = script.index("\n            try\n", script.index("set draftSnapshotOK to false"))
        self.assertLess(own_try, script.index("set draftMailbox to mailbox"))
        main_try_end = script.index("on error errMsg")
        # Defaults are set before the guarded block, so later code always sees them.
        self.assertLess(script.index("set priorDraftIDs to {}"), own_try)
        self.assertLess(script.index("set draftSnapshotOK to false"), own_try)
        self.assertLess(script.index("set draftMailbox to missing value"), own_try)
        # The snapshot's own try closes before the reply is created.
        own_end = script.index("end try", snapshot)
        self.assertLess(snapshot, script.index("set draftSnapshotOK to true"))
        self.assertLess(script.index("set draftSnapshotOK to true"), own_end)
        self.assertLess(own_end, script.index("set replyMessage to reply"))
        self.assertLess(own_end, main_try_end)
        # No lookup against the Drafts mailbox runs without a snapshot.
        lookup = script.index("whose subject is savedReplySubject")
        self.assertLess(script.index("if draftSnapshotOK then"), lookup)

    def test_new_candidates_sharing_one_message_id_count_as_one(self):
        """Gmail autosave copies share a Message-ID and are one draft."""
        script = self._draft_script()
        self.assertIn(
            "if newDraftMessageIDs does not contain candidateMessageID then", script
        )
        self.assertIn("set candidateMessageID to item 1 of newDraftMessageIDs", script)
        self.assertNotIn("count of newDrafts", script)

    def test_missing_drafts_mailbox_reports_failed_but_draft_saved(self):
        result, mock_get_source = self._run_reply(
            "Content-Type: text/plain\r\n\r\nYes, 3pm works.",
            saved_output=(
                b"Note: could not read the Drafts mailbox, so the saved draft "
                b"cannot be verified.\nSaved draft Message-ID: \n"
                b"Reply saved as draft!\nTo: a@example.com"
            ),
        )
        self.assertTrue(result.startswith("Status: FAILED"), result)
        self.assertIn("Reply saved as draft!", result)
        self.assertIn("could not read the Drafts mailbox", result)
        mock_get_source.assert_not_called()

    def test_html_sent_is_verified_instead_of_plain_fallback(self):
        result, _ = self._run_reply(
            'Content-Type: text/html\r\n\r\n<p>Actual HTML</p><blockquote type="cite">old</blockquote>',
            reply_body="Different fallback", body_html="<p>Actual <b>HTML</b></p>",
        )
        self.assertIn("Verification (PASSED)", result)

    def test_failure_status_leads_with_reason(self):
        result, _ = self._run_reply("Content-Type: text/plain\r\n\r\n> Yes, 3pm works.")
        self.assertTrue(result.startswith("Status: FAILED"), result)
        self.assertIn("only inside", result.splitlines()[0])

    def test_success_status_leads_result(self):
        result, _ = self._run_reply("Content-Type: text/plain\r\n\r\nYes, 3pm works.")
        self.assertTrue(result.startswith("Status: VERIFIED"), result)

    def test_source_error_is_a_leading_failure(self):
        result, _ = self._run_reply("Error: draft unavailable")
        self.assertTrue(result.startswith("Status: FAILED"), result)

    def test_body_outside_quote_reports_passed(self):
        result, mock_get_source = self._run_reply(
            "Content-Type: text/plain\r\n\r\n"
            "Yes, 3pm works.\r\n\r\n> On Jan 1, sender wrote:\r\n> hi\r\n"
        )

        self.assertIn("Verification (PASSED)", result)
        mock_get_source.assert_called_once_with(
            account="Work", message_id="new@example.com", mailbox="Drafts"
        )

    def test_body_inside_quote_reports_failed(self):
        """The #71 bug, caught rather than reported as a success."""
        result, _ = self._run_reply(
            "Content-Type: text/plain\r\n\r\n"
            "> Yes, 3pm works.\r\n> On Jan 1, sender wrote:\r\n> hi\r\n"
        )

        self.assertIn("Verification (FAILED)", result)
        self.assertIn("only inside the quoted original", result)

    def test_get_email_source_error_is_reported_not_swallowed(self):
        result, _ = self._run_reply("Error: account not found: Work")

        self.assertIn("could not re-read the saved draft", result)

    def test_no_overrides_reports_actual_saved_recipients(self):
        result, _ = self._run_reply(
            "From: sender@example.com\r\nTo: alice@example.com\r\nCc: bob@example.com\r\n"
            "Content-Type: text/plain\r\n\r\nYes, 3pm works.",
            reply_to_all=True,
        )
        self.assertIn("Recipients (PASSED): To=['alice@example.com'] "
                      "Cc=['bob@example.com'] From=['sender@example.com']", result)

    def test_requested_cc_actually_saved_reports_passed(self):
        """#70: verify the CC the caller asked for actually landed in the
        saved draft, instead of trusting the request was honored."""
        result, _ = self._run_reply(
            "To: alice@example.com\r\nCc: carol@example.com\r\n"
            "Content-Type: text/plain\r\n\r\n"
            "Yes, 3pm works.\r\n\r\n> On Jan 1, sender wrote:\r\n> hi\r\n",
            cc="carol@example.com",
        )

        self.assertIn("Recipients (PASSED)", result)

    def test_requested_cc_missing_from_saved_draft_reports_failed(self):
        """The exact #70 scenario: a requested CC that Mail silently
        dropped (e.g. bad address) must be caught, not glossed over."""
        result, _ = self._run_reply(
            "To: alice@example.com\r\n"
            "Content-Type: text/plain\r\n\r\n"
            "Yes, 3pm works.\r\n\r\n> On Jan 1, sender wrote:\r\n> hi\r\n",
            cc="carol@example.com",
        )

        self.assertIn("Recipients (FAILED)", result)
        self.assertIn("carol@example.com", result)

    def test_from_address_override_verified_against_saved_draft(self):
        """A `from_address` override that Mail actually honored should
        verify as PASSED against the saved draft's real From: header."""
        result, _ = self._run_reply(
            "From: alice@example.com\r\nTo: bob@example.com\r\n"
            "Content-Type: text/plain\r\n\r\n"
            "Yes, 3pm works.\r\n\r\n> On Jan 1, sender wrote:\r\n> hi\r\n",
            run_applescript_return="alice@example.com",
            from_address="alice@example.com",
        )

        self.assertIn("Recipients (PASSED)", result)

    def test_from_address_override_not_applied_reports_failed(self):
        """If Mail did not actually stamp the requested From: address into
        the saved draft, that must surface as a failure, not a silent
        assumption that the override took effect."""
        result, _ = self._run_reply(
            "From: work-default@example.com\r\nTo: bob@example.com\r\n"
            "Content-Type: text/plain\r\n\r\n"
            "Yes, 3pm works.\r\n\r\n> On Jan 1, sender wrote:\r\n> hi\r\n",
            run_applescript_return="alice@example.com",
            from_address="alice@example.com",
        )

        self.assertIn("Recipients (FAILED)", result)
        self.assertIn("not found in saved From", result)

    def test_send_mode_does_not_attempt_verification(self):
        """Verification only runs for mode='draft' (see docstring on
        `_verify_saved_reply_body` for why send/open are out of scope)."""
        with (
            patch(
                "apple_mail_mcp.tools.compose.subprocess.run",
                return_value=_make_subprocess_result(
                    stdout=b"Reply sent successfully!"
                ),
            ),
            patch("apple_mail_mcp.tools.compose.run_applescript"),
            patch(
                "apple_mail_mcp.tools.compose.get_email_source"
            ) as mock_get_source,
        ):
            result = compose_tools.reply_to_email(
                account="Work",
                subject_keyword="test",
                reply_body="Yes, 3pm works.",
                send=True,
            )

        mock_get_source.assert_not_called()
        self.assertNotIn("Verification", result)

    def test_open_mode_does_not_attempt_verification(self):
        with (
            patch(
                "apple_mail_mcp.tools.compose.subprocess.run",
                return_value=_make_subprocess_result(
                    stdout=b"Reply opened in Mail for review."
                ),
            ),
            patch("apple_mail_mcp.tools.compose.run_applescript"),
            patch(
                "apple_mail_mcp.tools.compose.get_email_source"
            ) as mock_get_source,
        ):
            result = compose_tools.reply_to_email(
                account="Work",
                subject_keyword="test",
                reply_body="Yes, 3pm works.",
                mode="open",
            )

        mock_get_source.assert_not_called()
        self.assertNotIn("Verification", result)

    def test_applescript_error_does_not_attempt_verification(self):
        """If the reply itself failed, there is no saved draft to read back."""
        with (
            patch(
                "apple_mail_mcp.tools.compose.subprocess.run",
                return_value=_make_subprocess_result(
                    stdout=b"No email found matching: test"
                ),
            ),
            patch("apple_mail_mcp.tools.compose.run_applescript"),
            patch(
                "apple_mail_mcp.tools.compose.get_email_source"
            ) as mock_get_source,
        ):
            compose_tools.reply_to_email(
                account="Work",
                subject_keyword="test",
                reply_body="Yes, 3pm works.",
                send=False,
            )

        mock_get_source.assert_not_called()


class ComposeFontStyleTests(unittest.TestCase):
    """Reply, forward and plain-text rich drafts share one font style (#100)."""

    def _capture_pasted_html(self, call):
        """Run ``call`` and return the HTML file content the script pastes."""
        captured = []

        def fake_run(args, input=None, **kwargs):
            script = input.decode("utf-8")
            match = re.search(r"cat '([^']+\.html)'", script)
            self.assertIsNotNone(match, "script does not read an HTML temp file")
            with open(match.group(1), encoding="utf-8") as fh:
                captured.append(fh.read())
            return _make_subprocess_result(stdout=b"ok")

        with (
            patch("apple_mail_mcp.tools.compose.subprocess.run", side_effect=fake_run),
            patch("apple_mail_mcp.tools.compose.run_applescript", return_value=""),
        ):
            call()
        self.assertEqual(len(captured), 1)
        return captured[0]

    def test_reply_html_carries_font_style(self):
        html = self._capture_pasted_html(
            lambda: compose_tools.reply_to_email(
                "Work", "test", "Sounds good", mode="open"
            )
        )
        self.assertIn(f'style="{compose_tools._COMPOSE_FONT_STYLE}"', html)
        self.assertIn("Sounds good", html)

    def test_forward_html_carries_font_style(self):
        html = self._capture_pasted_html(
            lambda: compose_tools.forward_email(
                "Work", "test", "to@example.com", message="FYI below"
            )
        )
        self.assertIn(f'style="{compose_tools._COMPOSE_FONT_STYLE}"', html)
        self.assertIn("FYI below", html)

    def test_plain_text_rich_body_reuses_font_style(self):
        html = compose_tools._build_html_from_text("hello")
        self.assertEqual(html.count(compose_tools._COMPOSE_FONT_STYLE), 2)
        self.assertIn("white-space: pre-wrap", html)


if __name__ == "__main__":
    unittest.main()

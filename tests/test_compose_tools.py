"""Tests for compose and rich draft helpers."""

import tempfile
import re
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


def _reply_lookup_payload(script, subject="Original subject", sender="them@example.com"):
    """Answer _find_reply_target's lookup script with a well-formed payload.

    The separator is generated per call and embedded in the script, so the
    fake reads it back out instead of hard-coding it.
    """
    match = re.search(r"<<<AMMCP-[0-9a-f]+>>>", script)
    if not match:
        return ""
    sep = match.group(0)
    return sep.join(
        ["4711", subject, sender, "Tuesday, 25 August 2026 at 16:28:42", "1", "Original body"]
    )


def _fake_reply_run(alias_answer=None):
    """Return a run_applescript double for the GUI-free reply path.

    First it answers any sender-alias lookup, then the target lookup, then the
    reply script itself.
    """
    scripts = []

    def _run(script, timeout=120):
        scripts.append(script)
        if "email addresses of targetAccount" in script and "reply foundMessage" not in script:
            return alias_answer or ""
        if "<<<AMMCP-" in script:
            return _reply_lookup_payload(script)
        return "Reply saved as draft!"

    return _run, scripts

def _main_script(scripts):
    """Return the compose script from a list of captured AppleScript calls.

    Sender lookups run before the main script and the draft-location check
    runs after it, so the main script is identified by content, not position.
    """
    for script in scripts:
        if "make new outgoing message" in script:
            return script
    raise AssertionError("no compose script captured")


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

        script = _main_script(captured)
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

        main_script = _main_script(scripts)
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
        # A plain-text reply runs GUI-free through run_applescript; only an
        # HTML body still goes through the clipboard/keystroke route.
        fake_run, scripts = _fake_reply_run()
        with (
            patch(
                "apple_mail_mcp.tools.compose.subprocess.run"
            ) as mock_subprocess,
            patch(
                "apple_mail_mcp.tools.compose.run_applescript",
                side_effect=fake_run,
            ),
        ):
            compose_tools.reply_to_email(
                account="Work",
                subject_keyword="test",
                reply_body="Reply body",
                send=False,
            )

        mock_subprocess.assert_not_called()
        script = next(s for s in scripts if "reply foundMessage" in s)
        self.assertIn("if (count of emailAddrs) is 1 then", script)
        self.assertIn(
            "set sender of replyMessage to item 1 of emailAddrs", script
        )
        self.assertNotIn('set sender of replyMessage to "', script)

    def test_injects_sender_when_from_address_is_valid(self):
        fake_run, scripts = _fake_reply_run(
            alias_answer="default@example.com\nsecondary@example.org"
        )
        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            side_effect=fake_run,
        ):
            compose_tools.reply_to_email(
                account="Work",
                subject_keyword="test",
                reply_body="Reply body",
                from_address="secondary@example.org",
                send=False,
            )

        script = next(s for s in scripts if "reply foundMessage" in s)
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

        script = _main_script(captured)
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

        main_script = _main_script(scripts)
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


if __name__ == "__main__":
    unittest.main()


class ReadOnlyModeTests(unittest.TestCase):
    """--read-only blocks delivery, not the draft and review modes."""

    def setUp(self):
        self._previous = compose_tools.server.READ_ONLY
        compose_tools.server.READ_ONLY = True

    def tearDown(self):
        compose_tools.server.READ_ONLY = self._previous

    def test_compose_email_refuses_to_send(self):
        with patch("apple_mail_mcp.tools.compose.run_applescript") as mock_run:
            result = compose_tools.compose_email(
                account="Work",
                to="someone@example.com",
                subject="Test",
                body="Body",
                mode="send",
            )

        mock_run.assert_not_called()
        self.assertTrue(result.startswith("Error: Sending is disabled"))

    def test_compose_email_still_drafts(self):
        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            return_value="DRAFT SAVED",
        ):
            result = compose_tools.compose_email(
                account="Work",
                to="someone@example.com",
                subject="Test",
                body="Body",
                mode="draft",
            )

        self.assertNotIn("Error: Sending is disabled", result)

    def test_reply_refuses_to_send_via_send_flag(self):
        with patch("apple_mail_mcp.tools.compose.run_applescript") as mock_run:
            result = compose_tools.reply_to_email(
                account="Work",
                subject_keyword="Invoice",
                reply_body="Body",
                send=True,
            )

        mock_run.assert_not_called()
        self.assertTrue(result.startswith("Error: Sending is disabled"))

    def test_reply_still_drafts(self):
        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            return_value="DRAFT SAVED",
        ):
            result = compose_tools.reply_to_email(
                account="Work",
                subject_keyword="Invoice",
                reply_body="Body",
                mode="draft",
            )

        self.assertNotIn("Error: Sending is disabled", result)

    def test_read_only_flag_is_read_at_call_time(self):
        """Regression: the module used to bind READ_ONLY's value at import."""
        compose_tools.server.READ_ONLY = False

        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            return_value="SENT",
        ):
            result = compose_tools.compose_email(
                account="Work",
                to="someone@example.com",
                subject="Test",
                body="Body",
                mode="send",
            )

        self.assertNotIn("Error: Sending is disabled", result)


class MailShareWrapperTests(unittest.TestCase):
    """Peeling Mail's share template off a stored body.

    macOS 15+ Mail wraps every AppleScript-supplied body in
    ``Apple-Mail-URLShareWrapperClass`` / ``blockquote type="cite"``. That
    cannot be prevented, but it must not stack: before the fix, every edit of
    a draft fed the already-wrapped body back through the composer and gained
    another layer. Measured on a real draft (861590DD, 05.09.2026) at two
    layers deep.
    """

    WRAPPED = (
        '<html><body>'
        '<div class="Apple-Mail-URLShareUserContentTopClass"><br></div>'
        '<div class="Apple-Mail-URLShareWrapperClass" style="position: relative !important;">'
        '<blockquote type="cite" style="border-left-style: none; color: inherit;'
        ' padding: inherit; margin: inherit;">'
        '<p>Gr&uuml;&szlig;e</p>'
        '</blockquote></div>'
        '</body></html>'
    )

    def test_single_layer_is_removed(self):
        stripped = compose_tools._strip_mail_share_wrapper(self.WRAPPED)
        self.assertNotIn("URLShareWrapperClass", stripped)
        self.assertNotIn("blockquote", stripped)
        self.assertIn("<p>Gr&uuml;&szlig;e</p>", stripped)

    def test_nested_layers_are_all_removed(self):
        nested = (
            '<body><div dir="auto">'
            '<div class="Apple-Mail-URLShareUserContentTopClass"><br></div>'
            '<div class="Apple-Mail-URLShareWrapperClass"><blockquote type="cite">'
            '<div class="Apple-Mail-URLShareUserContentTopClass"><br></div>'
            '<div class="Apple-Mail-URLShareWrapperClass"><blockquote type="cite">'
            "Kern"
            "</blockquote></div>"
            "</blockquote></div></div></body>"
        )
        stripped = compose_tools._strip_mail_share_wrapper(nested)
        self.assertNotIn("blockquote", stripped)
        self.assertNotIn("URLShare", stripped)
        self.assertIn("Kern", stripped)

    def test_top_div_with_real_content_is_kept(self):
        # Text typed above the wrapper lives in the top div. Dropping the div
        # wholesale would silently delete it.
        html = (
            '<div class="Apple-Mail-URLShareUserContentTopClass">Eigene Notiz</div>'
            '<div class="Apple-Mail-URLShareWrapperClass"><blockquote type="cite">'
            "Kern</blockquote></div>"
        )
        stripped = compose_tools._strip_mail_share_wrapper(html)
        self.assertIn("Eigene Notiz", stripped)
        self.assertIn("Kern", stripped)

    def test_unbalanced_markup_is_left_alone(self):
        # Cutting at a guessed offset would truncate the body. Better to hand
        # back the original and let the caller fall back.
        broken = '<div class="Apple-Mail-URLShareWrapperClass"><blockquote type="cite">abgeschnitten'
        self.assertEqual(compose_tools._strip_mail_share_wrapper(broken), broken)

    def test_body_without_wrapper_is_untouched(self):
        plain = "<p>nur Text</p>"
        self.assertEqual(compose_tools._strip_mail_share_wrapper(plain), plain)

    def test_signature_block_and_its_leading_breaks_are_removed(self):
        html = (
            "<p>Text</p><br><br>"
            '<div id="AppleMailSignature">'
            '<div class="ApplePlainTextBody"><table><tbody><tr><td>Robin</td>'
            "</tr></tbody></table><div><br></div></div>"
            "</div>"
        )
        stripped = compose_tools._strip_mail_signature_block(html)
        self.assertEqual(stripped, "<p>Text</p>")

    def test_signature_strip_is_a_no_op_without_a_signature(self):
        html = "<p>Text</p>"
        self.assertEqual(compose_tools._strip_mail_signature_block(html), html)

    def test_matching_close_counts_nesting(self):
        html = "<div>a<div>b</div>c</div>tail"
        close = compose_tools._matching_close(html, len("<div>"), "div")
        self.assertIsNotNone(close)
        self.assertEqual(html[close[1]:], "tail")


class DraftUpdateKeepsSignatureTests(unittest.TestCase):
    """Editing a draft must not cost it its signature.

    Before the fix, _update_draft rebuilt the message from
    ``content of theDraft`` — Mail's plain-text rendering — and then set
    ``message signature`` to ``missing value`` so the flattened copy inside
    that string would not be doubled. Result: no X-Apple-Mail-Signature
    header, Mail's compose window showing "Signature: None", and a signature
    that had lost its table, image and colours. Measured on draft 861590DD
    (05.09.2026). Now the stored HTML is reused, the baked-in signature is
    cut out of it, and Mail attaches the live one again.
    """

    STORED_HTML = (
        "<html><body>"
        '<div class="Apple-Mail-URLShareUserContentTopClass"><br></div>'
        '<div class="Apple-Mail-URLShareWrapperClass"><blockquote type="cite">'
        "<p>Hallo <b>Tomy</b></p>"
        "</blockquote></div><br><br>"
        '<div id="AppleMailSignature"><table><tbody><tr><td>Robin</td></tr></tbody></table></div>'
        "</body></html>"
    )

    def _fields(self, **overrides):
        fields = {
            "id": "42",
            "account": "Work",
            "subject": "Alt",
            "to": ["a@example.com"],
            "cc": [],
            "bcc": [],
            "attachments": [],
            "sender": "me@example.com",
            "content": "Hallo Tomy\n\nRobin\nFull Stack Developer",
        }
        fields.update(overrides)
        return fields

    def _run_update(self, html_body, **kwargs):
        scripts = []
        written = {}

        real_named_tempfile = compose_tools.tempfile.NamedTemporaryFile

        def spy_tempfile(*args, **tf_kwargs):
            handle = real_named_tempfile(*args, **tf_kwargs)
            original_write = handle.write

            def capture(text):
                written["body"] = text
                return original_write(text)

            handle.write = capture
            return handle

        def _run(script, timeout=120):
            scripts.append(script)
            return "ok"

        with patch.object(
            compose_tools, "_read_draft", return_value=(self._fields(), None)
        ), patch.object(
            compose_tools, "_draft_html_body", return_value=html_body
        ), patch.object(
            compose_tools, "_export_draft_attachments", return_value=([], None)
        ), patch.object(
            compose_tools, "run_applescript", side_effect=_run
        ), patch.object(
            compose_tools, "_draft_id_for_subject", return_value="43"
        ), patch.object(
            compose_tools, "_delete_draft_by_id", return_value=True
        ), patch.object(
            compose_tools, "_discard_draft_export"
        ), patch.object(
            compose_tools, "_draft_location_note", return_value=""
        ), patch.object(
            compose_tools.tempfile, "NamedTemporaryFile", side_effect=spy_tempfile
        ):
            result = compose_tools._update_draft(
                account="Work", draft_subject="Alt", **kwargs
            )
        build = next(s for s in scripts if "make new outgoing message" in s)
        return result, build, written.get("body", "")

    def test_reused_html_keeps_the_live_signature(self):
        result, build, body = self._run_update(self.STORED_HTML)
        self.assertNotIn("set message signature", build)
        self.assertIn("set html content of newDraft to draftBodyText", build)
        self.assertNotIn("AppleMailSignature", body)
        self.assertIn("HTML formatting and signature kept", result)

    def test_reused_html_does_not_gain_a_wrapper_layer(self):
        _, _, body = self._run_update(self.STORED_HTML)
        self.assertNotIn("URLShareWrapperClass", body)
        self.assertNotIn("blockquote", body)
        self.assertIn("<p>Hallo <b>Tomy</b></p>", body)

    def test_body_is_set_before_the_attachments_are_re_added(self):
        # Kept attachments are re-attached from disk after the rebuild.
        # `set html content` replaces the whole body, so it has to run first
        # or the freshly attached files are dropped again.
        scripts = []

        def _run(script, timeout=120):
            scripts.append(script)
            return "ok"

        with patch.object(
            compose_tools,
            "_read_draft",
            return_value=(self._fields(attachments=["rechnung.pdf"]), None),
        ), patch.object(
            compose_tools, "_draft_html_body", return_value=self.STORED_HTML
        ), patch.object(
            compose_tools,
            "_export_draft_attachments",
            return_value=(["/tmp/rechnung.pdf"], None),
        ), patch.object(
            compose_tools, "run_applescript", side_effect=_run
        ), patch.object(
            compose_tools, "_draft_id_for_subject", return_value="43"
        ), patch.object(
            compose_tools, "_delete_draft_by_id", return_value=True
        ), patch.object(
            compose_tools, "_discard_draft_export"
        ), patch.object(
            compose_tools, "_draft_location_note", return_value=""
        ):
            result = compose_tools._update_draft(account="Work", draft_subject="Alt")
        build = next(s for s in scripts if "make new outgoing message" in s)
        self.assertLess(
            build.index("set html content of newDraft to draftBodyText"),
            build.index("make new attachment"),
            "the body must be set before any attachment is re-added",
        )
        self.assertIn("is flattened", result)

    def test_falls_back_to_plain_text_when_html_is_unreadable(self):
        # No HTML part in the stored source (or Mail refused to hand it over):
        # rebuild from the plain rendering exactly as before, and say so.
        result, build, body = self._run_update(None)
        self.assertIn("set message signature of newDraft to missing value", build)
        self.assertIn("content:draftBodyText", build)
        self.assertIn("plain text", result)
        self.assertIn("Hallo Tomy", body)

    def test_empty_html_falls_back_too(self):
        # A wrapper holding nothing but the signature strips down to nothing.
        empty = (
            '<div class="Apple-Mail-URLShareWrapperClass"><blockquote type="cite">'
            "</blockquote></div>"
            '<div id="AppleMailSignature">Robin</div>'
        )
        _, build, _ = self._run_update(empty)
        self.assertIn("set message signature of newDraft to missing value", build)

    def test_new_body_still_lets_mail_add_the_signature(self):
        _, build, body = self._run_update(
            self.STORED_HTML, body="Komplett neuer Text"
        )
        self.assertNotIn("set message signature", build)
        self.assertIn("content:draftBodyText", build)
        self.assertEqual(body, "Komplett neuer Text")


class DraftHtmlBodyTests(unittest.TestCase):
    """_draft_html_body pulls the real HTML out of the raw message."""

    SOURCE = (
        "Subject: Test\n"
        "Mime-Version: 1.0\n"
        'Content-Type: multipart/alternative; boundary="B"\n'
        "\n"
        "--B\n"
        "Content-Type: text/plain; charset=us-ascii\n"
        "\n"
        "Fallback\n"
        "--B\n"
        "Content-Transfer-Encoding: quoted-printable\n"
        "Content-Type: text/html; charset=utf-8\n"
        "\n"
        "<p>Gr=C3=BC=C3=9Fe</p>\n"
        "--B--\n"
    )

    def test_html_part_is_decoded(self):
        with patch.object(compose_tools, "run_applescript", return_value=self.SOURCE):
            body = compose_tools._draft_html_body("42", "Work")
        self.assertIsNotNone(body)
        self.assertIn("Grüße", body)

    def test_missing_html_part_returns_none(self):
        plain = "Subject: Test\nContent-Type: text/plain\n\nNur Text\n"
        with patch.object(compose_tools, "run_applescript", return_value=plain):
            self.assertIsNone(compose_tools._draft_html_body("42", "Work"))

    def test_applescript_failure_returns_none(self):
        with patch.object(
            compose_tools, "run_applescript", side_effect=Exception("boom")
        ):
            self.assertIsNone(compose_tools._draft_html_body("42", "Work"))

    def test_non_numeric_id_is_refused_without_running_a_script(self):
        # Mail's message id is numeric and goes into the script unquoted.
        # Anything else must not reach osascript.
        with patch.object(compose_tools, "run_applescript") as mock_run:
            self.assertIsNone(
                compose_tools._draft_html_body('1 or true; do shell script "x"', "Work")
            )
        mock_run.assert_not_called()

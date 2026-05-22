"""Tests for compose and rich draft helpers."""

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
    def test_compose_defaults_to_draft_mode(self):
        captured = []

        def fake_run(script, timeout=120):
            captured.append(script)
            return "✓ Email saved as draft!"

        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            side_effect=fake_run,
        ):
            compose_tools.compose_email(
                account="Work",
                to="self@example.com",
                subject="Test",
                body="Body",
            )

        self.assertIn("SAVING EMAIL AS DRAFT", captured[0])
        self.assertIn("close window 1 saving yes", captured[0])
        self.assertNotIn("send newMessage", captured[0])

    def test_draft_safe_blocks_explicit_send(self):
        with patch.object(compose_tools.server, "DRAFT_SAFE", True):
            result = compose_tools.compose_email(
                account="Work",
                to="self@example.com",
                subject="Test",
                body="Body",
                mode="send",
            )

        self.assertIn("draft-safe mode", result)

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
    def test_reply_defaults_to_draft_mode(self):
        captured = []

        def fake_run(script, timeout=120):
            captured.append(script)
            return "ok"

        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            side_effect=fake_run,
        ):
            compose_tools.reply_to_email(
                account="Work",
                subject_keyword="test",
                reply_body="Reply body",
            )

        self.assertEqual(len(captured), 1)
        script = captured[0]
        self.assertIn("SAVING REPLY AS DRAFT", script)
        self.assertIn("close window 1 saving yes", script)
        self.assertNotIn("send replyMessage", script)

    def test_default_emits_single_alias_fallback_for_reply_message(self):
        captured = []

        def fake_run(script, timeout=120):
            captured.append(script)
            return "ok"

        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            side_effect=fake_run,
        ):
            compose_tools.reply_to_email(
                account="Work",
                subject_keyword="test",
                reply_body="Reply body",
                send=False,
            )

        self.assertEqual(len(captured), 1)
        script = captured[0]
        self.assertIn("if (count of emailAddrs) is 1 then", script)
        self.assertIn(
            "set sender of replyMessage to item 1 of emailAddrs", script
        )
        self.assertNotIn('set sender of replyMessage to "', script)

    def test_injects_sender_when_from_address_is_valid(self):
        scripts = []

        def fake_run(script, timeout=120):
            scripts.append(script)
            if len(scripts) == 1:
                return "default@example.com\nsecondary@example.org"
            return "ok"

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

        self.assertEqual(len(scripts), 2)
        script = scripts[1]
        self.assertIn(
            'set sender of replyMessage to "secondary@example.org"', script
        )
        self.assertNotIn("if (count of emailAddrs) is 1 then", script)

    def test_rejects_invalid_from_address_without_running_main_script(self):
        scripts = []

        def fake_run(script, timeout=120):
            scripts.append(script)
            return "default@example.com"

        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            side_effect=fake_run,
        ):
            result = compose_tools.reply_to_email(
                account="Work",
                subject_keyword="test",
                reply_body="Reply body",
                from_address="unknown@example.com",
                send=False,
            )

        self.assertEqual(len(scripts), 1)
        self.assertTrue(result.startswith("Error: 'from_address'"))


class ForwardEmailSenderOverrideTests(unittest.TestCase):
    def test_forward_defaults_to_draft_mode(self):
        captured = []

        def fake_run(script, timeout=120):
            captured.append(script)
            return "✓ Forward saved"

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
        self.assertIn("SAVING FORWARD AS DRAFT", captured[0])
        self.assertIn("close window 1 saving yes", captured[0])
        self.assertNotIn("send forwardMessage", captured[0])

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


class ComposeRunApplescriptMigrationTests(unittest.TestCase):
    def test_reply_to_email_forwards_timeout_to_run_applescript(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["timeout"] = timeout
            return "ok"

        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            side_effect=fake_run,
        ):
            compose_tools.reply_to_email(
                account="Work",
                subject_keyword="Invoice",
                reply_body="Thanks",
                timeout=240,
            )

        self.assertEqual(captured["timeout"], 240)

    def test_send_html_email_uses_run_applescript(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            captured["timeout"] = timeout
            return "Email saved as draft (HTML)"

        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            side_effect=fake_run,
        ):
            result = compose_tools.compose_email(
                account="Work",
                to="team@example.com",
                subject="Hi",
                body="Plain",
                body_html="<p>Hi</p>",
                mode="draft",
                timeout=90,
            )

        self.assertIn("use framework", captured["script"])
        self.assertEqual(captured["timeout"], 90)
        self.assertIn("Email saved as draft (HTML)", result)

    def test_forward_with_message_uses_run_applescript(self):
        captured = []

        def fake_run(script, timeout=120):
            captured.append(script)
            return "✓ Forward saved"

        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            side_effect=fake_run,
        ):
            compose_tools.forward_email(
                account="Work",
                subject_keyword="test",
                to="recipient@example.com",
                message="Please review",
            )

        self.assertEqual(len(captured), 1)
        self.assertIn("use framework", captured[0])

    def test_split_addresses_dedup_filters_empty_segments(self):
        self.assertEqual(
            compose_tools._split_addresses("a@x.com, , b@y.com"),
            ["a@x.com", "b@y.com"],
        )
        self.assertEqual(compose_tools._split_addresses(""), [])
        self.assertEqual(compose_tools._split_addresses(None), [])

    def test_build_recipient_loops_message_var_and_addresses(self):
        cc_script, bcc_script, cc_addrs, bcc_addrs = (
            compose_tools._build_recipient_loops(
                "a@x.com, b@y.com",
                "c@z.com",
                message_var="replyMessage",
            )
        )
        self.assertEqual(cc_addrs, ["a@x.com", "b@y.com"])
        self.assertEqual(bcc_addrs, ["c@z.com"])
        self.assertIn(
            "make new cc recipient at end of cc recipients of replyMessage",
            cc_script,
        )
        self.assertIn('address:"a@x.com"', cc_script)
        self.assertIn(
            "make new bcc recipient at end of bcc recipients of replyMessage",
            bcc_script,
        )
        self.assertIn('address:"c@z.com"', bcc_script)

    def test_build_recipient_loops_compact_empty(self):
        cc_script, bcc_script, cc_addrs, bcc_addrs = (
            compose_tools._build_recipient_loops(None, "", compact=True)
        )
        self.assertEqual(cc_addrs, [])
        self.assertEqual(bcc_addrs, [])
        self.assertEqual(cc_script, "")
        self.assertEqual(bcc_script, "")
        cc_script, _, _, _ = compose_tools._build_recipient_loops(
            "one@example.com", None, compact=True
        )
        self.assertEqual(
            cc_script,
            'make new cc recipient at end of cc recipients with properties '
            '{address:"one@example.com"}\n',
        )


if __name__ == "__main__":
    unittest.main()

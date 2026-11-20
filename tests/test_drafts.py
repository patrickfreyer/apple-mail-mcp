"""Tests for the id-based draft helpers (no Mail.app needed)."""

import unittest
from unittest.mock import patch

from apple_mail_mcp.tools import drafts


class QuoteTests(unittest.TestCase):
    def test_quote_prefixes_every_line(self):
        self.assertEqual(drafts.quote_original("a\r\n\r\nb\n"), "> a\n>\n> b")

    def test_reply_text_has_body_attribution_and_quote(self):
        text = drafts.build_reply_text(
            "Thanks.\n", "Ann <ann@example.com>", "2026-03-05T09:07:00", "Hi\nthere"
        )
        self.assertEqual(
            text,
            "Thanks.\n\nOn 5 Mar 2026 at 09:07, Ann <ann@example.com> wrote:\n\n"
            "> Hi\n> there\n",
        )

    def test_unparseable_date_is_kept(self):
        self.assertEqual(drafts.format_quote_date("yesterday"), "yesterday")

    def test_forward_text_carries_header_and_original(self):
        text = drafts.build_forward_text(
            "FYI", "a@example.com", "2026-03-05T09:07:00", "Plans", "b@example.com", "Body"
        )
        self.assertIn("Begin forwarded message:", text)
        self.assertIn("Subject: Plans", text)
        self.assertTrue(text.startswith("FYI\n\n"))
        self.assertTrue(text.endswith("Body\n"))


class ReplyThreadingTests(unittest.TestCase):
    ORIG = {
        "sender": "Ann <ann@example.com>",
        "reply_to": "",
        "to": "me@example.com, bob@example.com, ",
        "cc": "carol@example.com, ann@example.com, ",
        "own": "other@example.com, me@example.com, ",
    }

    def test_reply_goes_to_sender_from_the_address_written_to(self):
        to, cc, sender = drafts.reply_recipients(self.ORIG, reply_all=False)
        self.assertEqual(to, ["Ann <ann@example.com>"])
        self.assertEqual(cc, [])
        self.assertEqual(sender, "me@example.com")

    def test_reply_all_skips_self_and_duplicates(self):
        _, cc, _ = drafts.reply_recipients(self.ORIG, reply_all=True)
        self.assertEqual(cc, ["bob@example.com", "carol@example.com"])

    def test_reply_to_header_wins(self):
        orig = dict(self.ORIG, reply_to="list@example.com")
        self.assertEqual(drafts.reply_recipients(orig, False)[0], ["list@example.com"])

    def test_subject_prefix_not_doubled(self):
        self.assertEqual(drafts.prefixed_subject("Re:", "Plans"), "Re: Plans")
        self.assertEqual(drafts.prefixed_subject("Re:", "RE: Plans"), "RE: Plans")
        self.assertEqual(drafts.prefixed_subject("Fwd:", "Plans"), "Fwd: Plans")


class ScriptTests(unittest.TestCase):
    def test_lookup_is_by_id_not_subject(self):
        script = drafts.find_message_script(42, "Work", "INBOX")
        self.assertIn("whose id is 42", script)
        self.assertNotIn("subject", script)

    def test_parse_fields_keeps_separators_in_last_field(self):
        sep = drafts.SEP
        self.assertEqual(
            drafts.parse_fields(f"a{sep}b{sep}c{sep}d", 3), ["a", "b", f"c{sep}d"]
        )
        self.assertEqual(drafts.parse_fields("a", 3), ["a", "", ""])

    def test_background_reply_never_uses_reply_command_or_windows(self):
        orig = dict(ReplyThreadingTests.ORIG, subject="Plans", date="", content="x")
        with (
            patch.object(drafts, "_fetch_original", return_value=orig),
            patch.object(drafts, "run_mail", return_value="7") as run,
        ):
            drafts.create_reply_draft(42, "Thanks")
        script = run.call_args.args[0]
        self.assertNotIn("reply theMsg", script)
        self.assertNotIn("opening window", script)
        self.assertNotIn("activate", script)
        self.assertIn("visible:false", script)
        self.assertNotIn("send ", script)

    def test_open_for_review_uses_native_threaded_reply(self):
        orig = dict(ReplyThreadingTests.ORIG, subject="Plans", date="", content="x")
        with (
            patch.object(drafts, "_fetch_original", return_value=orig),
            patch.object(drafts, "run_mail", return_value="7") as run,
        ):
            out = drafts.create_reply_draft(42, "Thanks", open_for_review=True)
        self.assertIn("reply theMsg with opening window", run.call_args.args[0])
        self.assertIn("Threaded", out)


if __name__ == "__main__":
    unittest.main()

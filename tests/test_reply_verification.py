"""Tests for verify_reply_body_outside_quote (#71)."""

import unittest

from apple_mail_mcp.tools.reply_verification import verify_reply_body_outside_quote

_HEADERS = (
    "From: sender@example.com\r\n"
    "To: reply@example.com\r\n"
    "Subject: Re: Weekly sync\r\n"
    "MIME-Version: 1.0\r\n"
)

_ORIGINAL_HTML = (
    '<blockquote type="cite">'
    "<div>On Jan 1, 2026, sender wrote:</div>"
    "<div>Can we move the meeting?</div>"
    "</blockquote>"
)


def _multipart_source(new_body_html: str, new_body_text: str) -> str:
    """Build a multipart/alternative RFC 822 source, matching what Mail
    actually produces for an HTML reply (text/plain fallback + text/html)."""
    boundary = "----MailBoundary"
    return (
        _HEADERS
        + f'Content-Type: multipart/alternative; boundary="{boundary}"\r\n'
        + "\r\n"
        + f"--{boundary}\r\n"
        + "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        + new_body_text
        + "\r\n"
        + f"--{boundary}\r\n"
        + "Content-Type: text/html; charset=utf-8\r\n\r\n"
        + new_body_html
        + f"\r\n--{boundary}--\r\n"
    )


class VerifyReplyBodyOutsideQuoteTests(unittest.TestCase):
    def test_body_correctly_placed_above_the_quote_verifies(self):
        """The intended case: new content above the blockquote."""
        source = _multipart_source(
            new_body_html=f"<div>Yes, 3pm works.</div>{_ORIGINAL_HTML}",
            new_body_text="Yes, 3pm works.\n\nOn Jan 1, 2026, sender wrote:\n> Can we move the meeting?",
        )

        verified, detail = verify_reply_body_outside_quote(
            source, "Yes, 3pm works."
        )

        self.assertTrue(verified, detail)
        self.assertIn("outside", detail)

    def test_body_landed_inside_the_quote_is_caught(self):
        """The #71 bug: the paste ends up inside the blockquote, not above it.

        Before this module existed, `reply_to_email` reported success from
        text presence alone, which this case would have wrongly passed.
        """
        html_body = (
            '<blockquote type="cite">'
            "<div>Yes, 3pm works.</div>"
            "<div>On Jan 1, 2026, sender wrote:</div>"
            "<div>Can we move the meeting?</div>"
            "</blockquote>"
        )
        source = _multipart_source(
            new_body_html=html_body,
            new_body_text="> Yes, 3pm works.\n> On Jan 1, 2026, sender wrote:\n> Can we move the meeting?",
        )

        verified, detail = verify_reply_body_outside_quote(
            source, "Yes, 3pm works."
        )

        self.assertFalse(verified)
        self.assertIn("only inside the quoted original", detail)

    def test_body_missing_entirely_is_distinguished_from_quoted(self):
        """A failed paste (empty reply) must not be reported as 'inside the
        quote' -- that's a different, more specific failure than 'not
        found at all', and callers should be able to tell them apart."""
        source = _multipart_source(
            new_body_html=_ORIGINAL_HTML,
            new_body_text="On Jan 1, 2026, sender wrote:\n> Can we move the meeting?",
        )

        verified, detail = verify_reply_body_outside_quote(
            source, "Yes, 3pm works."
        )

        self.assertFalse(verified)
        self.assertIn("not found", detail)
        self.assertNotIn("only inside", detail)

    def test_reply_with_no_quote_block_at_all_still_verifies(self):
        """A reply to a message with no prior thread (or a compose, not a
        reply) has no blockquote to be inside of -- presence anywhere in
        the body is correctly sufficient."""
        source = _multipart_source(
            new_body_html="<div>Sounds good.</div>",
            new_body_text="Sounds good.",
        )

        verified, detail = verify_reply_body_outside_quote(source, "Sounds good.")

        self.assertTrue(verified, detail)

    def test_plain_text_only_message_uses_the_gt_marker_path(self):
        """No HTML part at all: falls back to '>'-line quote detection."""
        source = (
            _HEADERS
            + "Content-Type: text/plain; charset=utf-8\r\n\r\n"
            + "Yes, 3pm works.\n\n> Can we move the meeting?\n"
        )

        verified, detail = verify_reply_body_outside_quote(
            source, "Yes, 3pm works."
        )

        self.assertTrue(verified, detail)

    def test_plain_text_only_message_catches_body_inside_quote(self):
        source = (
            _HEADERS
            + "Content-Type: text/plain; charset=utf-8\r\n\r\n"
            + "> Yes, 3pm works.\n> Can we move the meeting?\n"
        )

        verified, detail = verify_reply_body_outside_quote(
            source, "Yes, 3pm works."
        )

        self.assertFalse(verified)
        self.assertIn("only inside the quoted original", detail)

    def test_html_wrapped_across_multiple_divs_still_matches(self):
        """Mail wraps each line in its own <div>; the tag-stripping
        normalization must not require an exact-string match against the
        raw HTML."""
        source = _multipart_source(
            new_body_html="<div>Yes,</div><div>3pm&nbsp;works.</div>" + _ORIGINAL_HTML,
            new_body_text="Yes,\n3pm works.",
        )

        verified, _ = verify_reply_body_outside_quote(source, "Yes, 3pm works.")

        self.assertTrue(verified)

    def test_plain_literal_markup_is_preserved_in_html_draft(self):
        source = _multipart_source(
            "<div>use &lt;b&gt; tag in R&amp;amp;D</div>" + _ORIGINAL_HTML,
            "use <b> tag in R&amp;D",
        )
        verified, detail = verify_reply_body_outside_quote(source, "use <b> tag in R&amp;D")
        self.assertTrue(verified, detail)

    def test_plain_body_line_wrapping_is_ignored(self):
        source = _HEADERS + "Content-Type: text/plain\r\n\r\nYes,\n  3pm\tworks.\n> original"
        verified, detail = verify_reply_body_outside_quote(source, "Yes, 3pm works.")
        self.assertTrue(verified, detail)

    def test_empty_reply_body_does_not_verify(self):
        source = _multipart_source(
            new_body_html=_ORIGINAL_HTML, new_body_text="quoted only"
        )

        verified, detail = verify_reply_body_outside_quote(source, "   ")

        self.assertFalse(verified)
        self.assertIn("empty", detail)

    def test_message_with_neither_html_nor_text_body_reports_that_plainly(self):
        source = (
            _HEADERS
            + "Content-Type: application/octet-stream\r\n\r\n"
            + "binary-ish-payload"
        )

        verified, detail = verify_reply_body_outside_quote(source, "Yes, 3pm works.")

        self.assertFalse(verified)
        self.assertIn("neither", detail)


if __name__ == "__main__":
    unittest.main()


class VerifyRecipientsTests(unittest.TestCase):
    """Tests for verify_recipients (#70)."""

    HEADERS = (
        "From: sender@example.com\r\n"
        "To: alice@example.com\r\n"
        "Cc: bob@example.com, carol@example.com\r\n"
        "Subject: Re: sync\r\n\r\n"
        "body\r\n"
    )

    def test_cc_entry_without_an_address_is_reported_not_dropped(self):
        """Seen on a real draft: "Name <>" was saved as `Cc: Name` and the
        check passed because the empty address was silently dropped."""
        source = (
            "From: Me <me@example.com>\r\nTo: a@example.com\r\nCc: Prueba Copia\r\n"
            "Subject: Re: t\r\nContent-Type: text/plain\r\n\r\nhola\r\n"
        )
        from apple_mail_mcp.tools.reply_verification import verify_recipients

        verified, detail = verify_recipients(source, expected_cc="Prueba Copia <>")
        self.assertFalse(verified)
        self.assertIn("has no valid address", detail)

    def test_cc_display_names_and_case_are_normalized(self):
        from apple_mail_mcp.tools.reply_verification import verify_recipients

        verified, detail = verify_recipients(
            self.HEADERS.replace("bob@example.com", "Bob@Example.COM"),
            expected_cc='"Example, Bob" <BOB@example.com>, Carol <CAROL@example.com>',
        )
        self.assertTrue(verified, detail)

    def test_from_display_name_and_case_are_normalized(self):
        from apple_mail_mcp.tools.reply_verification import verify_recipients

        verified, detail = verify_recipients(
            self.HEADERS.replace("sender@example.com", "Sender@Example.COM"),
            expected_from="Sender <SENDER@example.com>",
        )
        self.assertTrue(verified, detail)

    def test_no_expectations_always_verifies(self):
        from apple_mail_mcp.tools.reply_verification import verify_recipients

        verified, detail = verify_recipients(self.HEADERS)

        self.assertTrue(verified)
        self.assertIn("alice@example.com", detail)
        self.assertIn("bob@example.com", detail)
        self.assertIn("sender@example.com", detail)

    def test_requested_cc_present_verifies(self):
        from apple_mail_mcp.tools.reply_verification import verify_recipients

        verified, _ = verify_recipients(self.HEADERS, expected_cc="bob@example.com")

        self.assertTrue(verified)

    def test_requested_cc_missing_from_saved_draft_is_caught(self):
        """The exact scenario #70 flags: a CC the caller asked for that
        didn't actually make it into the saved draft."""
        from apple_mail_mcp.tools.reply_verification import verify_recipients

        verified, detail = verify_recipients(
            self.HEADERS, expected_cc="dave@example.com"
        )

        self.assertFalse(verified)
        self.assertIn("dave@example.com", detail)
        self.assertIn("not found in saved Cc", detail)

    def test_extra_cc_mail_added_itself_is_not_a_mismatch(self):
        """Reply-to-all can add CC recipients the caller never requested.
        Those are not a verification failure -- only a *missing* requested
        address is."""
        from apple_mail_mcp.tools.reply_verification import verify_recipients

        verified, _ = verify_recipients(self.HEADERS, expected_cc="bob@example.com")

        self.assertTrue(verified)  # carol@example.com is present but unrequested

    def test_multiple_requested_cc_addresses_all_checked(self):
        from apple_mail_mcp.tools.reply_verification import verify_recipients

        verified, detail = verify_recipients(
            self.HEADERS, expected_cc="bob@example.com, dave@example.com"
        )

        self.assertFalse(verified)
        # Only dave -- the one actually missing -- should be listed as the
        # *requested-but-missing* CC; bob was requested and present, so he
        # must not appear in that specific list (he legitimately still
        # shows up in the "saved Cc" echo of the full actual Cc header).
        missing_list = detail.split("requested CC ", 1)[1].split(" not found", 1)[0]
        self.assertIn("dave@example.com", missing_list)
        self.assertNotIn("bob@example.com", missing_list)

    def test_requested_from_matching_actual_verifies(self):
        from apple_mail_mcp.tools.reply_verification import verify_recipients

        verified, _ = verify_recipients(
            self.HEADERS, expected_from="sender@example.com"
        )

        self.assertTrue(verified)

    def test_requested_from_not_matching_actual_is_caught(self):
        """A sender override (`from_address`) that Mail silently ignored --
        e.g. because it wasn't a configured alias for the account -- must
        be reported, not assumed to have taken effect."""
        from apple_mail_mcp.tools.reply_verification import verify_recipients

        verified, detail = verify_recipients(
            self.HEADERS, expected_from="other@example.com"
        )

        self.assertFalse(verified)
        self.assertIn("other@example.com", detail)
        self.assertIn("not found in saved From", detail)

    def test_no_cc_header_at_all_with_no_expectation_verifies(self):
        from apple_mail_mcp.tools.reply_verification import verify_recipients

        source = (
            "From: sender@example.com\r\nTo: alice@example.com\r\n"
            "Subject: Re: sync\r\n\r\nbody\r\n"
        )

        verified, detail = verify_recipients(source)

        self.assertTrue(verified)
        self.assertIn("Cc=[]", detail)

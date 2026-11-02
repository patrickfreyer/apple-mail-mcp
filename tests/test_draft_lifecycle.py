"""Draft updates must fail safely before the original can be retired."""

import copy
import json
import unittest
from email.message import EmailMessage
from unittest.mock import patch

from apple_mail_mcp import server
from apple_mail_mcp.tools import compose, drafts


def draft(message_id="10", body="Original body", attachment=None, html=None):
    message = EmailMessage()
    message["Subject"] = "Review note"
    message["From"] = "sender@example.invalid"
    message["To"] = "reader@example.invalid"
    message["Cc"] = "copy@example.invalid"
    message["Message-ID"] = f"<{message_id}@example.invalid>"
    message.set_content(body)
    if html is not None:
        message.add_alternative(html, subtype="html")
    if attachment is not None:
        message.add_attachment(attachment, maintype="application", subtype="octet-stream", filename="evidence.bin")
    return dict(message_id=message_id, internet_message_id=f"{message_id}@example.invalid",
                subject="Review note", sender="sender@example.invalid", mailbox="Drafts",
                to=["reader@example.invalid"], cc=["copy@example.invalid"], bcc=[],
                attachments=["evidence.bin"] if attachment is not None else [],
                body=body, raw_source=message.as_string())


class DraftSelectionTests(unittest.TestCase):
    def test_subject_ambiguity_does_not_pick_first_draft(self):
        with self.assertRaisesRegex(drafts.DraftError, "Ambiguous"):
            drafts._select([draft("10"), draft("11")], draft_subject="Review")

    def test_exact_id_can_disambiguate_identical_subjects(self):
        found = drafts._select([draft("10"), draft("11")], message_id="11")
        self.assertEqual(found["message_id"], "11")

    def test_internet_id_is_an_exact_match(self):
        found = drafts._select([draft("10"), draft("11")], internet_message_id="<11@example.invalid>")
        self.assertEqual(found["message_id"], "11")

    def test_invalid_identifiers_cannot_reach_mail(self):
        for value in ("12 or true", "１２", "-1", "1.0", ""):
            with self.subTest(value=value), patch.object(drafts, "_query") as query:
                result = compose.manage_drafts("Work", "delete", message_id=value)
                self.assertTrue(result.startswith("Error:"))
                query.assert_not_called()

    def test_read_only_blocks_delivery_before_lookup(self):
        with patch.object(server, "READ_ONLY", True), patch.object(drafts, "_query") as query:
            result = compose.manage_drafts("Work", "send", message_id="10")
        self.assertEqual(result, "Error: Sending drafts is disabled in read-only mode.")
        query.assert_not_called()

    def test_read_never_opens_a_window_and_reports_truncation(self):
        original = draft(body="A body longer than its preview")
        with patch.object(drafts, "_query", side_effect=[[original], [copy.deepcopy(original)]]), patch.object(drafts, "run_applescript") as run:
            result = json.loads(compose.manage_drafts("Work", "read", message_id="10", max_chars=6, output_format="json"))
        self.assertEqual(result["draft"]["body"], "A body")
        self.assertTrue(result["draft"]["body_truncated"])
        self.assertNotIn("raw_source", result["draft"])
        run.assert_not_called()


class DraftReplacementTests(unittest.TestCase):
    def test_original_is_retired_only_after_saved_replacement_is_verified(self):
        original, replacement = draft(), draft("11", "Updated body")
        order = []
        with (
            patch.object(drafts, "_save_replacement", side_effect=lambda *a: order.append("save") or dict(message_ids=["11"], outgoing_id="99")),
            patch.object(drafts, "_query", side_effect=lambda *a, **k: order.append("read") or [replacement]),
            patch.object(drafts, "_retire", side_effect=lambda *a, **k: order.append("retire")) as retire,
        ):
            result = drafts._replace("Work", original, body="Updated body")
        self.assertEqual(order, ["save", "read", "retire"])
        self.assertTrue(result["verified"])
        self.assertEqual(result["draft"]["message_id"], "11")
        self.assertEqual(retire.call_args.kwargs["expected_source"], original["raw_source"])

    def test_failed_body_verification_keeps_original(self):
        with (
            patch.object(drafts, "_save_replacement", return_value=dict(message_ids=["11"], outgoing_id="99")),
            patch.object(drafts, "_query", return_value=[draft("11", "Wrong body")]),
            patch.object(drafts, "_retire") as retire,
        ):
            with self.assertRaisesRegex(drafts.DraftError, "Replacement message_id=11"):
                drafts._replace("Work", draft(), body="Updated body")
        retire.assert_not_called()

    def test_attachment_bytes_are_preserved_and_checked(self):
        original = draft(attachment=b"original attachment")
        wrong = draft("11", "Updated body", attachment=b"different bytes")
        with (
            patch.object(drafts, "_save_replacement", return_value=dict(message_ids=["11"], outgoing_id="99")) as save,
            patch.object(drafts, "_query", return_value=[wrong]),
            patch.object(drafts, "_retire") as retire,
        ):
            with self.assertRaisesRegex(drafts.DraftError, "attachment contents differ"):
                drafts._replace("Work", original, body="Updated body")
        self.assertEqual(save.call_args.args[1]["attachment_data"], [("evidence.bin", b"original attachment")])
        retire.assert_not_called()

    def test_recipient_mismatch_keeps_original(self):
        wrong = draft("11", "Updated body")
        wrong["bcc"] = ["unexpected@example.invalid"]
        with (
            patch.object(drafts, "_save_replacement", return_value=dict(message_ids=["11"], outgoing_id="99")),
            patch.object(drafts, "_query", return_value=[wrong]),
            patch.object(drafts, "_retire") as retire,
        ):
            with self.assertRaisesRegex(drafts.DraftError, "bcc recipients differ"):
                drafts._replace("Work", draft(), body="Updated body")
        retire.assert_not_called()

    def test_ambiguous_saved_identity_keeps_original(self):
        with patch.object(drafts, "_save_replacement", return_value=dict(message_ids=["11", "12"], outgoing_id="99")), patch.object(drafts, "_retire") as retire:
            with self.assertRaisesRegex(drafts.DraftError, "ambiguous"):
                drafts._replace("Work", draft(), body="Updated body")
        retire.assert_not_called()

    def test_thread_headers_are_not_silently_lost(self):
        original = draft()
        original["raw_source"] = "In-Reply-To: <parent@example.invalid>\n" + original["raw_source"]
        with patch.object(drafts, "_save_replacement") as save:
            with self.assertRaisesRegex(drafts.DraftError, "reply headers"):
                drafts._replace("Work", original, body="Updated body")
        save.assert_not_called()

    def test_html_loss_is_not_silently_accepted(self):
        original = draft(html='<p style="color: red">Original body</p>')
        with (
            patch.object(drafts, "_save_replacement", return_value=dict(message_ids=["11"], outgoing_id="99")),
            patch.object(drafts, "_query", return_value=[draft("11")]),
            patch.object(drafts, "_retire") as retire,
        ):
            with self.assertRaisesRegex(drafts.DraftError, "HTML formatting"):
                drafts._replace("Work", original, subject="Review note")
        retire.assert_not_called()

    def test_edit_requests_a_real_outgoing_composer(self):
        with patch.object(drafts, "_run_json", return_value={}) as run:
            item = draft()
            expected = dict(item, old_subject=item["subject"], body_html=None)
            drafts._save_replacement("Work", expected, [], True)
        script = run.call_args.args[0]
        self.assertIn("set newDraft to make new outgoing message", script)
        self.assertIn("set visible of newDraft to true", script)
        self.assertNotIn("open targetDraft", script)
        self.assertNotIn("close window 1", script)
        self.assertNotIn("send newDraft", script)

    def test_failed_source_guard_leaves_both_versions(self):
        with (
            patch.object(drafts, "_save_replacement", return_value=dict(message_ids=["11"], outgoing_id="99")),
            patch.object(drafts, "_query", return_value=[draft("11", "Updated body")]),
            patch.object(drafts, "_retire", side_effect=drafts.DraftError("Original draft changed")),
        ):
            with self.assertRaisesRegex(drafts.DraftError, "Original draft changed"):
                drafts._replace("Work", draft(), body="Updated body")


class DraftReviewTests(unittest.TestCase):
    def test_plain_compose_saves_only_its_own_message(self):
        with patch.object(compose, "run_applescript", return_value="saved") as run:
            compose.compose_email("Work", "reader@example.invalid", "Review", "Body", mode="draft")
        script = run.call_args.args[0]
        self.assertIn("close newMessage saving yes", script)
        self.assertNotIn("close window 1", script)

    def test_open_reports_a_viewer_not_an_editor(self):
        with patch.object(drafts, "_query", return_value=[draft()]), patch.object(drafts, "run_applescript", return_value="accepted"):
            result = json.loads(compose.manage_drafts("Work", "open", message_id="10", output_format="json"))
        self.assertEqual(result["status"], "viewer_opened")
        self.assertIn("not an editable composer", result["note"])

    def test_sent_verification_reports_leftovers_without_deleting(self):
        with patch.object(drafts, "_query", side_effect=[[draft()], [draft("11")]]), patch.object(drafts, "_retire") as retire:
            result = json.loads(compose.manage_drafts("Work", "verify_sent", internet_message_id="10@example.invalid", output_format="json"))
        self.assertEqual(result["status"], "sent_verified")
        self.assertEqual(result["remaining_draft_ids"], ["11"])
        retire.assert_not_called()

    def test_ambiguous_subject_cannot_send_or_delete(self):
        for action in ("send", "delete"):
            with self.subTest(action=action), patch.object(drafts, "_query", return_value=[draft(), draft("11")]), patch.object(drafts, "run_applescript") as run:
                result = compose.manage_drafts("Work", action, draft_subject="Review")
                self.assertIn("Ambiguous", result)
                run.assert_not_called()

    def test_send_request_is_not_reported_as_verified_delivery(self):
        with patch.object(drafts, "_query", return_value=[draft()]), patch.object(drafts, "run_applescript", return_value="accepted"):
            result = json.loads(compose.manage_drafts("Work", "send", message_id="10", output_format="json"))
        self.assertEqual(result["status"], "send_requested")
        self.assertIn("not yet verified", result["note"])

    def test_rejected_send_is_not_reported_as_success(self):
        with patch.object(drafts, "_query", return_value=[draft()]), patch.object(drafts, "run_applescript", return_value="Error: Mail did not accept the send request"):
            result = compose.manage_drafts("Work", "send", message_id="10")
        self.assertTrue(result.startswith("Error:"))

    def test_plain_compose_legacy_creation_rejects_html_instead_of_ignoring_it(self):
        with patch.object(compose, "run_applescript") as run:
            result = compose.manage_drafts("Work", "create", subject="A", to="a@example.invalid", body="A", body_html="<b>A</b>")
        self.assertIn("plain text", result)
        run.assert_not_called()


class MimePreservationTests(unittest.TestCase):
    def test_empty_plain_alternative_reads_visible_html_text(self):
        item = draft(body="", html="<p>Actual body</p>")
        self.assertEqual(drafts._norm(drafts._parts(item["raw_source"])[1]), "Actual body")

    def test_share_scaffolding_is_unwrapped_but_authored_quote_is_retained(self):
        authored = '<p><strong>New text</strong></p><blockquote type="cite">User quote</blockquote>'
        stored = '<html><head></head><body><div class="Apple-Mail-URLShareUserContentTopClass"><br></div><div class="Apple-Mail-URLShareWrapperClass"><blockquote type="cite">' + authored + '</blockquote></div></body></html>'
        self.assertEqual(drafts._mail_fragment(stored), authored)

    def test_unbalanced_html_is_refused(self):
        with self.assertRaisesRegex(drafts.DraftError, "Unbalanced"):
            drafts._mail_fragment("<div><strong>unfinished</div>")

    def test_document_styles_are_not_silently_dropped(self):
        with self.assertRaisesRegex(drafts.DraftError, "styling"):
            drafts._mail_fragment('<html><head><style>p {color:red}</style></head><body><p>Body</p></body></html>')

    def test_source_guard_precedes_original_deletion(self):
        with patch.object(drafts, "run_applescript", return_value="deleted") as run:
            drafts._retire("Work", draft(), expected_source="Original Case\r\n")
        script = run.call_args.args[0]
        self.assertIn("considering case", script)
        self.assertLess(script.index("Original draft changed"), script.index("delete targetDraft"))

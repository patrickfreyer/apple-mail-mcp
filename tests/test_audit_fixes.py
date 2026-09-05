"""Regression tests for the 25.08.2026 audit fixes.

Every test here corresponds to a defect that was measured against a live
Mail.app before the fix, not to a theoretical concern.
"""

import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apple_mail_mcp.tools import compose as compose_tools
from apple_mail_mcp.tools import inbox as inbox_tools
from apple_mail_mcp.tools import manage as manage_tools
from apple_mail_mcp.tools import search as search_tools


def _capture(fn, *args, applescript_returns=None, **kwargs):
    """Run *fn* with run_applescript stubbed, returning (result, scripts)."""
    scripts = []
    answers = list(applescript_returns or [])

    def _run(script, timeout=120):
        scripts.append(script)
        return answers.pop(0) if answers else ""

    with patch(
        "apple_mail_mcp.tools.compose.run_applescript", side_effect=_run
    ), patch(
        "apple_mail_mcp.tools.inbox.run_applescript", side_effect=_run
    ), patch(
        "apple_mail_mcp.tools.manage.run_applescript", side_effect=_run
    ), patch(
        "apple_mail_mcp.tools.search.run_applescript", side_effect=_run
    ), patch(
        # The draft-location lookup waits for Mail to write the draft; with a
        # stub there is nothing to wait for.
        "apple_mail_mcp.tools.compose.time.sleep"
    ):
        result = fn(*args, **kwargs)
    return result, scripts


class CloseTargetTests(unittest.TestCase):
    """A draft must save its own message, never Mail's frontmost window.

    Measured before the fix: compose_email(mode="draft") issued
    `close window 1 saving yes`. The message was created with visible:false and
    owns no window, so window 1 was the user's own open message — it got closed
    and saved as a draft, while the attachment of the intended draft was lost.
    """

    def test_compose_draft_closes_its_own_message(self):
        _, scripts = _capture(
            compose_tools.compose_email,
            account="Work",
            to="a@example.com",
            subject="Subject",
            body="Body",
            mode="draft",
        )
        script = next(s for s in scripts if "make new outgoing message" in s)
        self.assertIn("close newMessage saving yes", script)
        self.assertNotIn("close window 1", script)

    def test_manage_drafts_create_closes_its_own_message(self):
        _, scripts = _capture(
            compose_tools.manage_drafts,
            account="Work",
            action="create",
            subject="Subject",
            to="a@example.com",
            body="Body",
        )
        script = next(s for s in scripts if "make new outgoing message" in s)
        self.assertIn("close newDraft saving yes", script)
        self.assertNotIn("close window 1", script)

    def test_no_close_window_1_left_anywhere(self):
        import inspect

        source = inspect.getsource(compose_tools)
        code_lines = [
            line for line in source.splitlines()
            if "close window 1" in line and not line.strip().startswith("#")
        ]
        self.assertEqual(code_lines, [])


class AccountNameWithPipeTests(unittest.TestCase):
    """Account names may contain "|".

    Robin's account is literally named "Robin Herbeck | Full Stack Developer".
    The old delimiter split it into two unusable fragments, and every follow-up
    call with such a fragment failed with "account not found".
    """

    NAME = "Robin Herbeck | Full Stack Developer"

    def test_list_accounts_keeps_pipe_in_name(self):
        result, _ = _capture(
            inbox_tools.list_accounts,
            applescript_returns=["legacy\n" + self.NAME + "\nGoogle"],
        )
        self.assertEqual(result, ["legacy", self.NAME, "Google"])

    def test_list_account_addresses_keeps_pipe_in_name(self):
        result, _ = _capture(
            inbox_tools.list_account_addresses,
            applescript_returns=[self.NAME + "|||info@robinherbeck.com"],
        )
        self.assertEqual(result, {self.NAME: ["info@robinherbeck.com"]})

    def test_unread_summary_keeps_pipe_in_name(self):
        result, _ = _capture(
            inbox_tools.get_mailbox_unread_counts,
            summary_only=True,
            applescript_returns=["legacy:0\n" + self.NAME + ":7"],
        )
        self.assertEqual(result, {"legacy": 0, self.NAME: 7})


class TrashLoopTests(unittest.TestCase):
    """Deleting inside a forward loop over the same list skips messages.

    Reproduced with the identical pattern against Mail: after the first delete
    the list shifts and reading the next index fails with -1728.
    """

    def test_empty_trash_iterates_backwards(self):
        _, scripts = _capture(
            manage_tools.manage_trash,
            account="Work",
            action="empty_trash",
            confirm_empty=True,
        )
        script = scripts[0]
        self.assertIn("repeat with msgIndex from messageCount to 1 by -1", script)
        self.assertNotIn("repeat with aMessage in trashMessages", script)

    def test_delete_permanent_reports_measured_count(self):
        # The old version counted delete calls. Mail's `delete` is a no-op on a
        # message already in Trash, so it reported deletions that never
        # happened. The count now comes from the mailbox itself.
        _, scripts = _capture(
            manage_tools.manage_trash,
            account="Work",
            action="delete_permanent",
            subject_keyword="x",
            dry_run=False,
        )
        script = scripts[0]
        self.assertIn("set trashBefore to count of messages of trashMailbox", script)
        self.assertIn("set trashAfter to count of messages of trashMailbox", script)
        self.assertIn("ACTUALLY REMOVED", script)


class QuotedReplyTests(unittest.TestCase):
    """The plain-text reply carries the quote we build ourselves."""

    def test_quote_has_header_and_markers(self):
        body = compose_tools._build_quoted_reply(
            "Hallo Robin.",
            "A <a@example.com>",
            "25.08.2026",
            "Zeile eins\r\n\r\nZeile zwei",
        )
        self.assertTrue(body.startswith("Hallo Robin."))
        self.assertIn("Am 25.08.2026 schrieb A <a@example.com>:", body)
        self.assertIn("> Zeile eins", body)
        self.assertIn("> Zeile zwei", body)

    def test_quote_drops_zero_width_padding(self):
        padded = "Text" + "‌" * 50 + "￼"
        body = compose_tools._build_quoted_reply("Hi", "a@b.c", "heute", padded)
        self.assertNotIn("‌", body)
        self.assertNotIn("￼", body)

    def test_quote_is_truncated_with_a_marker(self):
        body = compose_tools._build_quoted_reply(
            "Hi", "a@b.c", "heute", "x" * 500, limit=100
        )
        self.assertIn("> [...]", body)

    def test_no_original_means_no_quote_block(self):
        body = compose_tools._build_quoted_reply("Nur Text", "a@b.c", "heute", "")
        self.assertEqual(body, "Nur Text\n\n")


class ReplyPathTests(unittest.TestCase):
    """Plain replies must not depend on keyboard focus.

    Measured before the fix: the reply draft carried correct
    In-Reply-To/References headers and an empty body, because the blind Cmd+V
    landed in another app.
    """

    def _run_reply(self, **kwargs):
        scripts = []

        def _run(script, timeout=120):
            scripts.append(script)
            match = re.search(r"<<<AMMCP-[0-9a-f]+>>>", script)
            if match and "reply foundMessage" not in script:
                sep = match.group(0)
                return sep.join(
                    ["99", "Thread", "them@example.com", "heute", "1", "Original"]
                )
            if "reply foundMessage" in script:
                sep = re.search(r"<<<AMMCP-[0-9a-f]+>>>", script).group(0)
                return "Reply saved as draft!" + sep + "Re: Thread"
            return ""

        with patch(
            "apple_mail_mcp.tools.compose.run_applescript", side_effect=_run
        ), patch("apple_mail_mcp.tools.compose.time.sleep"):
            result = compose_tools.reply_to_email(
                account="Work",
                subject_keyword="Thread",
                reply_body="Antwort",
                mode="draft",
                **kwargs,
            )
        return result, scripts

    def test_plain_reply_uses_no_keystrokes(self):
        _, scripts = self._run_reply()
        joined = "\n".join(scripts)
        self.assertNotIn("keystroke", joined)
        self.assertNotIn("System Events", joined)

    def test_plain_reply_saves_the_message_not_a_window(self):
        _, scripts = self._run_reply()
        script = next(s for s in scripts if "reply foundMessage" in s)
        self.assertIn("save replyMessage", script)
        self.assertNotIn("close window 1", script)

    def test_reply_searches_the_requested_mailbox(self):
        _, scripts = self._run_reply(mailbox="Archive")
        lookup = next(s for s in scripts if "matchingMessages" in s)
        self.assertIn('mailbox "Archive"', lookup)

    def test_reply_sets_body_before_attaching(self):
        # The attachment must live under the home directory; the repo does not.
        with tempfile.NamedTemporaryFile(
            dir=Path.home(), suffix=".txt", delete=False
        ) as handle:
            handle.write(b"x")
            attachment_path = handle.name
        try:
            _, scripts = self._run_reply(attachments=attachment_path)
        finally:
            os.unlink(attachment_path)
        script = next(s for s in scripts if "reply foundMessage" in s)
        self.assertLess(
            script.index("set content of replyMessage"),
            script.index("make new attachment"),
            "content must be set first, it replaces the whole body",
        )


class ForwardModeTests(unittest.TestCase):
    """forward_email had no non-sending mode and was dropped in read-only."""

    def test_draft_mode_saves_instead_of_sending(self):
        _, scripts = _capture(
            compose_tools.forward_email,
            account="Work",
            subject_keyword="x",
            to="a@example.com",
            mode="draft",
        )
        script = scripts[0]
        self.assertIn("save forwardMessage", script)
        self.assertNotIn("send forwardMessage", script)

    def test_send_mode_still_sends(self):
        _, scripts = _capture(
            compose_tools.forward_email,
            account="Work",
            subject_keyword="x",
            to="a@example.com",
        )
        self.assertIn("send forwardMessage", scripts[0])

    def test_read_only_blocks_send_but_allows_draft(self):
        from apple_mail_mcp import server

        original = server.READ_ONLY
        server.READ_ONLY = True
        try:
            blocked, _ = _capture(
                compose_tools.forward_email,
                account="Work",
                subject_keyword="x",
                to="a@example.com",
            )
            self.assertIn("read-only", blocked)
            allowed, scripts = _capture(
                compose_tools.forward_email,
                account="Work",
                subject_keyword="x",
                to="a@example.com",
                mode="draft",
            )
            self.assertNotIn("read-only", allowed)
            self.assertIn("save forwardMessage", scripts[0])
        finally:
            server.READ_ONLY = original


class BlindTypingGuardTests(unittest.TestCase):
    """The GUI paths must abort instead of typing into a foreign app.

    ``compose_email`` no longer has a GUI path at all — it hands the markup
    to Mail through ``set html content``. The guard that mattered there is
    now the absence of any keystroke, which is what this asserts. Reply and
    forward still paste (they must keep Mail's quoted original) and keep
    their focus guards, covered in test_compose_tools.py.
    """

    def _compose_html_script(self):
        scripts = []

        def fake_run(script, timeout=120):
            scripts.append(script)
            if "make new outgoing message" in script:
                return "Email saved as draft (HTML)"
            return ""

        with patch(
            "apple_mail_mcp.tools.compose.run_applescript", side_effect=fake_run
        ), patch("apple_mail_mcp.tools.compose.time.sleep"):
            compose_tools.compose_email(
                account="Work",
                to="a@example.com",
                subject="s",
                body="b",
                body_html="<p>b</p>",
                mode="draft",
            )
        for script in scripts:
            if "make new outgoing message" in script:
                return script
        raise AssertionError("no compose script was rendered")

    def test_html_compose_never_types(self):
        script = self._compose_html_script()
        self.assertNotIn("keystroke", script)
        self.assertNotIn("key code", script)
        self.assertNotIn("System Events", script)
        self.assertNotIn("frontmost", script)

    def test_html_compose_sets_html_content_directly(self):
        script = self._compose_html_script()
        self.assertIn("set html content of newMsg to htmlBody", script)


class DraftUpdateTests(unittest.TestCase):
    """Editing a draft: rebuild, verify, only then delete the old one."""

    def _fields(self, **overrides):
        fields = {
            "id": "42",
            "account": "Work",
            "subject": "Alt",
            "to": ["a@example.com"],
            "cc": [],
            "bcc": [],
            "attachments": ["file.pdf"],
            "sender": "me@example.com",
            "content": "Alter Text",
        }
        fields.update(overrides)
        return fields

    def test_unknown_attachment_pattern_leaves_draft_untouched(self):
        with patch.object(
            compose_tools, "_read_draft", return_value=(self._fields(), None)
        ), patch.object(compose_tools, "run_applescript") as mock_run:
            result = compose_tools._update_draft(
                account="Work",
                draft_subject="Alt",
                remove_attachments="doesnotexist",
            )
        self.assertIn("no attachment matches", result)
        self.assertIn("Draft left untouched", result)
        mock_run.assert_not_called()

    def test_failed_extraction_aborts_before_rebuilding(self):
        with patch.object(
            compose_tools, "_read_draft", return_value=(self._fields(), None)
        ), patch.object(
            compose_tools,
            "_export_draft_attachments",
            return_value=([], "Error: could not extract these existing attachments"),
        ), patch.object(compose_tools, "run_applescript") as mock_run:
            result = compose_tools._update_draft(account="Work", draft_subject="Alt")
        self.assertIn("could not extract", result)
        mock_run.assert_not_called()

    def test_old_draft_survives_when_replacement_never_appears(self):
        with patch.object(
            compose_tools, "_read_draft", return_value=(self._fields(), None)
        ), patch.object(
            compose_tools, "_export_draft_attachments", return_value=([], None)
        ), patch.object(
            compose_tools, "run_applescript", return_value="ok"
        ), patch.object(
            compose_tools, "_draft_id_for_subject", return_value=None
        ), patch.object(
            compose_tools, "_delete_draft_by_id"
        ) as mock_delete, patch.object(
            compose_tools.time, "sleep"
        ):
            result = compose_tools._update_draft(account="Work", draft_subject="Alt")
        self.assertIn("left untouched", result)
        mock_delete.assert_not_called()

    def test_reused_body_suppresses_the_second_signature(self):
        scripts = []

        def _run(script, timeout=120):
            scripts.append(script)
            return "ok"

        with patch.object(
            compose_tools, "_read_draft", return_value=(self._fields(), None)
        ), patch.object(
            compose_tools, "_export_draft_attachments", return_value=([], None)
        ), patch.object(
            compose_tools, "run_applescript", side_effect=_run
        ), patch.object(
            compose_tools, "_draft_id_for_subject", return_value="43"
        ), patch.object(
            compose_tools, "_delete_draft_by_id", return_value=True
        ), patch.object(
            compose_tools, "_draft_location_note", return_value=""
        ):
            compose_tools._update_draft(account="Work", draft_subject="Alt")
        build = next(s for s in scripts if "make new outgoing message" in s)
        self.assertIn("set message signature of newDraft to missing value", build)

    def test_new_body_keeps_the_signature(self):
        scripts = []

        def _run(script, timeout=120):
            scripts.append(script)
            return "ok"

        with patch.object(
            compose_tools, "_read_draft", return_value=(self._fields(), None)
        ), patch.object(
            compose_tools, "_export_draft_attachments", return_value=([], None)
        ), patch.object(
            compose_tools, "run_applescript", side_effect=_run
        ), patch.object(
            compose_tools, "_draft_id_for_subject", return_value="43"
        ), patch.object(
            compose_tools, "_delete_draft_by_id", return_value=True
        ), patch.object(
            compose_tools, "_draft_location_note", return_value=""
        ):
            compose_tools._update_draft(
                account="Work", draft_subject="Alt", body="Ganz neuer Text"
            )
        build = next(s for s in scripts if "make new outgoing message" in s)
        self.assertNotIn("set message signature", build)


if __name__ == "__main__":
    unittest.main()


class RichDraftAttachmentTests(unittest.TestCase):
    """create_rich_email_draft could not carry a file at all.

    The generated message is not a scriptable compose object, so nothing can
    be attached after opening it — the file has to be inside the `.eml`.
    """

    def _build(self, tmpdir, **kwargs):
        out = Path(tmpdir) / "draft.eml"
        with patch("apple_mail_mcp.tools.compose.run_applescript", return_value=""):
            result = compose_tools.create_rich_email_draft(
                account="Work",
                subject="Betreff",
                to="a@example.com",
                html_body="<p>Hallo</p>",
                output_path=str(out),
                open_in_mail=False,
                **kwargs,
            )
        return result, out.read_bytes().decode("utf-8", "replace")

    def test_attachment_is_embedded_in_the_eml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            attachment = Path.home() / "mcp-test-attachment.txt"
            attachment.write_text("Inhalt")
            try:
                result, raw = self._build(tmpdir, attachments=str(attachment))
            finally:
                attachment.unlink()
        self.assertIn("multipart/mixed", raw)
        self.assertIn("mcp-test-attachment.txt", raw)
        self.assertIn("Attachments embedded: mcp-test-attachment.txt", result)

    def test_missing_file_is_refused_before_writing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "draft.eml"
            with patch(
                "apple_mail_mcp.tools.compose.run_applescript", return_value=""
            ):
                result = compose_tools.create_rich_email_draft(
                    account="Work",
                    subject="Betreff",
                    to="a@example.com",
                    text_body="Hallo",
                    output_path=str(out),
                    open_in_mail=False,
                    attachments=str(Path.home() / "does-not-exist-xyz.pdf"),
                )
            self.assertIn("does not exist", result)
            self.assertFalse(out.exists(), "nothing may be written on a bad path")


class DraftAmbiguityTests(unittest.TestCase):
    """Sending or deleting the wrong draft cannot be undone."""

    def test_send_refuses_before_sending_when_several_match(self):
        _, scripts = _capture(
            compose_tools.manage_drafts,
            account="Work",
            action="send",
            draft_subject="Update",
        )
        script = scripts[0]
        self.assertIn("Refusing to guess which one to send", script)
        self.assertLess(
            script.index("Refusing to guess which one to send"),
            script.index("send foundDraft"),
            "the refusal must be evaluated before the send",
        )

    def test_delete_refuses_before_deleting_when_several_match(self):
        _, scripts = _capture(
            compose_tools.manage_drafts,
            account="Work",
            action="delete",
            draft_subject="Update",
        )
        script = scripts[0]
        self.assertIn("Refusing to guess which one to delete", script)
        self.assertLess(
            script.index("Refusing to guess which one to delete"),
            script.index("delete foundDraft"),
            "the refusal must be evaluated before the delete",
        )

    def test_open_takes_the_newest_and_says_so(self):
        _, scripts = _capture(
            compose_tools.manage_drafts,
            account="Work",
            action="open",
            draft_subject="Update",
        )
        script = scripts[0]
        self.assertIn("drafts matched, opened the newest one", script)


class NewestMatchTests(unittest.TestCase):
    """Subject keywords are ambiguous; the newest match is the intended one."""

    def test_forward_picks_the_newest_match(self):
        _, scripts = _capture(
            compose_tools.forward_email,
            account="Work",
            subject_keyword="Thread",
            to="a@example.com",
            mode="draft",
        )
        script = scripts[0]
        self.assertIn("whose subject contains", script)
        self.assertIn("date received of candidate) > newestDate", script)
        self.assertIn("forwarded the newest one", script)

    def test_attachment_lookup_lists_what_is_actually_there(self):
        _, scripts = _capture(
            manage_tools.save_email_attachment,
            account="Work",
            subject_keyword="Invoice",
            attachment_name="pdf",
            save_path=str(Path.home() / "invoice.pdf"),
            mailbox="Archive",
        )
        script = scripts[0]
        self.assertIn('mailbox "Archive"', script)
        self.assertIn("Attachments on that message:", script)


class ThreadLinkageTests(unittest.TestCase):
    """Threads are grouped by Message-ID, not by a shared subject."""

    def test_prefixes_are_stripped_repeatedly(self):
        self.assertEqual(
            search_tools._strip_thread_prefixes("Re: AW: Fwd: Angebot"), "Angebot"
        )
        self.assertEqual(search_tools._strip_thread_prefixes("Angebot"), "Angebot")

    def test_references_are_extracted_from_headers(self):
        headers = (
            "From: a@example.com\n"
            "In-Reply-To: <one@example.com>\n"
            "References: <one@example.com>\n <two@example.com>\n"
            "Subject: Test\n"
        )
        self.assertEqual(
            search_tools._referenced_ids(headers),
            {"one@example.com", "two@example.com"},
        )

    def _record(self, message_id, refs=(), age=0, subject="Angebot"):
        return {
            "message_id": message_id,
            "references": set(refs),
            "age_seconds": age,
            "subject": subject,
            "sender": "a@example.com",
            "date": "heute",
            "read": True,
            "mailbox": "INBOX",
            "preview": "",
        }

    def test_same_subject_from_another_conversation_is_separated(self):
        records = [
            self._record("root@x", age=-300),
            self._record("reply@x", refs=["root@x"], age=-100),
            self._record("stranger@y", age=-200),
        ]
        linked, unlinked = search_tools._split_thread_by_linkage(records)
        self.assertEqual(
            [r["message_id"] for r in linked], ["root@x", "reply@x"]
        )
        self.assertEqual([r["message_id"] for r in unlinked], ["stranger@y"])

    def test_chain_joins_even_when_the_link_comes_later(self):
        # The newest message references its parent, the parent references the
        # root: one pass over the list would miss the root.
        records = [
            self._record("root@x", age=-300),
            self._record("middle@x", refs=["root@x"], age=-200),
            self._record("newest@x", refs=["middle@x"], age=-100),
        ]
        linked, unlinked = search_tools._split_thread_by_linkage(records)
        self.assertEqual(len(linked), 3)
        self.assertEqual(unlinked, [])

    def test_message_without_ids_stays_in_the_thread(self):
        # Better to show it than to hide mail the old subject grouping listed.
        records = [
            self._record("", age=-200),
            self._record("newest@x", age=-100),
        ]
        linked, unlinked = search_tools._split_thread_by_linkage(records)
        self.assertEqual(len(linked), 2)
        self.assertEqual(unlinked, [])

    def test_thread_is_sorted_oldest_first(self):
        records = [
            self._record("root@x", age=-300),
            self._record("reply@x", refs=["root@x"], age=-100),
        ]
        linked, _ = search_tools._split_thread_by_linkage(records)
        self.assertEqual([r["age_seconds"] for r in linked], [-300, -100])


class DraftResurrectionTests(unittest.TestCase):
    """A deleted draft used to come back a few seconds later.

    Mail keeps the compose object alive after saving and autosaves it again:
    measured 25.08.2026, the draft was gone at t+10 s and back at t+15 s with
    a new id. Closing the invisible compose object without saving stops it.
    """

    def test_delete_closes_the_invisible_compose_object(self):
        _, scripts = _capture(
            compose_tools.manage_drafts,
            account="Work",
            action="delete",
            draft_subject="Update",
        )
        script = scripts[0]
        self.assertIn("close aCompose saving no", script)
        self.assertLess(
            script.index("delete foundDraft"),
            script.index("close aCompose saving no"),
            "the draft is deleted first, then its compose object is silenced",
        )

    def test_only_invisible_compose_objects_are_closed(self):
        # A visible compose object is a window the user has open; closing it
        # without saving would throw away whatever they are writing.
        _, scripts = _capture(
            compose_tools.manage_drafts,
            account="Work",
            action="delete",
            draft_subject="Update",
        )
        self.assertIn("(visible of aCompose) is false", scripts[0])

    def test_update_silences_the_old_version_too(self):
        with patch.object(
            compose_tools, "run_applescript", return_value="gone"
        ) as mock_run:
            compose_tools._delete_draft_by_id("42", "Work")
        script = mock_run.call_args[0][0]
        self.assertIn("close aCompose saving no", script)
        self.assertIn("(visible of aCompose) is false", script)

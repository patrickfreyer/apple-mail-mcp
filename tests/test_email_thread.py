"""Tests for get_email_thread: grouping by Message-ID, not by subject."""

import unittest
from unittest.mock import patch

from apple_mail_mcp.tools import search as search_tools

SEP = "<<<AMMCP-0000000000000000>>>"
ROW = "<<<AMMCPROW-0000000000000000>>>"


def _record(message_id, refs=(), age=0, subject="Proposal"):
    return {
        "message_id": message_id,
        "references": set(refs),
        "age_seconds": age,
        "subject": subject,
        "sender": "a@example.com",
        "date": "today",
        "read": True,
        "mailbox": "INBOX",
        "preview": "",
    }


def _row(message_id, subject, age, headers=""):
    fields = [
        message_id,
        subject,
        "a@example.com",
        "Monday, 12. October 2026",
        str(age),
        "true",
        "INBOX",
        "preview",
        headers,
    ]
    return SEP.join(fields) + ROW


class ThreadHelperTests(unittest.TestCase):
    def test_prefixes_are_stripped_repeatedly(self):
        self.assertEqual(
            search_tools._strip_thread_prefixes("Re: AW: Fwd: Proposal"), "Proposal"
        )
        self.assertEqual(search_tools._strip_thread_prefixes("Proposal"), "Proposal")

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


class ThreadLinkageTests(unittest.TestCase):
    def test_same_subject_from_another_conversation_is_separated(self):
        records = [
            _record("root@x", age=-300),
            _record("reply@x", refs=["root@x"], age=-100),
            _record("stranger@y", age=-200),
        ]
        linked, unlinked = search_tools._split_thread_by_linkage(records)
        self.assertEqual([r["message_id"] for r in linked], ["root@x", "reply@x"])
        self.assertEqual([r["message_id"] for r in unlinked], ["stranger@y"])

    def test_chain_joins_even_when_the_link_comes_later(self):
        # The newest message references its parent, the parent references the
        # root: a single pass over the list would miss the root.
        records = [
            _record("root@x", age=-300),
            _record("middle@x", refs=["root@x"], age=-200),
            _record("newest@x", refs=["middle@x"], age=-100),
        ]
        linked, unlinked = search_tools._split_thread_by_linkage(records)
        self.assertEqual(len(linked), 3)
        self.assertEqual(unlinked, [])

    def test_message_without_ids_stays_in_the_thread(self):
        # Better to show it than to hide mail the subject grouping used to list.
        records = [_record("", age=-200), _record("newest@x", age=-100)]
        linked, unlinked = search_tools._split_thread_by_linkage(records)
        self.assertEqual(len(linked), 2)
        self.assertEqual(unlinked, [])

    def test_thread_is_sorted_oldest_first(self):
        records = [
            _record("reply@x", refs=["root@x"], age=-100),
            _record("root@x", age=-300),
        ]
        linked, _ = search_tools._split_thread_by_linkage(records)
        self.assertEqual([r["age_seconds"] for r in linked], [-300, -100])


class GetEmailThreadTests(unittest.TestCase):
    def _run(self, applescript_output, **kwargs):
        with (
            patch(
                "apple_mail_mcp.tools.search.os.urandom", return_value=b"\x00" * 8
            ),
            patch(
                "apple_mail_mcp.tools.search.run_applescript",
                return_value=applescript_output,
            ) as mock_run,
        ):
            result = search_tools.get_email_thread(
                account="Work", subject_keyword="Re: Proposal", **kwargs
            )
        return result, mock_run.call_args[0][0]

    def test_lists_strangers_with_the_same_subject_separately(self):
        output = (
            _row("<root@x>", "Proposal", -300)
            + _row("<stranger@y>", "Proposal", -200)
            + _row("<reply@x>", "Re: Proposal", -100, "In-Reply-To: <root@x>\n")
        )
        result, script = self._run(output)

        self.assertIn('whose subject contains "Proposal"', script)
        self.assertIn("FOUND 2 MESSAGE(S) IN THREAD", result)
        self.assertIn(
            "1 MESSAGE(S) WITH THE SAME SUBJECT BUT NO LINK TO THIS THREAD", result
        )

    def test_reports_no_match(self):
        result, _ = self._run("")
        self.assertIn("No message found matching: Re: Proposal", result)

    def test_surfaces_applescript_errors(self):
        result, _ = self._run("ERROR" + SEP + "Mailbox not found: Foo")
        self.assertEqual(result, "Error: Mailbox not found: Foo")

    def test_rejects_a_keyword_that_is_only_prefixes(self):
        with patch("apple_mail_mcp.tools.search.run_applescript") as mock_run:
            result = search_tools.get_email_thread(
                account="Work", subject_keyword="Re: "
            )
        mock_run.assert_not_called()
        self.assertTrue(result.startswith("Error:"))


if __name__ == "__main__":
    unittest.main()

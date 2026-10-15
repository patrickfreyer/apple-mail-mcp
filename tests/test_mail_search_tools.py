"""Tests for structured email search and bulk update helpers."""

import json
import unittest
from unittest.mock import patch

from apple_mail_mcp.tools import manage as manage_tools
from apple_mail_mcp.tools import search as search_tools
from apple_mail_mcp.tools import smart_inbox as smart_inbox_tools


def _record_line(
    message_id,
    subject,
    internet_message_id="<abc@example.com>",
    sender="sender@example.com",
    mailbox="INBOX",
    account="Work",
    is_read=False,
    received_date="2026-03-07T10:00:00",
    flag_index=-1,
    content_preview="",
):
    return "|||".join(
        [
            str(message_id),
            internet_message_id,
            subject,
            sender,
            mailbox,
            account,
            "true" if is_read else "false",
            received_date,
            str(flag_index),
            content_preview,
        ]
    )


class SearchToolTests(unittest.TestCase):
    def test_search_emails_pagination_consistency(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return "\n".join(
                [
                    _record_line(
                        100,
                        "Ticket 100",
                        received_date="2026-03-07T12:00:00",
                    ),
                    _record_line(
                        101,
                        "Ticket 101",
                        received_date="2026-03-07T11:00:00",
                    ),
                    _record_line(
                        102,
                        "Ticket 102",
                        received_date="2026-03-07T10:00:00",
                    ),
                ]
            )

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            response = json.loads(
                search_tools.search_emails(
                    account="Work",
                    output_format="json",
                    offset=1,
                    limit=2,
                    max_results=None,
                )
            )

        self.assertEqual(response["offset"], 1)
        self.assertEqual(response["returned"], 2)
        self.assertTrue(response["has_more"])
        self.assertEqual(response["next_offset"], 3)
        self.assertEqual(
            response["items"][0]["mail_link"],
            "message://%3Cabc@example.com%3E",
        )
        self.assertIn("set offsetRemaining to 1", captured["script"])
        self.assertIn("set collectLimit to 3", captured["script"])

    def test_search_emails_unread_only_filter(self):
        """Test that read_status='unread' adds the correct whose clause."""
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return _record_line(201, "Unread Ticket", is_read=False)

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            response = json.loads(
                search_tools.search_emails(
                    account="Work",
                    subject_keyword="Ticket",
                    read_status="unread",
                    output_format="json",
                    limit=1,
                )
            )

        self.assertEqual(len(response["items"]), 1)
        self.assertFalse(response["items"][0]["is_read"])
        self.assertIn("read status is false", captured["script"])

    def test_search_emails_builds_real_date_filters(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return _record_line(
                301,
                "Dated Ticket",
                received_date="2026-03-05T09:00:00",
            )

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            response = json.loads(
                search_tools.search_emails(
                    account="Work",
                    subject_keyword="Ticket",
                    date_from="2026-03-01",
                    date_to="2026-03-07",
                    output_format="json",
                    limit=1,
                    max_results=None,
                )
            )

        self.assertEqual(response["items"][0]["message_id"], "301")
        self.assertIn("set year of fromDate to 2026", captured["script"])
        self.assertIn("set month of fromDate to March", captured["script"])
        self.assertIn("date received >= fromDate", captured["script"])
        self.assertIn("date received <= toDate", captured["script"])

    def test_large_mailbox_search_uses_prefiltered_selection(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return ""

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            response = json.loads(
                search_tools.search_emails(
                    account="Work",
                    subject_keywords=["INC-1", "INC-2"],
                    include_content=False,
                    output_format="json",
                    limit=50,
                    max_results=None,
                )
            )

        self.assertEqual(response["items"], [])
        self.assertIn(
            "set matchingMessages to every message of currentMailbox whose",
            captured["script"],
        )
        self.assertNotIn(
            "set mailboxMessages to every message of currentMailbox", captured["script"]
        )

    def test_search_emails_returns_mail_link_from_internet_message_id(self):
        def fake_run(script, timeout=120):
            return _record_line(
                401,
                "Linked Ticket",
                internet_message_id="<QwcH6OP9REaEX0pi8aR6-g@geopod-ismtpd-60>",
            )

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            response = json.loads(
                search_tools.search_emails(
                    account="Work",
                    subject_keyword="Linked",
                    output_format="json",
                    limit=1,
                    max_results=None,
                )
            )

        self.assertEqual(
            response["items"][0]["internet_message_id"],
            "<QwcH6OP9REaEX0pi8aR6-g@geopod-ismtpd-60>",
        )
        self.assertEqual(
            response["items"][0]["mail_link"],
            "message://%3CQwcH6OP9REaEX0pi8aR6-g@geopod-ismtpd-60%3E",
        )

    def test_search_emails_mail_link_normalizes_missing_angle_brackets(self):
        """AppleScript sometimes returns the Message-ID without angle brackets;
        the mail_link should still include them (percent-encoded)."""

        def fake_run(script, timeout=120):
            return _record_line(
                402,
                "Unbracketed Ticket",
                internet_message_id="abc@example.com",
            )

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            response = json.loads(
                search_tools.search_emails(
                    account="Work",
                    subject_keyword="Unbracketed",
                    output_format="json",
                    limit=1,
                    max_results=None,
                )
            )

        self.assertEqual(
            response["items"][0]["internet_message_id"],
            "abc@example.com",
        )
        self.assertEqual(
            response["items"][0]["mail_link"],
            "message://%3Cabc@example.com%3E",
        )

    def test_search_emails_account_none_iterates_all_accounts(self):
        """When account is None, the script should iterate all accounts."""
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return ""

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            search_tools.search_emails(
                account=None,
                subject_keyword="Test",
                output_format="json",
                limit=5,
            )

        self.assertIn("set searchAccounts to every account", captured["script"])

    def test_search_emails_body_text_uses_lowercase_handler(self):
        """When body_text is provided, the script should include LOWERCASE_HANDLER."""
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return ""

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            search_tools.search_emails(
                account="Work",
                body_text="invoice",
                output_format="json",
                limit=5,
            )

        self.assertIn("on lowercase(str)", captured["script"])
        self.assertIn('lowerContent contains "invoice"', captured["script"])

    def test_search_emails_reports_flag_color(self):
        def fake_run(script, timeout=120):
            return "\n".join(
                [
                    _record_line(100, "Flagged orange", flag_index=1),
                    _record_line(101, "Not flagged", flag_index=-1),
                ]
            )

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            result = search_tools.search_emails(
                account="Work",
                output_format="json",
            )

        items = json.loads(result)["items"]
        flagged_item = next(i for i in items if i["message_id"] == "100")
        plain_item = next(i for i in items if i["message_id"] == "101")
        self.assertTrue(flagged_item["is_flagged"])
        self.assertEqual(flagged_item["flag_color"], "orange")
        self.assertFalse(plain_item["is_flagged"])
        self.assertNotIn("flag_color", plain_item)

    def test_search_emails_text_output_shows_flag_marker(self):
        def fake_run(script, timeout=120):
            return _record_line(100, "Budget review", flag_index=3)

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            result = search_tools.search_emails(account="Work")

        self.assertIn("Budget review ⚑ green", result)

    def test_search_emails_flagged_filter_builds_whose_clause(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return ""

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            search_tools.search_emails(account="Work", flagged=True)

        self.assertIn("flagged status is true", captured["script"])

    def test_search_emails_flag_color_filter_uses_flag_index(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return ""

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            search_tools.search_emails(account="Work", flag_color="purple")

        self.assertIn(
            "(flagged status is true and flag index is 5)", captured["script"]
        )

    def test_search_emails_flag_color_in_body_search_path(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return ""

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            search_tools.search_emails(
                account="Work", body_text="invoice", flag_color="red"
            )

        self.assertIn("messageFlagIndex is 0", captured["script"])
        # Read in both scan loops (bounded for large mailboxes, full for the
        # rest) and in the record emission block.
        self.assertEqual(
            captured["script"].count("set messageFlagIndex to flag index of aMessage"),
            3,
        )

    def test_search_emails_body_search_skips_flag_read_without_flag_filter(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return ""

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            search_tools.search_emails(account="Work", body_text="invoice")

        # Only the record emission block reads flag index; the per-message
        # scan loop must not pay for it when no flag filter is set.
        self.assertEqual(
            captured["script"].count("set messageFlagIndex to flag index of aMessage"),
            1,
        )

    def test_search_emails_rejects_invalid_flag_color(self):
        with patch("apple_mail_mcp.tools.search.run_applescript") as mock_run:
            result = search_tools.search_emails(account="Work", flag_color="magenta")

        self.assertIn("Invalid flag_color", result)
        mock_run.assert_not_called()

    def test_search_emails_rejects_flag_color_with_flagged_false(self):
        with patch("apple_mail_mcp.tools.search.run_applescript") as mock_run:
            result = search_tools.search_emails(
                account="Work", flagged=False, flag_color="blue"
            )

        self.assertIn("flag_color cannot be combined", result)
        mock_run.assert_not_called()

    # -- Issue #41: search_emails hangs / returns empty on very large
    # (90,000+ message) mailboxes because it always materializes the full
    # mailbox via `every message of currentMailbox [whose ...]`, an
    # unindexed AppleScript scan with no upper bound. --------------------

    def test_search_emails_large_mailbox_scan_is_bounded_by_index(self):
        """The generated script must guard full-mailbox materialization
        behind a cheap `count of messages` check and fall back to a capped,
        early-exiting index scan instead of always pulling every message
        into memory in one Apple event."""
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return ""

        with patch(
            "apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run
        ):
            search_tools.search_emails(
                account="Work", sender="boss@example.com", limit=5
            )

        script = captured["script"]
        self.assertIn("count of messages of currentMailbox", script)
        self.assertIn("if totalMessageCount >", script)
        # Bounded path reads messages by index and can stop early rather
        # than pulling the whole mailbox into memory up front.
        self.assertIn("repeat with msgIndex from", script)
        self.assertIn("message msgIndex of currentMailbox", script)
        # The size guard must appear before the whose-clause materialization
        # — i.e. materialization is now conditional, not unconditional.
        guard_pos = script.index("if totalMessageCount >")
        materialize_pos = script.index(
            "set matchingMessages to every message of currentMailbox whose"
        )
        self.assertLess(guard_pos, materialize_pos)

    def test_search_emails_bounded_scan_direction_follows_sort(self):
        """date_desc (the default) must scan from the newest end of the
        mailbox first, so a capped scan still surfaces the most relevant
        matches instead of the oldest ones.

        In Mail, message 1 is the newest: checked on a 75,190-message Gmail
        INBOX (message 1 received today, message 4000 three months earlier,
        the last one in 2005). So newest-first walks the indexes upward."""
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return ""

        with patch(
            "apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run
        ):
            search_tools.search_emails(account="Work", sort="date_desc", limit=5)
        self.assertIn(
            "repeat with msgIndex from 1 to totalMessageCount by 1",
            captured["script"],
        )

        with patch(
            "apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run
        ):
            search_tools.search_emails(account="Work", sort="date_asc", limit=5)
        self.assertIn(
            "repeat with msgIndex from totalMessageCount to 1 by -1",
            captured["script"],
        )

    def test_search_emails_scan_cap_is_shared_across_mailboxes(self):
        """mailbox="All" must not get a fresh cap per large mailbox: the
        counter is set once per call and never reset inside the loop."""
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return ""

        with patch(
            "apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run
        ):
            search_tools.search_emails(account="Work", mailbox="All", limit=5)
        script = captured["script"]
        self.assertEqual(script.count("set scannedTotal to 0"), 1)
        self.assertLess(
            script.index("set scannedTotal to 0"),
            script.index("repeat with targetAccount in searchAccounts"),
        )
        self.assertIn(
            f"if scannedTotal > {search_tools.BOUNDED_SCAN_MAX_MESSAGES} then",
            script,
        )

    def test_search_emails_body_search_is_bounded_on_large_mailboxes(self):
        """body_text reads every message's content; on a very large mailbox it
        must use the capped, newest-first index scan with an early exit."""
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return ""

        with patch(
            "apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run
        ):
            search_tools.search_emails(account="Work", body_text="invoice", limit=5)
        script = captured["script"]
        self.assertIn(
            f"if totalMessageCount > {search_tools.WHOSE_CLAUSE_SAFE_LIMIT} then",
            script,
        )
        self.assertIn(
            f"if scannedTotal > {search_tools.BOUNDED_BODY_SCAN_MAX_MESSAGES} then",
            script,
        )
        self.assertIn("repeat with msgIndex from 1 to totalMessageCount by 1", script)
        self.assertIn(
            "if (count of matchingMessages) >= scanTarget then exit repeat", script
        )

    def test_search_emails_reports_scan_limited_instead_of_silent_empty(self):
        """When Mail signals that a large-mailbox scan hit its safety cap
        before finishing, search_emails must surface that honestly instead
        of returning an indistinguishable empty/partial result."""

        def fake_run_with_hit(script, timeout=120):
            return "SCAN_LIMITED=true\n" + _record_line(500, "Found before cap")

        with patch(
            "apple_mail_mcp.tools.search.run_applescript",
            side_effect=fake_run_with_hit,
        ):
            response = json.loads(
                search_tools.search_emails(
                    account="Work", output_format="json", limit=5
                )
            )

        self.assertEqual(len(response["items"]), 1)
        self.assertTrue(response["scan_limited"])

        def fake_run_empty(script, timeout=120):
            return "SCAN_LIMITED=true\n"

        with patch(
            "apple_mail_mcp.tools.search.run_applescript",
            side_effect=fake_run_empty,
        ):
            text_response = search_tools.search_emails(account="Work", limit=5)

        self.assertIn("FOUND: 0", text_response)
        self.assertIn("NOTE", text_response.upper())

    def test_search_emails_scan_not_limited_by_default(self):
        """Normal, non-truncated responses must not carry a scan_limited
        flag or warning text."""

        def fake_run(script, timeout=120):
            return _record_line(600, "Normal result")

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            response = json.loads(
                search_tools.search_emails(
                    account="Work", output_format="json", limit=5
                )
            )
        self.assertFalse(response["scan_limited"])

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            text_response = search_tools.search_emails(account="Work", limit=5)
        self.assertNotIn("NOTE", text_response.upper())


class ManageToolTests(unittest.TestCase):
    def test_update_email_status_with_message_ids_uses_exact_id_condition(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return "updated"

        with patch("apple_mail_mcp.tools.manage.run_applescript", side_effect=fake_run):
            result = manage_tools.update_email_status(
                account="Work",
                mailbox="INBOX",
                message_ids=["101", "202"],
                action="mark_read",
            )

        self.assertEqual(result, "updated")
        self.assertIn("id is 101", captured["script"])
        self.assertIn("id is 202", captured["script"])
        self.assertIn("set read status of targetMessages to true", captured["script"])

    def test_update_email_status_flag_color_sets_flag_index(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return "updated"

        with patch("apple_mail_mcp.tools.manage.run_applescript", side_effect=fake_run):
            result = manage_tools.update_email_status(
                account="Work",
                mailbox="INBOX",
                message_ids=["101"],
                action="flag",
                flag_color="Orange",
            )

        self.assertEqual(result, "updated")
        self.assertIn("set flag index of targetMessages to 1", captured["script"])
        self.assertIn("Flagged (orange)", captured["script"])
        # flag index alone doesn't activate the flag; both must be set.
        self.assertIn("set flagged status of targetMessages to true", captured["script"])

    def test_update_email_status_flag_without_color_uses_flagged_status(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return "updated"

        with patch("apple_mail_mcp.tools.manage.run_applescript", side_effect=fake_run):
            manage_tools.update_email_status(
                account="Work",
                mailbox="INBOX",
                message_ids=["101"],
                action="flag",
            )

        self.assertIn("set flagged status of targetMessages to true", captured["script"])
        self.assertNotIn("flag index", captured["script"])

    def test_update_email_status_flag_color_filter_path_matches_other_colors(self):
        captured = {}

        def fake_run(script, timeout=300):
            captured["script"] = script
            return "updated"

        with patch("apple_mail_mcp.tools.manage.run_applescript", side_effect=fake_run):
            manage_tools.update_email_status(
                account="Work",
                mailbox="INBOX",
                subject_keyword="invoice",
                action="flag",
                flag_color="green",
            )

        self.assertIn(
            "(flag index is not 3 or flagged status is false)", captured["script"]
        )
        self.assertIn("set flag index of aMessage to 3", captured["script"])
        self.assertIn("set flagged status of aMessage to true", captured["script"])

    def test_update_email_status_rejects_invalid_flag_color(self):
        with patch("apple_mail_mcp.tools.manage.run_applescript") as mock_run:
            result = manage_tools.update_email_status(
                account="Work",
                mailbox="INBOX",
                message_ids=["101"],
                action="flag",
                flag_color="magenta",
            )

        self.assertIn("Invalid flag_color", result)
        mock_run.assert_not_called()

    def test_update_email_status_rejects_flag_color_with_other_actions(self):
        with patch("apple_mail_mcp.tools.manage.run_applescript") as mock_run:
            result = manage_tools.update_email_status(
                account="Work",
                mailbox="INBOX",
                message_ids=["101"],
                action="mark_read",
                flag_color="red",
            )

        self.assertIn("only valid with action='flag'", result)
        mock_run.assert_not_called()


class SmartInboxToolTests(unittest.TestCase):
    def test_get_needs_response_priority_label_includes_flag_color(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return "no results"

        with patch(
            "apple_mail_mcp.tools.smart_inbox.run_applescript", side_effect=fake_run
        ):
            smart_inbox_tools.get_needs_response(account="Work")

        self.assertIn("set flagIndex to flag index of aMessage", captured["script"])
        self.assertIn(
            'set flagColorNames to {"red", "orange", "yellow", "green", "blue", "purple", "gray"}',
            captured["script"],
        )
        self.assertIn('"HIGH (" & flagLabel & " + question)"', captured["script"])

    @staticmethod
    def _awaiting_reply_script(**kwargs):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return "no results"

        with patch(
            "apple_mail_mcp.tools.smart_inbox.run_applescript", side_effect=fake_run
        ):
            smart_inbox_tools.get_awaiting_reply(account="Work", **kwargs)

        return captured["script"]

    def test_get_awaiting_reply_bounds_inbox_scan_by_date(self):
        """The inbox cross-reference must stop at the date cutoff.

        Unbounded, this loop fetched two properties for every message in the
        inbox, which timed out on large mailboxes before returning anything.
        """
        script = self._awaiting_reply_script(days_back=14)

        self.assertIn("if msgDate < cutoffDate then", script)
        self.assertIn(
            f"if staleRun > {smart_inbox_tools.INBOX_STALE_RUN_LIMIT} then exit repeat",
            script,
        )
        # Subject/sender are only fetched for in-window messages.
        self.assertIn("set end of inboxSubjects to lowerBase", script)

        # `date received` must be fetched BEFORE subject/sender, so an
        # out-of-window message costs one round-trip instead of three. That
        # cost property is the whole point of the fix, so pin the order.
        date_fetch = script.index("set msgDate to date received of aMessage")
        subject_fetch = script.index("set msgSubject to subject of aMessage")
        self.assertLess(date_fetch, subject_fetch)

    def test_get_awaiting_reply_stale_run_counts_consecutive_only(self):
        """The stale-run counter must reset on every in-window message.

        Without the reset it becomes a cumulative count, and a mailbox with
        INBOX_STALE_RUN_LIMIT out-of-window messages scattered anywhere in the
        scan would truncate the entire cross-reference — reporting answered
        mail as awaiting reply, the exact failure the tolerance exists to
        prevent.
        """
        script = self._awaiting_reply_script(days_back=14)

        self.assertIn("set staleRun to staleRun + 1", script)
        # The reset lives in the else branch, i.e. after the increment.
        increment = script.index("set staleRun to staleRun + 1")
        reset = script.index("set staleRun to 0", increment)
        self.assertGreater(reset, increment)
        # ...and before the in-window property fetch it guards.
        self.assertLess(reset, script.index("set msgSubject to subject of aMessage"))

    def test_get_awaiting_reply_keeps_parallel_lists_index_aligned(self):
        """Both appends must follow every operation that can throw.

        inboxSubjects and inboxSenders are indexed in lockstep by the matching
        loop. Appending a subject and then throwing on the sender would shift
        every later index by one and silently mispair subjects with senders.
        """
        script = self._awaiting_reply_script(days_back=14)

        last_throwing = script.index("set lowerSender to my lowercase(msgSender)")
        first_append = script.index("set end of inboxSubjects to lowerBase")
        self.assertLess(last_throwing, first_append)
        self.assertIn("set end of inboxSenders to lowerSender", script)

    def test_get_awaiting_reply_caps_inbox_scan_count(self):
        """A hard count cap bounds cost independently of the date cutoff."""
        for days_back in (14, 0):
            with self.subTest(days_back=days_back):
                script = self._awaiting_reply_script(days_back=days_back)
                self.assertIn("set inboxScanned to inboxScanned + 1", script)
                self.assertIn(
                    f"if inboxScanned > {smart_inbox_tools.INBOX_SCAN_CAP} then", script
                )
                # Truncation is disclosed rather than silently changing results.
                self.assertIn("if inboxCapHit then", script)

    def test_get_awaiting_reply_all_time_has_no_cutoff_reference(self):
        """days_back=0 means all time: cutoffDate is never defined, so the
        generated script must not reference it (the count cap is the bound)."""
        script = self._awaiting_reply_script(days_back=0)

        self.assertNotIn("cutoffDate", script)
        self.assertIn("set inboxScanned to inboxScanned + 1", script)

    def test_get_awaiting_reply_matches_on_sender_before_indexing_subjects(self):
        """Sender is the selective test, so it gates the O(idx) list indexing."""
        script = self._awaiting_reply_script(days_back=14)

        self.assertIn("repeat with inboxSender in inboxSenders", script)
        sender_check = script.index("if inboxSender contains lowerRecipAddr then")
        subject_index = script.index("set inboxSubj to item idx of inboxSubjects")
        self.assertLess(sender_check, subject_index)


if __name__ == "__main__":
    unittest.main()

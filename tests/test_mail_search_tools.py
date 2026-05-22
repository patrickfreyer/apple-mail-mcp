"""Tests for structured email search and bulk update helpers."""

import asyncio
import json
import unittest
from unittest.mock import patch

from apple_mail_mcp.core import AppleScriptTimeout
from apple_mail_mcp.tools import manage as manage_tools
from apple_mail_mcp.tools import search as search_tools
from apple_mail_mcp.tools import inbox as inbox_tools


def _record_line(
    message_id,
    subject,
    internet_message_id="<abc@example.com>",
    sender="sender@example.com",
    mailbox="INBOX",
    account="Work",
    is_read=False,
    received_date="2026-03-07T10:00:00",
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
            content_preview,
        ]
    )


def _run(coro):
    """Convenience: drive an async tool to completion from a sync test."""
    return asyncio.run(coro)


def _clear_default_mail_account():
    """Multi-account dispatch tests must not inherit DEFAULT_MAIL_ACCOUNT from env."""
    from apple_mail_mcp import server as _srv

    return patch.object(_srv, "DEFAULT_MAIL_ACCOUNT", None)


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
                _run(
                    search_tools.search_emails(
                        account="Work",
                        output_format="json",
                        offset=1,
                        limit=2,
                        max_results=None,
                    )
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
                _run(
                    search_tools.search_emails(
                        account="Work",
                        subject_keyword="Ticket",
                        read_status="unread",
                        output_format="json",
                        limit=1,
                    )
                )
            )

        self.assertEqual(len(response["items"]), 1)
        self.assertFalse(response["items"][0]["is_read"])
        self.assertIn("messageRead is false", captured["script"])

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
                _run(
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
            )

        self.assertEqual(response["items"][0]["message_id"], "301")
        self.assertIn("set year of fromDate to 2026", captured["script"])
        self.assertIn("set month of fromDate to March", captured["script"])
        self.assertIn("messageDate >= fromDate", captured["script"])
        self.assertIn("messageDate <= toDate", captured["script"])

    def test_large_mailbox_search_uses_applescript_cap(self):
        """A1: when subject/sender filters are supplied, the script must bind
        a bounded newest-message slice and filter inside it so a 24K-message
        Exchange mailbox doesn't materialize every match."""
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return ""

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            response = json.loads(
                _run(
                    search_tools.search_emails(
                        account="Work",
                        subject_keywords=["INC-1", "INC-2"],
                        include_content=False,
                        output_format="json",
                        limit=50,
                        max_results=None,
                    )
                )
            )

        self.assertEqual(response["items"], [])
        # A1 cap: limit+1 = 51 (offset=0)
        self.assertIn("set scanUpperBound to 51", captured["script"])
        self.assertIn("messages 1 thru scanUpperBound of currentMailbox", captured["script"])
        # The old, unfiltered enumeration must not appear.
        self.assertNotIn(
            "set matchingMessages to every message of currentMailbox\n",
            captured["script"],
        )
        self.assertNotIn("every message of currentMailbox whose", captured["script"])

    def test_no_filter_caps_via_messages_1_thru_n(self):
        """A1: with no filter conditions, the script should bind
        `messages 1 thru N` directly instead of `every message`."""
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return ""

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            _run(
                search_tools.search_emails(
                    account="Work",
                    output_format="json",
                    limit=10,
                    max_results=None,
                    recent_days=0,
                    allow_full_scan=True,
                )
            )

        self.assertIn("set scanUpperBound to 11", captured["script"])
        self.assertIn("messages 1 thru scanUpperBound of currentMailbox", captured["script"])
        # `every message` should not appear as the binding source (the helper
        # functions don't reference it either in this branch).
        self.assertNotIn("set matchingMessages to every message", captured["script"])

    def test_date_only_filter_uses_whose_clause(self):
        """A2: a date-only call still filters inside the bounded slice so it
        doesn't fall back to a full-scan branch."""
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return ""

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            _run(
                search_tools.search_emails(
                    account="Work",
                    date_from="2026-05-01",
                    output_format="json",
                    limit=10,
                    max_results=None,
                )
            )

        self.assertIn("messages 1 thru scanUpperBound of currentMailbox", captured["script"])
        self.assertIn("messageDate >= fromDate", captured["script"])
        self.assertNotIn("every message of currentMailbox whose", captured["script"])

    def test_search_emails_returns_mail_link_from_internet_message_id(self):
        def fake_run(script, timeout=120):
            return _record_line(
                401,
                "Linked Ticket",
                internet_message_id="<QwcH6OP9REaEX0pi8aR6-g@geopod-ismtpd-60>",
            )

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            response = json.loads(
                _run(
                    search_tools.search_emails(
                        account="Work",
                        subject_keyword="Linked",
                        output_format="json",
                        limit=1,
                        max_results=None,
                    )
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
                _run(
                    search_tools.search_emails(
                        account="Work",
                        subject_keyword="Unbracketed",
                        output_format="json",
                        limit=1,
                        max_results=None,
                    )
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

    def test_search_emails_account_none_dispatches_per_account(self):
        """A4b: when account is None, the tool first lists accounts (one
        AppleScript call), then runs one AppleScript per account in
        parallel via asyncio.to_thread. Each per-account script targets
        a single account via `{account "..."}`."""
        scripts = []

        def fake_run(script, timeout=120):
            scripts.append(script)
            # First call is the account list probe — return two account names.
            if "set acctNames to" in script:
                return "Work\nPersonal"
            # Subsequent per-account calls return no records.
            return ""

        with _clear_default_mail_account(), patch(
            "apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run
        ):
            _run(
                search_tools.search_emails(
                    account=None,
                    subject_keyword="Test",
                    output_format="json",
                    limit=5,
                )
            )

        # 1 list-accounts call + 2 per-account search calls
        self.assertEqual(len(scripts), 3)
        per_account_scripts = scripts[1:]
        self.assertTrue(
            any('set searchAccounts to {account "Work"}' in s for s in per_account_scripts)
        )
        self.assertTrue(
            any('set searchAccounts to {account "Personal"}' in s for s in per_account_scripts)
        )

    def test_search_emails_body_text_uses_ignoring_case_not_lowercase_handler(self):
        """A4c: body-search must no longer rely on the per-message shell-out
        lowercase handler. Instead it wraps comparisons in `ignoring case`."""
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return ""

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            _run(
                search_tools.search_emails(
                    account="Work",
                    body_text="invoice",
                    output_format="json",
                    limit=5,
                )
            )

        self.assertNotIn("on lowercase(", captured["script"])
        self.assertNotIn("my lowercase(", captured["script"])
        self.assertIn("ignoring case", captured["script"])
        self.assertIn('msgContent contains "invoice"', captured["script"])

    def test_get_email_by_id_returns_exact_message_json(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return _record_line(
                12345,
                "Exact Ticket",
                content_preview="Full body preview",
            )

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            response = json.loads(
                search_tools.get_email_by_id(
                    account="Work",
                    message_id="12345",
                    output_format="json",
                )
            )

        self.assertEqual(response["item"]["message_id"], "12345")
        self.assertEqual(response["item"]["subject"], "Exact Ticket")
        self.assertEqual(response["item"]["content_preview"], "Full body preview")
        self.assertIn("whose id is 12345", captured["script"])

    def test_get_email_by_id_rejects_non_numeric_ids(self):
        result = search_tools.get_email_by_id(
            account="Work",
            message_id="abc",
            output_format="json",
        )

        self.assertIn("message_id must be a numeric", result)

    def test_search_emails_timeout_param_is_forwarded(self):
        """A3: an explicit `timeout=N` kwarg must reach run_applescript so the
        caller can extend (or shorten) the per-account budget."""
        captured = {}

        def fake_run(script, timeout=120):
            captured["timeout"] = timeout
            return ""

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            _run(
                search_tools.search_emails(
                    account="Work",
                    subject_keyword="Test",
                    output_format="json",
                    limit=5,
                    timeout=300,
                )
            )

        self.assertEqual(captured["timeout"], 300)

    def test_search_emails_per_account_timeout_yields_errors_field(self):
        """A4: when one account's AppleScript times out, the call must still
        return data from the other accounts plus an `errors` list naming the
        slow account(s)."""

        def fake_run(script, timeout=120):
            if "set acctNames to" in script:
                return "Work\nTU"
            if 'account "TU"' in script:
                raise AppleScriptTimeout("TU timed out")
            # Work returns one record.
            return _record_line(700, "Work email", account="Work")

        with _clear_default_mail_account(), patch(
            "apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run
        ):
            response = json.loads(
                _run(
                    search_tools.search_emails(
                        account=None,
                        subject_keyword="Anything",
                        output_format="json",
                        limit=5,
                    )
                )
            )

        self.assertIn("errors", response)
        self.assertEqual(response["errors"], ["TU"])
        self.assertEqual(len(response["items"]), 1)
        self.assertEqual(response["items"][0]["account"], "Work")

    def test_search_emails_single_account_skips_account_listing(self):
        """A4b: when an explicit account is passed, the tool must NOT run the
        account-listing probe — single-account calls should incur zero gather
        overhead."""
        scripts = []

        def fake_run(script, timeout=120):
            scripts.append(script)
            return ""

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            _run(
                search_tools.search_emails(
                    account="Work",
                    subject_keyword="Test",
                    output_format="json",
                    limit=5,
                )
            )

        self.assertEqual(len(scripts), 1)
        self.assertNotIn("set acctNames to", scripts[0])

    def test_search_emails_default_recent_days_applies_48h_window(self):
        """A0a: with no date args, a 48h window is auto-applied — the script
        must contain a populated `fromDate` and a `date received >= fromDate`
        clause, and the JSON response must echo `recent_days_applied=2.0`."""
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return ""

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            response = json.loads(
                _run(
                    search_tools.search_emails(
                        account="Work",
                        output_format="json",
                        limit=5,
                    )
                )
            )

        self.assertIn("set year of fromDate to", captured["script"])
        self.assertIn("messageDate >= fromDate", captured["script"])
        self.assertEqual(response["recent_days_applied"], 2.0)
        self.assertIsNotNone(response["searched_from"])

    def test_search_emails_recent_days_zero_disables_window(self):
        """A0a: recent_days=0 must disable the auto-window — no `fromDate`
        machinery should appear in the generated script."""
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return ""

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            response = json.loads(
                _run(
                    search_tools.search_emails(
                        account="Work",
                        output_format="json",
                        limit=5,
                        recent_days=0,
                        allow_full_scan=True,
                    )
                )
            )

        self.assertNotIn("set year of fromDate to", captured["script"])
        self.assertEqual(response["recent_days_applied"], 0.0)
        self.assertIsNone(response["searched_from"])

    def test_search_emails_rejects_full_scan_without_opt_in(self):
        with patch("apple_mail_mcp.tools.search.run_applescript") as mock_run:
            result = _run(
                search_tools.search_emails(
                    account="Work",
                    output_format="json",
                    limit=5,
                    recent_days=0,
                )
            )

        payload = json.loads(result)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "full_scan_requires_opt_in")
        self.assertIn("allow_full_scan=True", payload["message"])
        mock_run.assert_not_called()

    def test_search_emails_explicit_date_from_overrides_default_window(self):
        """A0a: an explicit `date_from` overrides the 48h default — the script
        must encode the caller-supplied date, not today−2."""
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return ""

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            response = json.loads(
                _run(
                    search_tools.search_emails(
                        account="Work",
                        date_from="2026-01-01",
                        output_format="json",
                        limit=5,
                    )
                )
            )

        self.assertIn("set year of fromDate to 2026", captured["script"])
        self.assertIn("set month of fromDate to January", captured["script"])
        self.assertIn("set day of fromDate to 1", captured["script"])
        self.assertEqual(response["searched_from"], "2026-01-01")

    def test_search_emails_default_account_respected_when_env_set(self):
        """A0b: when DEFAULT_MAIL_ACCOUNT is set and the caller passes neither
        `account` nor `all_accounts=True`, the generated script must target
        that default account."""
        captured = {}

        def fake_run(script, timeout=120):
            captured.setdefault("scripts", []).append(script)
            return ""

        from apple_mail_mcp import server as _srv

        with patch.object(_srv, "DEFAULT_MAIL_ACCOUNT", "Work"):
            with patch(
                "apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run
            ):
                _run(
                    search_tools.search_emails(
                        subject_keyword="Test",
                        output_format="json",
                        limit=5,
                    )
                )

        # Single-account fast path: only one AppleScript call, targeting "Work".
        self.assertEqual(len(captured["scripts"]), 1)
        self.assertIn('set searchAccounts to {account "Work"}', captured["scripts"][0])
        self.assertNotIn("set acctNames to", captured["scripts"][0])

    def test_search_emails_all_accounts_overrides_default_account(self):
        """A0b: `all_accounts=True` must bypass the DEFAULT_MAIL_ACCOUNT
        fallback and trigger multi-account dispatch."""
        captured = {}

        def fake_run(script, timeout=120):
            captured.setdefault("scripts", []).append(script)
            if "set acctNames to" in script:
                return "Work\nPersonal"
            return ""

        from apple_mail_mcp import server as _srv

        with patch.object(_srv, "DEFAULT_MAIL_ACCOUNT", "Work"):
            with patch(
                "apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run
            ):
                _run(
                    search_tools.search_emails(
                        all_accounts=True,
                        subject_keyword="Test",
                        output_format="json",
                        limit=5,
                    )
                )

        # 1 account-listing probe + 2 per-account dispatches.
        self.assertEqual(len(captured["scripts"]), 3)
        per_account = captured["scripts"][1:]
        self.assertTrue(
            any('set searchAccounts to {account "Work"}' in s for s in per_account)
        )
        self.assertTrue(
            any('set searchAccounts to {account "Personal"}' in s for s in per_account)
        )

    def test_search_emails_parallel_dispatch_uses_to_thread(self):
        """A4b: per-account searches must be dispatched via asyncio.to_thread
        (one call per account) rather than serially inside one big script."""
        from unittest.mock import MagicMock

        scripts = []

        def fake_run(script, timeout=120):
            scripts.append(script)
            if "set acctNames to" in script:
                return "A\nB\nC"
            return ""

        with _clear_default_mail_account(), patch(
            "apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run
        ):
            with patch(
                "apple_mail_mcp.tools.search.asyncio.to_thread",
                wraps=asyncio.to_thread,
            ) as to_thread_spy:
                _run(
                    search_tools.search_emails(
                        account=None,
                        subject_keyword="X",
                        output_format="json",
                        limit=5,
                    )
                )

        # 1 list-accounts dispatch + 3 per-account dispatches
        self.assertGreaterEqual(to_thread_spy.call_count, 4)


class ListInboxEmailsTests(unittest.TestCase):
    def test_list_inbox_emails_caps_messages_in_applescript(self):
        """A1: text-format list_inbox_emails must bind `messages 1 thru N`
        rather than `every message` so large inboxes don't fully enumerate."""
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return ""

        with patch("apple_mail_mcp.tools.inbox.run_applescript", side_effect=fake_run):
            _run(inbox_tools.list_inbox_emails(account="Work", max_emails=10))

        self.assertIn("messages 1 thru 10 of inboxMailbox", captured["script"])
        self.assertNotIn("every message of inboxMailbox", captured["script"])

    def test_list_inbox_emails_unread_only_uses_whose(self):
        """A1: include_read=False must use `whose read status is false`
        instead of a Python-side filter on every message."""
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return ""

        with patch("apple_mail_mcp.tools.inbox.run_applescript", side_effect=fake_run):
            _run(
                inbox_tools.list_inbox_emails(
                    account="Work",
                    max_emails=10,
                    include_read=False,
                    output_format="json",
                )
            )

        self.assertIn("whose read status is false", captured["script"])

    def test_list_inbox_emails_timeout_is_forwarded(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["timeout"] = timeout
            return ""

        with patch("apple_mail_mcp.tools.inbox.run_applescript", side_effect=fake_run):
            _run(inbox_tools.list_inbox_emails(account="Work", max_emails=5, timeout=240))

        self.assertEqual(captured["timeout"], 240)

    def test_list_inbox_emails_default_max_emails_is_50(self):
        """A0a: list_inbox_emails defaults max_emails to 50, which must be
        baked into the AppleScript via `messages 1 thru 50`."""
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return ""

        with patch("apple_mail_mcp.tools.inbox.run_applescript", side_effect=fake_run):
            _run(inbox_tools.list_inbox_emails(account="Work"))

        self.assertIn("messages 1 thru 50 of inboxMailbox", captured["script"])

    def test_list_inbox_emails_partial_results_on_account_timeout(self):
        """A4: when one account's AppleScript times out, list_inbox_emails
        (JSON path) must still return other accounts' data + an `errors`
        list."""

        def fake_run(script, timeout=120):
            if "set acctNames to" in script:
                return "Work\nTU"
            if 'account "TU"' in script:
                raise AppleScriptTimeout("TU timed out")
            return "Hello|||sender@example.com|||today|||false|||Work"

        with _clear_default_mail_account(), patch(
            "apple_mail_mcp.tools.inbox.run_applescript", side_effect=fake_run
        ):
            raw = _run(inbox_tools.list_inbox_emails(output_format="json", max_emails=5))

        payload = json.loads(raw)
        self.assertIn("emails", payload)
        self.assertIn("errors", payload)
        self.assertEqual(payload["errors"], ["TU"])
        self.assertEqual(len(payload["emails"]), 1)
        self.assertEqual(payload["emails"][0]["account"], "Work")


class ManageToolTests(unittest.TestCase):
    def test_move_email_dry_run_uses_search_helper(self):
        with patch(
            "apple_mail_mcp.tools.manage._search_mail_records",
            return_value=[
                {
                    "subject": "Ticket",
                    "sender": "sender@example.com",
                    "received_date": "2026-03-07T10:00:00",
                }
            ],
        ) as mock_search, patch(
            "apple_mail_mcp.tools.manage.run_applescript"
        ) as mock_run:
            result = manage_tools.move_email(
                account="Work",
                to_mailbox="Archive",
                subject_keyword="Ticket",
                dry_run=True,
                max_moves=1,
            )

        mock_search.assert_called_once()
        mock_run.assert_not_called()
        self.assertIn("DRY RUN - PREVIEW MOVE", result)
        self.assertIn("Would move: Ticket", result)

    def test_manage_trash_dry_run_uses_search_helper(self):
        with patch(
            "apple_mail_mcp.tools.manage._search_mail_records",
            return_value=[],
        ) as mock_search, patch(
            "apple_mail_mcp.tools.manage.run_applescript"
        ) as mock_run:
            result = manage_tools.manage_trash(
                account="Work",
                action="move_to_trash",
                subject_keyword="Ticket",
                dry_run=True,
                max_deletes=1,
            )

        mock_search.assert_called_once()
        mock_run.assert_not_called()
        self.assertIn("DRY RUN - PREVIEW TRASH", result)
        self.assertIn("TOTAL: 0", result)

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


class GetEmailThreadTests(unittest.TestCase):
    """Phase 2 scan-path hardening for get_email_thread."""

    def test_get_email_thread_default_emits_whose_date_filter_and_cap(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            captured["timeout"] = timeout
            return "EMAIL THREAD VIEW"

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            result = search_tools.get_email_thread(
                account="Work",
                subject_keyword="Project Update",
                max_messages=25,
            )

        script = captured["script"]
        self.assertIn("EMAIL THREAD VIEW", result)
        self.assertIn("set cutoffDate to current date", script)
        self.assertIn("messageDate < cutoffDate", script)
        self.assertIn("set scanUpperBound to 25", script)
        self.assertIn("messages 1 thru scanUpperBound of currentMailbox", script)
        self.assertIn("ignoring case", script)
        self.assertIn("Window: last 48h", script)
        self.assertEqual(captured["timeout"], 120)

    def test_get_email_thread_recent_days_zero_uses_messages_cap(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return "ok"

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            result = search_tools.get_email_thread(
                account="Work",
                subject_keyword="Budget",
                max_messages=10,
                recent_days=0,
            )

        self.assertIn("allow_full_scan=True", result)
        self.assertNotIn("script", captured)

    def test_get_email_thread_recent_days_zero_allows_explicit_full_scan(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return "ok"

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            search_tools.get_email_thread(
                account="Work",
                subject_keyword="Budget",
                max_messages=10,
                recent_days=0,
                allow_full_scan=True,
            )

        script = captured["script"]
        self.assertNotIn("cutoffDate", script)
        self.assertNotIn("messageDate < cutoffDate", script)
        self.assertIn("set scanUpperBound to 10", script)
        self.assertIn("messages 1 thru scanUpperBound of currentMailbox", script)
        self.assertIn("Window: full inbox", script)

    def test_get_email_thread_no_bare_every_message_enumeration(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["script"] = script
            return "ok"

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            search_tools.get_email_thread(
                account="Work",
                subject_keyword="Standup",
                max_messages=5,
            )

        script = captured["script"]
        self.assertNotIn("set mailboxMessages to every message of currentMailbox", script)
        self.assertNotIn("repeat with aMessage in mailboxMessages", script)

    def test_get_email_thread_passes_custom_timeout(self):
        captured = {}

        def fake_run(script, timeout=120):
            captured["timeout"] = timeout
            return "ok"

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            search_tools.get_email_thread(
                account="Work",
                subject_keyword="Invoice",
                timeout=300,
            )

        self.assertEqual(captured["timeout"], 300)

    def test_get_email_thread_handles_timeout(self):
        def fake_run(script, timeout=120):
            raise AppleScriptTimeout("simulated")

        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=fake_run):
            result = search_tools.get_email_thread(
                account="Work",
                subject_keyword="Invoice",
                timeout=90,
            )

        self.assertIn("timed out", result.lower())
        self.assertIn("Work", result)
        self.assertIn("90", result)

    def test_get_email_thread_rejects_invalid_max_messages(self):
        result = search_tools.get_email_thread(
            account="Work",
            subject_keyword="Invoice",
            max_messages=0,
        )
        self.assertIn("max_messages must be > 0", result)


if __name__ == "__main__":
    unittest.main()

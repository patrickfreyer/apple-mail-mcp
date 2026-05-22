"""Focused tests for the 3.1.5 modernization pass.

Covers the four tool modules updated in parallel:

- ``smart_inbox`` (``get_awaiting_reply``, ``get_needs_response``,
  ``get_top_senders``)
- ``manage`` (``move_email``, ``update_email_status``, ``manage_trash``,
  ``create_mailbox``, etc.)
- ``analytics`` (``list_email_attachments``, ``get_statistics``,
  ``export_emails``)
- ``compose`` (``compose_email``, ``reply_to_email``, ``forward_email``,
  ``manage_drafts``)

Each modernized tool now:

1. Defaults ``account=None`` and falls back to
   ``apple_mail_mcp.server.DEFAULT_MAIL_ACCOUNT``.
2. Generates AppleScript with ``whose`` clauses + ``items 1 thru N`` caps
   so large mailboxes never fully materialize.
3. Accepts a ``timeout`` kwarg and catches ``AppleScriptTimeout`` from
   ``run_applescript``, returning a structured error string.

These tests mock ``subprocess.run`` / ``run_applescript`` to assert the
captured AppleScript matches the new patterns and that the resolution +
error paths behave as documented.
"""

import subprocess
import unittest
from unittest.mock import patch

from apple_mail_mcp import server as _server
from apple_mail_mcp.core import AppleScriptTimeout
from apple_mail_mcp.tools import analytics as analytics_tools
from apple_mail_mcp.tools import compose as compose_tools
from apple_mail_mcp.tools import manage as manage_tools
from apple_mail_mcp.tools import smart_inbox as smart_inbox_tools


class _ScriptCapture:
    """Reusable side_effect helper that records each AppleScript invocation
    and lets the test specify a return value.

    ``return_value`` may be a string or a list; if a list, each call pops
    the next entry.
    """

    def __init__(self, return_value=""):
        self.scripts = []
        self.timeouts = []
        self._return_value = return_value

    def __call__(self, script, timeout=120):
        self.scripts.append(script)
        self.timeouts.append(timeout)
        if isinstance(self._return_value, list):
            if self._return_value:
                return self._return_value.pop(0)
            return ""
        return self._return_value

    @property
    def last_script(self):
        return self.scripts[-1] if self.scripts else ""


class DefaultAccountFallbackTests(unittest.TestCase):
    """Group A: every modernized tool must fall back to
    ``DEFAULT_MAIL_ACCOUNT`` when ``account`` is omitted."""

    ACCOUNT = "TestAcct"

    def setUp(self):
        self._patcher = patch.object(_server, "DEFAULT_MAIL_ACCOUNT", self.ACCOUNT)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    # --- smart_inbox ---

    def test_get_awaiting_reply_uses_default_account(self):
        cap = _ScriptCapture(return_value="ok")
        with patch(
            "apple_mail_mcp.tools.smart_inbox.run_applescript", side_effect=cap
        ):
            result = smart_inbox_tools.get_awaiting_reply(days_back=1, max_results=1)
        self.assertNotIn("No account specified", result)
        self.assertIn(f'account "{self.ACCOUNT}"', cap.last_script)

    def test_get_needs_response_uses_default_account(self):
        cap = _ScriptCapture(return_value="ok")
        with patch(
            "apple_mail_mcp.tools.smart_inbox.run_applescript", side_effect=cap
        ):
            result = smart_inbox_tools.get_needs_response(days_back=1, max_results=1)
        self.assertNotIn("No account specified", result)
        self.assertIn(f'account "{self.ACCOUNT}"', cap.last_script)

    def test_get_top_senders_uses_default_account(self):
        # AppleScript returns the aggregation payload; tool sorts in Python.
        cap = _ScriptCapture(
            return_value="TOTAL|||0\nUNIQUE|||0"
        )
        with patch(
            "apple_mail_mcp.tools.smart_inbox.run_applescript", side_effect=cap
        ):
            result = smart_inbox_tools.get_top_senders(days_back=1, top_n=3)
        self.assertNotIn("No account specified", result)
        self.assertIn(f'account "{self.ACCOUNT}"', cap.last_script)

    # --- manage ---

    def test_move_email_uses_default_account(self):
        # move_email dry-run now delegates to the search helper, so we capture
        # the script at search.run_applescript (the underlying invocation).
        cap = _ScriptCapture(return_value="ok")
        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=cap):
            result = manage_tools.move_email(
                to_mailbox="Archive",
                subject_keyword="Promo",
                max_moves=1,
                dry_run=True,
            )
        self.assertNotIn("DEFAULT_MAIL_ACCOUNT", result)
        self.assertIn(f'account "{self.ACCOUNT}"', cap.last_script)

    def test_update_email_status_uses_default_account(self):
        cap = _ScriptCapture(return_value="ok")
        with patch("apple_mail_mcp.tools.manage.run_applescript", side_effect=cap):
            result = manage_tools.update_email_status(
                action="mark_read",
                message_ids=["42"],
            )
        self.assertNotIn("DEFAULT_MAIL_ACCOUNT", result)
        self.assertIn(f'account "{self.ACCOUNT}"', cap.last_script)

    def test_manage_trash_uses_default_account(self):
        # manage_trash dry-run now delegates to the search helper.
        cap = _ScriptCapture(return_value="ok")
        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=cap):
            result = manage_tools.manage_trash(
                action="move_to_trash",
                subject_keyword="Promo",
                max_deletes=1,
                dry_run=True,
            )
        self.assertNotIn("DEFAULT_MAIL_ACCOUNT", result)
        self.assertIn(f'account "{self.ACCOUNT}"', cap.last_script)

    def test_create_mailbox_uses_default_account(self):
        cap = _ScriptCapture(return_value="ok")
        with patch("apple_mail_mcp.tools.manage.run_applescript", side_effect=cap):
            result = manage_tools.create_mailbox(name="ScratchFolder")
        self.assertNotIn("DEFAULT_MAIL_ACCOUNT", result)
        self.assertIn(f'account "{self.ACCOUNT}"', cap.last_script)

    # --- analytics ---

    def test_list_email_attachments_uses_default_account(self):
        # list_email_attachments now runs a preflight via the search helper
        # before invoking analytics.run_applescript. Patch both so the
        # preflight returns a hit and we capture the analytics-side script.
        cap = _ScriptCapture(return_value="ok")
        with patch(
            "apple_mail_mcp.tools.analytics._search_mail_records",
            return_value=[{"subject": "Invoice"}],
        ), patch(
            "apple_mail_mcp.tools.analytics.run_applescript", side_effect=cap
        ):
            result = analytics_tools.list_email_attachments(
                subject_keyword="Invoice", max_results=5
            )
        self.assertNotIn("DEFAULT_MAIL_ACCOUNT", result)
        self.assertIn(f'account "{self.ACCOUNT}"', cap.last_script)

    def test_get_statistics_uses_default_account(self):
        cap = _ScriptCapture(return_value="ok")
        with patch(
            "apple_mail_mcp.tools.analytics.run_applescript", side_effect=cap
        ):
            result = analytics_tools.get_statistics(
                scope="account_overview", days_back=1
            )
        self.assertNotIn("DEFAULT_MAIL_ACCOUNT", result)
        self.assertIn(f'account "{self.ACCOUNT}"', cap.last_script)

    def test_export_emails_uses_default_account(self):
        cap = _ScriptCapture(return_value="ok")
        with patch(
            "apple_mail_mcp.tools.analytics.run_applescript", side_effect=cap
        ):
            result = analytics_tools.export_emails(
                scope="entire_mailbox", max_emails=1
            )
        self.assertNotIn("DEFAULT_MAIL_ACCOUNT", result)
        self.assertIn(f'account "{self.ACCOUNT}"', cap.last_script)

    # --- compose ---
    #
    # compose_email, reply_to_email, forward_email, and manage_drafts route
    # through run_applescript (including AppleScriptObjC use-framework paths).
    # We assert resolution via the script that DOES get captured.

    def test_compose_email_uses_default_account(self):
        cap = _ScriptCapture(return_value="ok")
        with patch("apple_mail_mcp.tools.compose.run_applescript", side_effect=cap):
            result = compose_tools.compose_email(
                to="someone@example.com",
                subject="Hi",
                body="Body",
                mode="draft",
            )
        self.assertNotIn("No account specified", result)
        # _validate_from_address is skipped when from_address is None, so the
        # captured script is the compose script itself.
        self.assertIn(f'account "{self.ACCOUNT}"', cap.last_script)

    def test_reply_to_email_uses_default_account(self):
        cap = _ScriptCapture(return_value="Reply sent successfully!")
        with patch("apple_mail_mcp.tools.compose.run_applescript", side_effect=cap):
            result = compose_tools.reply_to_email(
                subject_keyword="Foo",
                reply_body="hi",
            )
        self.assertNotIn("No account specified", result)
        self.assertIn(f'account "{self.ACCOUNT}"', cap.last_script)

    def test_forward_email_uses_default_account(self):
        # No `message` arg -> goes through run_applescript path.
        cap = _ScriptCapture(return_value="ok")
        with patch("apple_mail_mcp.tools.compose.run_applescript", side_effect=cap):
            result = compose_tools.forward_email(
                subject_keyword="Foo",
                to="other@example.com",
            )
        self.assertNotIn("No account specified", result)
        self.assertIn(f'account "{self.ACCOUNT}"', cap.last_script)

    def test_manage_drafts_uses_default_account(self):
        # action='list' is the simplest path; smoke-test resolution there.
        cap = _ScriptCapture(return_value="ok")
        with patch("apple_mail_mcp.tools.compose.run_applescript", side_effect=cap):
            result = compose_tools.manage_drafts(action="list")
        self.assertNotIn("No account specified", result)
        self.assertIn(f'account "{self.ACCOUNT}"', cap.last_script)


class WhoseAndCapTests(unittest.TestCase):
    """Group B: spot-check that whose+cap pattern reaches AppleScript in
    each modernized module."""

    def test_smart_inbox_get_awaiting_reply_emits_whose_and_cap(self):
        cap = _ScriptCapture(return_value="ok")
        with patch(
            "apple_mail_mcp.tools.smart_inbox.run_applescript", side_effect=cap
        ):
            smart_inbox_tools.get_awaiting_reply(
                account="X", days_back=7, max_results=5
            )
        script = cap.last_script
        self.assertIn("whose", script)
        self.assertIn("items 1 thru", script)

    def test_manage_move_email_emits_whose_and_cap(self):
        # Dry-run move_email delegates to the search helper; capture the
        # script there. The search helper builds the same whose+cap shape.
        cap = _ScriptCapture(return_value="ok")
        with patch("apple_mail_mcp.tools.search.run_applescript", side_effect=cap):
            manage_tools.move_email(
                account="X",
                to_mailbox="Archive",
                subject_keywords=["test"],
                max_moves=5,
                dry_run=True,
            )
        script = cap.last_script
        self.assertIn("whose", script)
        # Search helper applies a script-side cap derived from
        # limit=max_moves+1=6 (plus its own offset/collectLimit overhead).
        # Just verify a cap appears.
        self.assertRegex(script, r"items 1 thru \d+")

    def test_analytics_get_statistics_uses_documented_caps(self):
        cap = _ScriptCapture(return_value="ok")
        with patch(
            "apple_mail_mcp.tools.analytics.run_applescript", side_effect=cap
        ):
            analytics_tools.get_statistics(
                account="X", scope="account_overview", days_back=30
            )
        script = cap.last_script
        # 20-mailbox cap and 500-message-per-mailbox cap are the documented
        # ceilings; both must appear verbatim in the generated AppleScript.
        self.assertIn("1 thru 20", script)
        self.assertIn("1 thru 500", script)


class NoAccountErrorTests(unittest.TestCase):
    """Group C: when DEFAULT_MAIL_ACCOUNT is unset and the caller omits
    `account`, the tool must surface a clear error rather than dispatching
    AppleScript against an empty account name."""

    def test_smart_inbox_without_account_errors(self):
        with patch.object(_server, "DEFAULT_MAIL_ACCOUNT", None):
            # run_applescript should NOT be called when resolution fails.
            with patch(
                "apple_mail_mcp.tools.smart_inbox.run_applescript"
            ) as mock_run:
                result = smart_inbox_tools.get_awaiting_reply(days_back=1)
                mock_run.assert_not_called()
        # Implementation wording: "Error: No account specified and ..."
        self.assertTrue(
            result.startswith("Error") or result.startswith("ERROR"),
            f"Expected an error prefix, got: {result!r}",
        )
        self.assertIn("No account", result)


class AppleScriptTimeoutHandlingTests(unittest.TestCase):
    """Group D: each modernized file must catch ``AppleScriptTimeout`` and
    return a structured "timed out" string rather than re-raising."""

    def _timeout(self, *args, **kwargs):
        raise AppleScriptTimeout("simulated timeout")

    def test_smart_inbox_get_awaiting_reply_handles_timeout(self):
        with patch(
            "apple_mail_mcp.tools.smart_inbox.run_applescript",
            side_effect=self._timeout,
        ):
            result = smart_inbox_tools.get_awaiting_reply(
                account="X", days_back=1, max_results=1
            )
        self.assertIn("timed out", result.lower())

    def test_manage_move_email_handles_timeout(self):
        # In dry-run, move_email routes through the search helper. Patch
        # search.run_applescript so the preflight times out; move_email must
        # still return a structured "timed out" message rather than empty.
        with patch(
            "apple_mail_mcp.tools.search.run_applescript",
            side_effect=self._timeout,
        ):
            result = manage_tools.move_email(
                account="X",
                to_mailbox="Archive",
                subject_keyword="Promo",
                max_moves=1,
                dry_run=True,
            )
        self.assertIn("timed out", result.lower())

    def test_analytics_list_attachments_handles_timeout(self):
        # list_email_attachments preflight goes through the search helper.
        # Patch search.run_applescript so the preflight times out — the tool
        # must surface this as a structured "timed out" error.
        with patch(
            "apple_mail_mcp.tools.search.run_applescript",
            side_effect=self._timeout,
        ):
            result = analytics_tools.list_email_attachments(
                account="X", subject_keyword="Invoice"
            )
        self.assertIn("timed out", result.lower())

    def test_compose_manage_drafts_handles_timeout(self):
        with patch(
            "apple_mail_mcp.tools.compose.run_applescript",
            side_effect=self._timeout,
        ):
            result = compose_tools.manage_drafts(account="X", action="list")
        self.assertIn("timed out", result.lower())


if __name__ == "__main__":
    unittest.main()

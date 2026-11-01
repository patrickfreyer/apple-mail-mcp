"""Mailbox lookup regressions shared by search and thread collection."""

import unittest
from unittest.mock import patch

from apple_mail_mcp.tools import search


class SearchMailboxTests(unittest.TestCase):
    def _script(self, tool, mailbox):
        with patch.object(search, "run_applescript", return_value="") as run:
            if tool == "search":
                search.search_emails(account="Work", mailbox=mailbox, limit=1)
            else:
                search.get_email_thread(
                    account="Work", mailbox=mailbox, subject_keyword="Topic"
                )
        return run.call_args.args[0]

    def test_default_inbox_tries_localized_names_in_both_tools(self):
        for tool in ("search", "thread"):
            with self.subTest(tool=tool):
                script = self._script(tool, "INBOX")
                self.assertIn('"Boîte de réception"', script)
                self.assertIn('"Posteingang"', script)
                self.assertIn("no localized inbox match", script)

    def test_nested_mailbox_is_resolved_as_parent_and_child(self):
        for tool in ("search", "thread"):
            with self.subTest(tool=tool):
                script = self._script(tool, "Archives/2026")
                self.assertIn(
                    'mailbox "2026" of mailbox "Archives" of targetAccount', script
                )
                self.assertNotIn('mailbox "Archives/2026" of targetAccount', script)

    def test_plain_mailbox_keeps_direct_lookup(self):
        for tool in ("search", "thread"):
            with self.subTest(tool=tool):
                self.assertIn(
                    'mailbox "Archive" of targetAccount', self._script(tool, "Archive")
                )

    def test_all_mailboxes_keeps_account_wide_lookup(self):
        for tool in ("search", "thread"):
            with self.subTest(tool=tool):
                script = self._script(tool, "All")
                self.assertIn("set searchMailboxes to every mailbox of targetAccount", script)
                self.assertNotIn('mailbox "All" of targetAccount', script)

    def test_nested_names_are_escaped_by_the_shared_helper(self):
        for tool in ("search", "thread"):
            with self.subTest(tool=tool):
                script = self._script(tool, 'Archives/Team "A"')
                self.assertIn('mailbox "Team \\"A\\"" of mailbox "Archives"', script)

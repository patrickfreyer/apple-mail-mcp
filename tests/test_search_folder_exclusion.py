"""System mailbox exclusions must compare names, not repeat references."""

import shutil
import subprocess
import unittest
from unittest.mock import patch

from apple_mail_mcp.tools import search


class SearchFolderExclusionTests(unittest.TestCase):
    def _skip_block(self):
        with patch.object(search, "run_applescript", return_value="") as run:
            search.search_emails(account="Work", mailbox="All", limit=1)
        script = run.call_args.args[0]
        start = script.index("set skipFolders to")
        end = script.index("if not shouldSkip then", start)
        return script[start:end]

    def test_repeat_reference_is_dereferenced_before_comparison(self):
        block = self._skip_block()
        self.assertIn("mailboxName is (contents of skipFolder)", block)
        self.assertNotIn("mailboxName is skipFolder then", block)

    @unittest.skipUnless(shutil.which("osascript"), "requires AppleScript")
    def test_native_comparison_skips_system_folders_and_keeps_regular_mail(self):
        block = self._skip_block()
        for mailbox, expected in (
            ("Trash", "true"),
            ("Drafts", "true"),
            ("Junk Email", "true"),
            ("Sent Messages", "true"),
            ("trash", "true"),
            ("INBOX", "false"),
            ("Archive", "false"),
            ("Trash receipts", "false"),
        ):
            with self.subTest(mailbox=mailbox):
                script = (
                    f'set mailboxName to "{mailbox}"\n'
                    "set shouldSkip to false\n" + block + "\nreturn shouldSkip"
                )
                result = subprocess.run(
                    ["osascript", "-"], input=script, text=True,
                    capture_output=True, check=True, timeout=10,
                )
                self.assertEqual(result.stdout.strip(), expected)

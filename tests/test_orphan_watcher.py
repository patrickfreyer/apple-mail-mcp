"""Tests for the orphan watcher in __main__."""

import time
import unittest

from apple_mail_mcp.__main__ import _start_orphan_watcher


class OrphanWatcherTests(unittest.TestCase):
    def test_exits_when_ppid_changes(self):
        """Watcher calls exit_fn when the PPID differs from the initial one."""
        exits = []
        ppids = iter([100, 100, 1])  # two checks with live parent, then orphaned
        _start_orphan_watcher(
            interval_sec=0.01,
            get_ppid=lambda: next(ppids),
            exit_fn=lambda code: exits.append(code),
        )
        # Allow the daemon thread time to run through all three ticks
        time.sleep(0.1)
        self.assertEqual(exits, [0])

    def test_does_not_exit_while_parent_alive(self):
        """Watcher does not call exit_fn while PPID remains unchanged."""
        exits = []
        _start_orphan_watcher(
            interval_sec=0.01,
            get_ppid=lambda: 100,
            exit_fn=lambda code: exits.append(code),
        )
        time.sleep(0.05)
        self.assertEqual(exits, [])


if __name__ == "__main__":
    unittest.main()

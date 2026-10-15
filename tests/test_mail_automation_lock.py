"""Tests for the cross-process AppleScript serialization lock in core.py.

Uses a real (but per-test, throwaway) lockfile path and real flock() calls —
patching flock itself would defeat the point of the test. flock is POSIX,
not macOS-specific, so these run in CI on Linux with no Mail.app, matching
the existing convention in test_core_applescript.py.
"""

import os
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch


class FakePopen:
    """Minimal fake that mimics subprocess.Popen, mirroring the one in
    test_core_applescript.py (duplicated rather than cross-imported to keep
    test modules independent)."""

    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.killed = False
        self.stdin = MagicMock()

    def communicate(self, input=None, timeout=None):
        return (self._stdout, self._stderr)

    def kill(self):
        self.killed = True

    def wait(self):
        pass


class MailAutomationLockTestCase(unittest.TestCase):
    """Shared setUp/tearDown: point core._LOCK_PATH at a throwaway tmp file."""

    def setUp(self):
        from apple_mail_mcp import core
        self._core = core
        self._tmpdir = tempfile.mkdtemp()
        self._lock_path = os.path.join(self._tmpdir, "test.lock")
        self._patcher = patch.object(core, "_LOCK_PATH", self._lock_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        shutil.rmtree(self._tmpdir, ignore_errors=True)


class TestMailAutomationLock(MailAutomationLockTestCase):
    """Tests for mail_automation_lock in isolation."""

    def test_acquires_and_releases_cleanly(self):
        """A single caller can acquire and release without error."""
        with self._core.mail_automation_lock(timeout=5):
            pass

    def test_creates_lock_directory_if_missing(self):
        """The lock's parent directory is created if it doesn't exist yet."""
        nested = os.path.join(self._tmpdir, "nested", "dir", "test.lock")
        with patch.object(self._core, "_LOCK_PATH", nested):
            with self._core.mail_automation_lock(timeout=5):
                pass
        self.assertTrue(os.path.exists(nested))

    def test_second_caller_blocks_until_first_releases(self):
        """A second acquisition waits for the first to release rather than
        failing immediately or racing past it."""
        holder_has_lock = threading.Event()
        release_holder = threading.Event()
        waiter_wait_time = []

        def _holder():
            with self._core.mail_automation_lock(timeout=5):
                holder_has_lock.set()
                release_holder.wait(timeout=2.0)

        def _waiter():
            holder_has_lock.wait(timeout=2.0)
            start = time.monotonic()
            with self._core.mail_automation_lock(timeout=5):
                waiter_wait_time.append(time.monotonic() - start)

        t1 = threading.Thread(target=_holder)
        t1.start()
        self.assertTrue(
            holder_has_lock.wait(timeout=2.0), "holder never acquired the lock"
        )

        t2 = threading.Thread(target=_waiter)
        t2.start()
        # Give the waiter a moment to actually be blocked on flock before releasing.
        time.sleep(0.3)
        release_holder.set()
        t1.join(timeout=2.0)
        t2.join(timeout=2.0)

        self.assertEqual(len(waiter_wait_time), 1, "waiter never acquired the lock")
        self.assertGreaterEqual(
            waiter_wait_time[0],
            0.25,
            "waiter acquired suspiciously fast — lock may not be exclusive",
        )

    def test_raises_timeout_error_when_held_too_long(self):
        """Waiting past *timeout* raises TimeoutError instead of blocking forever."""
        holder_has_lock = threading.Event()
        release_holder = threading.Event()

        def _holder():
            with self._core.mail_automation_lock(timeout=5):
                holder_has_lock.set()
                release_holder.wait(timeout=2.0)

        t1 = threading.Thread(target=_holder)
        t1.start()
        self.assertTrue(holder_has_lock.wait(timeout=2.0))

        with self.assertRaises(TimeoutError):
            with self._core.mail_automation_lock(timeout=0.3):
                pass  # pragma: no cover — should never be reached

        release_holder.set()
        t1.join(timeout=2.0)

    def test_lock_released_on_exception_inside_with_block(self):
        """The lock is released even if the protected code raises."""
        with self.assertRaises(ValueError):
            with self._core.mail_automation_lock(timeout=5):
                raise ValueError("boom")

        # If the lock leaked, this would time out instead of succeeding immediately.
        acquired = []

        def _try_again():
            with self._core.mail_automation_lock(timeout=2):
                acquired.append(True)

        t = threading.Thread(target=_try_again)
        t.start()
        t.join(timeout=2.0)
        self.assertEqual(acquired, [True], "lock was not released after an exception")


class TestRunApplescriptHoldsLock(MailAutomationLockTestCase):
    """Integration: run_applescript actually serializes through the lock."""

    def test_concurrent_run_applescript_calls_do_not_overlap(self):
        """Multiple threads calling run_applescript never have two
        communicate() calls in flight at the same time."""
        overlap_detected = [False]
        active_count = [0]
        counter_lock = threading.Lock()

        class TrackingPopen(FakePopen):
            def communicate(self, input=None, timeout=None):
                with counter_lock:
                    active_count[0] += 1
                    if active_count[0] > 1:
                        overlap_detected[0] = True
                time.sleep(0.2)
                with counter_lock:
                    active_count[0] -= 1
                return (b"ok", b"")

        def _run():
            self._core.run_applescript('display dialog "hi"', timeout=5)

        with patch.object(
            self._core, "_popen_factory", side_effect=lambda *a, **kw: TrackingPopen()
        ):
            threads = [threading.Thread(target=_run) for _ in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)

        self.assertFalse(
            overlap_detected[0],
            "more than one run_applescript call was inside communicate() at once",
        )


class TestLockWaitIsIndependentOfAppleScriptTimeout(MailAutomationLockTestCase):
    """The lock wait uses its own short bound, not the AppleScript timeout."""

    def test_lock_wait_constant_is_short(self):
        self.assertLessEqual(self._core.LOCK_WAIT_SECONDS, 60)

    def test_default_lock_timeout_is_lock_wait_seconds(self):
        import inspect

        default = inspect.signature(
            self._core.mail_automation_lock
        ).parameters["timeout"].default
        self.assertEqual(default, self._core.LOCK_WAIT_SECONDS)

    def test_run_applescript_waits_lock_wait_seconds_not_script_timeout(self):
        seen = []
        real_lock = self._core.mail_automation_lock

        def spy_lock(timeout=self._core.LOCK_WAIT_SECONDS):
            seen.append(timeout)
            return real_lock(timeout=timeout)

        with (
            patch.object(self._core, "mail_automation_lock", side_effect=spy_lock),
            patch.object(
                self._core,
                "_popen_factory",
                side_effect=lambda *a, **kw: FakePopen(stdout=b"ok"),
            ),
        ):
            self._core.run_applescript('return "ok"', timeout=240)

        self.assertEqual(seen, [self._core.LOCK_WAIT_SECONDS])


class TestComposeToolsReportBusyLock(unittest.TestCase):
    """Direct-osascript compose paths turn a lock TimeoutError into a clean error."""

    def _busy_lock(self, *args, **kwargs):
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            raise TimeoutError("Mail automation is busy (lock held) after 30s")
            yield  # pragma: no cover

        return _cm()

    def _patches(self):
        return (
            patch(
                "apple_mail_mcp.tools.compose.mail_automation_lock",
                side_effect=self._busy_lock,
            ),
            patch(
                "apple_mail_mcp.tools.compose.run_applescript",
                return_value="a@b.com",
            ),
            patch("apple_mail_mcp.tools.compose.subprocess.run"),
        )

    def _assert_busy(self, result, mock_run):
        mock_run.assert_not_called()
        self.assertTrue(
            result.startswith("Error: Mail automation is busy"), result
        )

    def test_send_html_email_reports_busy(self):
        from apple_mail_mcp.tools import compose as compose_tools

        p1, p2, p3 = self._patches()
        with p1, p2, p3 as mock_run:
            result = compose_tools.compose_email(
                account="Work",
                to="x@example.com",
                subject="s",
                body="Body",
                body_html="<p>Body</p>",
                mode="send",
            )
        self._assert_busy(result, mock_run)

    def test_reply_to_email_reports_busy(self):
        from apple_mail_mcp.tools import compose as compose_tools

        p1, p2, p3 = self._patches()
        with p1, p2, p3 as mock_run:
            result = compose_tools.reply_to_email(
                account="Work",
                subject_keyword="test",
                reply_body="Reply",
                send=False,
            )
        self._assert_busy(result, mock_run)

    def test_forward_email_reports_busy(self):
        from apple_mail_mcp.tools import compose as compose_tools

        p1, p2, p3 = self._patches()
        with p1, p2, p3 as mock_run:
            result = compose_tools.forward_email(
                account="Work",
                subject_keyword="test",
                to="x@example.com",
                message="FYI",
            )
        self._assert_busy(result, mock_run)


if __name__ == "__main__":
    unittest.main()

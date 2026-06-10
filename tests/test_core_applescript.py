"""Tests for AppleScript timeout injection and in-flight child tracking in core.py.

Uses dependency injection (Popen factory + module-level registry) rather than
calling real osascript, so these tests run in CI on Linux with no Mail.app.
"""

import subprocess
import threading
import time
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# _apply_applescript_timeout
# ---------------------------------------------------------------------------


class TestApplyApplescriptTimeout(unittest.TestCase):
    """Tests for the _apply_applescript_timeout helper."""

    def setUp(self):
        # Import here so module-level side-effects (signal handlers) run inside
        # the test process only once and predictably.
        from apple_mail_mcp.core import _apply_applescript_timeout
        self._fn = _apply_applescript_timeout

    def test_wraps_normal_script(self):
        """Normal script is wrapped in 'with timeout of <inner> seconds'."""
        script = 'tell application "Mail"\n    get subject of first message\nend tell'
        result = self._fn(script, timeout=120)
        self.assertTrue(
            result.startswith("with timeout of "),
            msg=f"Expected 'with timeout of ...' at start; got:\n{result}",
        )
        self.assertIn("end timeout", result)
        self.assertIn(script, result)

    def test_inner_is_timeout_minus_five(self):
        """Inner timeout value is max(timeout-5, 5)."""
        from apple_mail_mcp.core import _apply_applescript_timeout
        script = 'display dialog "hello"'
        result = _apply_applescript_timeout(script, timeout=120)
        # inner should be 115
        self.assertIn("with timeout of 115 seconds", result)

    def test_inner_floor_is_five(self):
        """Inner timeout is floored at 5 even when Python timeout is very small."""
        from apple_mail_mcp.core import _apply_applescript_timeout
        script = 'display dialog "hello"'
        # timeout=7 -> inner = max(2, 5) = 5
        result = _apply_applescript_timeout(script, timeout=7)
        self.assertIn("with timeout of 5 seconds", result)

    def test_leaves_use_script_unchanged(self):
        """Scripts with a top-level 'use' declaration are returned as-is."""
        from apple_mail_mcp.core import _apply_applescript_timeout
        script = (
            "use framework \"Foundation\"\n"
            "use scripting additions\n"
            'set x to current application\n'
        )
        result = _apply_applescript_timeout(script, timeout=120)
        self.assertEqual(result, script)

    def test_indented_use_line_also_skipped(self):
        """A 'use' line with leading whitespace is also detected and skipped."""
        from apple_mail_mcp.core import _apply_applescript_timeout
        script = '    use framework "AppKit"\nset x to 1'
        result = _apply_applescript_timeout(script, timeout=120)
        self.assertEqual(result, script)

    def test_use_inside_handler_not_mistaken(self):
        """A word 'use' that is NOT a line-leading directive is wrapped normally."""
        from apple_mail_mcp.core import _apply_applescript_timeout
        # 'use' appears inside a string, not as the first token of any line
        script = 'set x to "I use Mail a lot"\ntell application "Mail"\nend tell'
        result = _apply_applescript_timeout(script, timeout=120)
        self.assertIn("with timeout of", result)
        self.assertIn("end timeout", result)


# ---------------------------------------------------------------------------
# In-flight children registry
# ---------------------------------------------------------------------------


class FakePopen:
    """Minimal fake that mimics subprocess.Popen for registry tests."""

    def __init__(self, returncode=0, stdout=b"", stderr=b"", delay=0.0):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._delay = delay
        self.killed = False
        self.stdin = MagicMock()
        self.stdin.write = MagicMock()
        self.stdin.close = MagicMock()

    def communicate(self, input=None, timeout=None):
        if self._delay:
            time.sleep(self._delay)
        return (self._stdout, self._stderr)

    def kill(self):
        self.killed = True

    def wait(self):
        pass


class TestInflightRegistry(unittest.TestCase):
    """Tests for in-flight Popen tracking inside run_applescript."""

    def _run_with_fake_popen(self, fake_proc, timeout=120):
        """
        Invoke run_applescript with a factory that always returns *fake_proc*.

        We patch core._popen_factory which run_applescript should call instead
        of subprocess.Popen directly.
        """
        from apple_mail_mcp import core
        with patch.object(core, "_popen_factory", return_value=fake_proc):
            return core.run_applescript("display dialog \"hi\"", timeout=timeout)

    def test_child_registered_while_running(self):
        """Popen is in _inflight_children while communicate() is blocked."""
        from apple_mail_mcp import core

        barrier = threading.Event()
        observed_in_registry = []

        class BlockingPopen(FakePopen):
            def communicate(self, input=None, timeout=None):
                # Signal the test thread that we are inside communicate()
                barrier.set()
                # Block until the test has snapshotted the registry
                time.sleep(0.15)
                return (b"ok", b"")

        proc = BlockingPopen()

        def _run():
            self._run_with_fake_popen(proc)

        t = threading.Thread(target=_run)
        t.start()

        # Wait until communicate() is entered
        barrier.wait(timeout=2.0)

        with core._inflight_lock:
            observed_in_registry.append(proc in core._inflight_children)

        t.join(timeout=2.0)

        self.assertTrue(
            observed_in_registry[0],
            "Popen should be in _inflight_children while communicate() is running",
        )

    def test_child_deregistered_after_success(self):
        """Popen is removed from _inflight_children after a successful call."""
        from apple_mail_mcp import core

        proc = FakePopen(stdout=b"hello", stderr=b"")
        self._run_with_fake_popen(proc)

        with core._inflight_lock:
            self.assertNotIn(
                proc,
                core._inflight_children,
                "Popen should be removed from _inflight_children after completion",
            )

    def test_child_deregistered_after_timeout(self):
        """Popen is removed and killed after TimeoutExpired."""
        from apple_mail_mcp import core

        class TimeoutPopen(FakePopen):
            def communicate(self, input=None, timeout=None):
                raise subprocess.TimeoutExpired(cmd="osascript", timeout=timeout)

        proc = TimeoutPopen()
        with patch.object(core, "_popen_factory", return_value=proc):
            with self.assertRaises(Exception, msg="Should raise on timeout"):
                core.run_applescript("display dialog \"x\"", timeout=1)

        with core._inflight_lock:
            self.assertNotIn(proc, core._inflight_children)
        self.assertTrue(proc.killed, "kill() should have been called on timeout")

    def test_child_deregistered_after_error(self):
        """Popen is removed from registry even if communicate() raises unexpectedly."""
        from apple_mail_mcp import core

        class BrokenPopen(FakePopen):
            def communicate(self, input=None, timeout=None):
                raise OSError("pipe broken")

        proc = BrokenPopen()
        with patch.object(core, "_popen_factory", return_value=proc):
            with self.assertRaises(Exception):
                core.run_applescript("display dialog \"x\"", timeout=120)

        with core._inflight_lock:
            self.assertNotIn(proc, core._inflight_children)

    def test_return_value_preserved(self):
        """run_applescript returns the stdout content (sanitized) unchanged."""
        from apple_mail_mcp import core

        proc = FakePopen(stdout=b"hello world\r\n", stderr=b"")
        result = self._run_with_fake_popen(proc)
        self.assertEqual(result, "hello world")

    def test_error_on_nonzero_returncode(self):
        """run_applescript raises when osascript exits non-zero with stderr."""
        from apple_mail_mcp import core

        class FailPopen(FakePopen):
            def __init__(self):
                super().__init__(returncode=1, stderr=b"some error")

            @property
            def returncode(self):
                return 1

            @returncode.setter
            def returncode(self, v):
                pass

            def communicate(self, input=None, timeout=None):
                return (b"", b"some error")

        proc = FailPopen()
        with patch.object(core, "_popen_factory", return_value=proc):
            with self.assertRaises(Exception, msg="Should raise on AppleScript error"):
                core.run_applescript("bad script", timeout=120)


if __name__ == "__main__":
    unittest.main()

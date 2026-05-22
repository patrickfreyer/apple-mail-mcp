"""Tests for generated wrapper command-surface checks (mocked, no live wrapper)."""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CHECK_WRAPPER_PATH = _REPO_ROOT / "tools" / "check_wrapper_surface.py"
_spec = importlib.util.spec_from_file_location("check_wrapper_surface", _CHECK_WRAPPER_PATH)
assert _spec and _spec.loader
check_wrapper_surface = importlib.util.module_from_spec(_spec)
sys.modules["check_wrapper_surface"] = check_wrapper_surface
_spec.loader.exec_module(check_wrapper_surface)


class WrapperSurfaceTests(unittest.TestCase):
    def test_check_wrapper_surface_all_present(self):
        help_text = "\n".join(check_wrapper_surface.CRITICAL_WRAPPER_COMMANDS)
        with patch.object(
            check_wrapper_surface, "_wrapper_help", return_value=help_text
        ):
            ok, present, missing = check_wrapper_surface.check_wrapper_surface(
                "apple-mail"
            )
        self.assertTrue(ok)
        self.assertEqual(len(present), len(check_wrapper_surface.CRITICAL_WRAPPER_COMMANDS))
        self.assertEqual(missing, [])

    def test_check_wrapper_surface_missing_get_email_by_id(self):
        help_text = "search-emails\nget-email-thread\nlist-inbox-emails\nget-inbox-overview"
        with patch.object(
            check_wrapper_surface, "_wrapper_help", return_value=help_text
        ):
            ok, _present, missing = check_wrapper_surface.check_wrapper_surface(
                "apple-mail"
            )
        self.assertFalse(ok)
        self.assertIn("get-email-by-id", missing)

    def test_main_skips_when_no_wrapper_on_path(self):
        with patch("shutil.which", return_value=None):
            code = check_wrapper_surface.main([])
        self.assertEqual(code, 0)

    def test_main_fails_when_commands_missing(self):
        with (
            patch("shutil.which", return_value="/bin/apple-mail"),
            patch.object(
                check_wrapper_surface,
                "check_wrapper_surface",
                return_value=(False, [], ["get-email-by-id"]),
            ),
        ):
            code = check_wrapper_surface.main([])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()

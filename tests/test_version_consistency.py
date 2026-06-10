"""Tests that all version strings across the repo agree."""

import importlib.util
import sys
import unittest
from pathlib import Path

# Load check_versions from scripts/ without requiring it to be a package
_REPO_ROOT = Path(__file__).parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "check_versions.py"

spec = importlib.util.spec_from_file_location("check_versions", _SCRIPT)
_cv = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
spec.loader.exec_module(_cv)  # type: ignore[union-attr]


class VersionConsistencyTests(unittest.TestCase):
    def test_all_version_strings_agree(self):
        """Every file that carries a version string must declare the same value."""
        ok, versions = _cv.check(_REPO_ROOT)
        if not ok:
            unique = sorted(set(versions.values()))
            details = "\n".join(f"  {k}: {v}" for k, v in versions.items())
            self.fail(
                f"Version strings disagree ({', '.join(unique)}):\n{details}"
            )

    def test_package_exposes_version(self):
        """apple_mail_mcp.__version__ must be importable and non-empty."""
        # Add plugin/ to path so the package is importable (mirrors the pytest invocation)
        plugin_dir = str(_REPO_ROOT / "plugin")
        added = False
        if plugin_dir not in sys.path:
            sys.path.insert(0, plugin_dir)
            added = True
        try:
            import apple_mail_mcp  # noqa: PLC0415

            ver = getattr(apple_mail_mcp, "__version__", None)
            self.assertIsNotNone(ver, "apple_mail_mcp.__version__ is not defined")
            self.assertIsInstance(ver, str, "apple_mail_mcp.__version__ must be a str")
            self.assertTrue(ver.strip(), "apple_mail_mcp.__version__ must not be empty")
        finally:
            if added:
                sys.path.remove(plugin_dir)


if __name__ == "__main__":
    unittest.main()

"""Tests for tools/validate_manifests.py (Phase 1 CI guardrails)."""

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ValidateManifestsTests(unittest.TestCase):
    def test_validate_manifests_passes_on_current_repo(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/validate_manifests.py")],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=result.stdout + result.stderr,
        )
        self.assertIn("validate_manifests: OK", result.stdout)


if __name__ == "__main__":
    unittest.main()

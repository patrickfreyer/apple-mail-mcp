#!/usr/bin/env python3
"""
extract_changelog.py — Print the CHANGELOG section for the current version.

Reads the version from pyproject.toml, finds the matching `## [<version>]`
heading in CHANGELOG.md, and prints that section (up to the next `## ` heading).
Used by the release workflow to build GitHub Release notes from the changelog.

Usage:
    python scripts/extract_changelog.py            # current pyproject version
    python scripts/extract_changelog.py 3.1.7      # explicit version

Always exits 0. If no matching section is found, prints a short fallback so a
release never fails just because the changelog wasn't updated.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def current_version() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    return data["project"]["version"]


def extract(version: str) -> str | None:
    changelog = REPO_ROOT / "CHANGELOG.md"
    if not changelog.is_file():
        return None
    lines = changelog.read_text().splitlines()

    # Match e.g. "## [3.1.7] - 2026-06-12" (tolerate any trailing text).
    start = None
    head_re = re.compile(r"^##\s+\[" + re.escape(version) + r"\]")
    for i, line in enumerate(lines):
        if head_re.match(line):
            start = i
            break
    if start is None:
        return None

    body: list[str] = []
    for line in lines[start + 1:]:
        if line.startswith("## "):  # next section heading
            break
        body.append(line)

    text = "\n".join(body).strip("\n")
    return text or None


def main() -> None:
    version = sys.argv[1] if len(sys.argv) > 1 else current_version()
    section = extract(version)
    if section:
        print(section)
    else:
        print(f"Release {version}. See CHANGELOG.md for details.")
    sys.exit(0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
check_versions.py — Drift guard for version strings.

Reads the version from every file that carries one and asserts they all agree.
Run from the repo root:

    python scripts/check_versions.py

Exits 0 on success, 1 if any version string disagrees (lists offenders).
"""

import json
import re
import sys
from pathlib import Path


def get_versions(repo_root: Path) -> dict[str, str]:
    """Return a mapping of {source_label: version_string} for every tracked file."""
    versions: dict[str, str] = {}

    # 1. apple-mail-mcpb/manifest.json  (single source of truth for the build script)
    manifest_path = repo_root / "apple-mail-mcpb" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    versions["apple-mail-mcpb/manifest.json"] = manifest["version"]

    # 2. pyproject.toml
    pyproject_text = (repo_root / "pyproject.toml").read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject_text, re.MULTILINE)
    if not match:
        raise ValueError("Could not find version in pyproject.toml")
    versions["pyproject.toml"] = match.group(1)

    # 3. server.json — two occurrences: top-level "version" and packages[0]["version"]
    server = json.loads((repo_root / "server.json").read_text())
    versions["server.json#version"] = server["version"]
    versions["server.json#packages[0].version"] = server["packages"][0]["version"]

    # 4. plugin/apple_mail_mcp/__init__.py  __version__
    init_text = (
        repo_root / "plugin" / "apple_mail_mcp" / "__init__.py"
    ).read_text()
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', init_text, re.MULTILINE)
    if not match:
        raise ValueError(
            "Could not find __version__ in plugin/apple_mail_mcp/__init__.py"
        )
    versions["plugin/apple_mail_mcp/__init__.py"] = match.group(1)

    return versions


def check(repo_root: Path | None = None) -> tuple[bool, dict[str, str]]:
    """
    Check that all version strings agree.

    Returns (ok, versions_dict).  ok is True when all strings match.
    Raises ValueError if a version string cannot be parsed.
    """
    if repo_root is None:
        repo_root = Path(__file__).parent.parent
    versions = get_versions(repo_root)
    unique = set(versions.values())
    return len(unique) == 1, versions


def main() -> None:
    repo_root = Path(__file__).parent.parent
    try:
        ok, versions = check(repo_root)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if ok:
        version = next(iter(versions.values()))
        print(f"OK — all version strings agree: {version}")
        for label, ver in versions.items():
            print(f"  {label}: {ver}")
        sys.exit(0)
    else:
        unique_versions = sorted(set(versions.values()))
        print(
            f"FAIL — version strings disagree "
            f"(found {len(unique_versions)} distinct values: "
            f"{', '.join(unique_versions)})",
            file=sys.stderr,
        )
        for label, ver in versions.items():
            marker = "" if len(set(versions.values()) - {ver}) == 0 else "  <-- MISMATCH"
            print(f"  {label}: {ver}{marker}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

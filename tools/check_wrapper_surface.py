#!/usr/bin/env python3
"""Verify generated mcporter wrapper exposes critical MCP commands.

Manifest validation (validate_manifests.py) checks Python ↔ MCPB parity only.
This script checks the *generated* `apple-mail` wrapper on PATH, which embeds
tool schemas at generation time and can drift when new tools are added.

Usage:
  python tools/check_wrapper_surface.py
  python tools/check_wrapper_surface.py --wrapper /path/to/apple-mail

Exit 0 when all critical commands are present; exit 1 otherwise.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

# Critical read commands agents rely on (kebab-case as exposed by mcporter).
CRITICAL_WRAPPER_COMMANDS = (
    "get-email-by-id",
    "search-emails",
    "get-email-thread",
    "list-inbox-emails",
    "get-inbox-overview",
)


def _wrapper_help(wrapper: str) -> str:
    result = subprocess.run(
        [wrapper, "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{wrapper} --help failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout


def check_wrapper_surface(wrapper: str) -> tuple[bool, list[str], list[str]]:
    help_text = _wrapper_help(wrapper)
    missing = [cmd for cmd in CRITICAL_WRAPPER_COMMANDS if cmd not in help_text]
    present = [cmd for cmd in CRITICAL_WRAPPER_COMMANDS if cmd in help_text]
    return not missing, present, missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wrapper",
        default=None,
        help="Path to generated apple-mail wrapper (default: first apple-mail on PATH)",
    )
    args = parser.parse_args(argv)

    wrapper = args.wrapper or shutil.which("apple-mail")
    if not wrapper:
        print(
            "skip: no generated apple-mail wrapper on PATH "
            "(install mcporter bundle or pass --wrapper)",
            file=sys.stderr,
        )
        return 0

    try:
        ok, present, missing = check_wrapper_surface(wrapper)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"wrapper: {wrapper}")
    for cmd in present:
        print(f"  ok   {cmd}")
    for cmd in missing:
        print(f"  MISS {cmd}")

    if not ok:
        print(
            "\nRegenerate wrapper after syncing plugin/:\n"
            "  cd ~/.local/share/apple-mail-cli\n"
            "  rsync -a --delete --exclude venv "
            "/path/to/apple-mail-mcp/plugin/ ./plugin/\n"
            "  npx mcporter@0.11.3 generate-cli --from apple-mail-cli.mjs "
            "--bundle apple-mail-cli.mjs\n"
            "  ./install.sh",
            file=sys.stderr,
        )
        return 1

    print("wrapper surface: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
verify_wheel.py — Pre-publish artifact guard.

Catches the exact class of bug that shipped in the broken 2.2.0 PyPI release:
a wheel that contains only the dist-info + console-script entry point but NOT
the apple_mail_mcp/ package (so `uvx mcp-apple-mail` dies with
ModuleNotFoundError: No module named 'apple_mail_mcp').

What it checks, given a built wheel:
  1. STRUCTURE — the wheel actually contains apple_mail_mcp/__init__.py,
     apple_mail_mcp/__main__.py, and a healthy number of module files.
  2. SIZE — the package payload is far larger than an empty wheel (~6 KB),
     guarding against the "dist-info only" regression.
  3. INSTALL — pip-installs the wheel into a throwaway venv, imports the
     package, loads the apple_mail_mcp.__main__:main entry point, and confirms
     the mcp-apple-mail console script resolves. (Skip with --skip-install.)

Usage:
    python scripts/verify_wheel.py                 # auto-find newest dist/*.whl
    python scripts/verify_wheel.py path/to.whl     # explicit wheel
    python scripts/verify_wheel.py --skip-install  # structure/size checks only

Exits 0 on success, non-zero (with a clear message) on any failure.
stdlib-only — safe to run in CI before any dependency install.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path

PACKAGE = "apple_mail_mcp"
DIST_NAME = "mcp-apple-mail"
CONSOLE_SCRIPT = "mcp-apple-mail"
ENTRY_POINT = "apple_mail_mcp.__main__:main"

# An empty/broken wheel (dist-info only) is ~6 KB. A healthy build is >200 KB.
MIN_PACKAGE_BYTES = 50_000
MIN_PACKAGE_FILES = 8


def fail(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"FAIL — {msg}", file=sys.stderr)
    sys.exit(1)


def find_wheel(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            fail(f"wheel not found: {p}")
        return p
    dist = Path("dist")
    if not dist.is_dir():
        fail("no dist/ directory — run `python -m build` first (or pass a wheel path)")
    wheels = sorted(dist.glob("*.whl"), key=lambda p: p.stat().st_mtime)
    if not wheels:
        fail("no *.whl found in dist/ — run `python -m build` first")
    return wheels[-1]


def check_structure(wheel: Path) -> None:
    print(f"==> Inspecting {wheel.name}")
    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()
        infos = {i.filename: i.file_size for i in zf.infolist()}

    pkg_files = [n for n in names if n.startswith(f"{PACKAGE}/") and n.endswith(".py")]
    required = {f"{PACKAGE}/__init__.py", f"{PACKAGE}/__main__.py"}
    missing = sorted(r for r in required if r not in names)
    if missing:
        fail(
            f"wheel is missing required module file(s): {', '.join(missing)}. "
            f"This is the 2.2.0-style 'package not included' regression. "
            f"Check [tool.hatch.build.targets.wheel] packages in pyproject.toml."
        )

    if len(pkg_files) < MIN_PACKAGE_FILES:
        fail(
            f"wheel contains only {len(pkg_files)} {PACKAGE}/*.py files "
            f"(expected >= {MIN_PACKAGE_FILES}). Payload looks incomplete."
        )

    pkg_bytes = sum(sz for n, sz in infos.items() if n.startswith(f"{PACKAGE}/"))
    if pkg_bytes < MIN_PACKAGE_BYTES:
        fail(
            f"{PACKAGE}/ payload is only {pkg_bytes} bytes "
            f"(expected >= {MIN_PACKAGE_BYTES}). Likely a dist-info-only wheel."
        )

    print(f"    OK structure: {len(pkg_files)} module files, {pkg_bytes:,} bytes in {PACKAGE}/")


def check_install(wheel: Path) -> None:
    print("==> Clean-venv install + import + entry-point check")
    with tempfile.TemporaryDirectory() as td:
        venv_dir = Path(td) / "venv"
        venv.create(venv_dir, with_pip=True, clear=True)
        bin_dir = venv_dir / ("Scripts" if sys.platform == "win32" else "bin")
        py = bin_dir / ("python.exe" if sys.platform == "win32" else "python")
        pip = bin_dir / ("pip.exe" if sys.platform == "win32" else "pip")

        res = subprocess.run(
            [str(pip), "install", "--quiet", str(wheel)],
            capture_output=True, text=True,
        )
        if res.returncode != 0:
            fail(f"pip install of the wheel failed:\n{res.stdout}\n{res.stderr}")

        probe = (
            "import importlib, importlib.metadata as md\n"
            "import apple_mail_mcp\n"
            "from apple_mail_mcp.__main__ import main\n"
            "for mod in ('core','tools.compose','tools.search','tools.manage',"
            "'tools.inbox','tools.analytics','tools.smart_inbox'):\n"
            "    importlib.import_module('apple_mail_mcp.' + mod)\n"
            "eps = [e for e in md.entry_points(group='console_scripts') "
            f"if e.name == {CONSOLE_SCRIPT!r}]\n"
            "assert eps, 'console script entry point missing'\n"
            f"assert eps[0].value == {ENTRY_POINT!r}, 'entry point target changed: ' + eps[0].value\n"
            "assert callable(eps[0].load()), 'entry point does not load to a callable'\n"
            "print(apple_mail_mcp.__version__)\n"
        )
        res = subprocess.run([str(py), "-c", probe], capture_output=True, text=True)
        if res.returncode != 0:
            fail(f"smoke import / entry-point check failed:\n{res.stdout}\n{res.stderr}")

        installed_version = res.stdout.strip().splitlines()[-1]

        # The console script must exist on the venv PATH and be runnable.
        script = bin_dir / (f"{CONSOLE_SCRIPT}.exe" if sys.platform == "win32" else CONSOLE_SCRIPT)
        if not script.exists():
            fail(f"console script not installed: {script}")

    print(f"    OK install: imported apple_mail_mcp {installed_version}, "
          f"entry point {ENTRY_POINT} resolves, `{CONSOLE_SCRIPT}` script present")


def main() -> None:
    ap = argparse.ArgumentParser(description="Verify a built wheel before publishing.")
    ap.add_argument("wheel", nargs="?", help="path to wheel (default: newest dist/*.whl)")
    ap.add_argument("--skip-install", action="store_true",
                    help="skip the clean-venv install test (structure/size only)")
    args = ap.parse_args()

    wheel = find_wheel(args.wheel)
    check_structure(wheel)
    if args.skip_install:
        print("==> Skipping clean-venv install (--skip-install)")
    else:
        check_install(wheel)

    print(f"\nPASS — {wheel.name} is a healthy {DIST_NAME} distribution.")
    sys.exit(0)


if __name__ == "__main__":
    main()

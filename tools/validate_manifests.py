#!/usr/bin/env python3
"""Validate version sync, tool counts, and mcpb tool name parity."""

from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _fail(msg: str) -> None:
    print(f"validate_manifests: {msg}", file=sys.stderr)
    sys.exit(1)


def _read_project_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"^\[project\]\s*$([\s\S]*?)(?=^\[|\Z)", text, re.M)
    if not block:
        _fail("pyproject.toml: missing [project] section")
    match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', block.group(1), re.M)
    if not match:
        _fail("pyproject.toml: missing [project].version")
    return match.group(1)


def _json_field(path: Path, dotted: str):
    data = json.loads(path.read_text(encoding="utf-8"))
    cur = data
    for part in dotted.split("."):
        if "[" in part:
            key, rest = part.split("[", 1)
            idx = int(rest.rstrip("]"))
            cur = cur[key][idx]
        else:
            cur = cur[part]
    return cur


def _extract_registered_tool_names() -> list[str]:
    names: list[str] = []
    for path in sorted(glob.glob(str(ROOT / "plugin/apple_mail_mcp/tools/*.py"))):
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        i = 0
        while i < len(lines):
            if re.match(r"^@mcp\.tool", lines[i]):
                j = i + 1
                while j < len(lines) and lines[j].startswith("@"):
                    j += 1
                if j >= len(lines):
                    _fail(f"no function after @mcp.tool in {path}:{i + 1}")
                match = re.match(r"(?:async )?def (\w+)", lines[j])
                if not match:
                    _fail(f"no def after @mcp.tool in {path}:{i + 1}")
                names.append(match.group(1))
                i = j + 1
            else:
                i += 1
    return names


def _check_tool_count_claim(text: str | None, source: str, actual: int, errors: list[str]) -> None:
    match = re.search(r"(\d+)\s+(?:MCP\s+)?tools?\b", text or "", re.I)
    if not match:
        errors.append(f"{source}: missing '<N> tools' or '<N> MCP tools' in description")
        return
    claimed = int(match.group(1))
    if claimed != actual:
        errors.append(
            f"{source}: description claims {claimed} tools, registry has {actual}"
        )


def main() -> None:
    errors: list[str] = []
    expected_version = _read_project_version()

    version_checks = [
        (ROOT / "plugin/.claude-plugin/plugin.json", "version", "plugin.json"),
        (ROOT / ".claude-plugin/marketplace.json", "plugins[0].version", "marketplace.json"),
        (ROOT / "server.json", "version", "server.json"),
        (ROOT / "server.json", "packages[0].version", "server.json packages[0]"),
        (ROOT / "apple-mail-mcpb/manifest.json", "version", "mcpb manifest.json"),
    ]
    for path, field, label in version_checks:
        actual = _json_field(path, field)
        if actual != expected_version:
            errors.append(f"{label}: got '{actual}', expected '{expected_version}'")

    code_names = _extract_registered_tool_names()
    actual_count = len(code_names)
    if actual_count == 0:
        errors.append("no @mcp.tool registrations found")

    plugin = json.loads((ROOT / "plugin/.claude-plugin/plugin.json").read_text(encoding="utf-8"))
    _check_tool_count_claim(plugin.get("description"), "plugin.json description", actual_count, errors)

    market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
    plugins = market.get("plugins") or []
    if not plugins:
        errors.append("marketplace.json: missing plugins[0]")
    else:
        _check_tool_count_claim(
            plugins[0].get("description"),
            "marketplace.json plugins[0].description",
            actual_count,
            errors,
        )

    mcpb = json.loads((ROOT / "apple-mail-mcpb/manifest.json").read_text(encoding="utf-8"))
    _check_tool_count_claim(mcpb.get("description"), "mcpb manifest description", actual_count, errors)

    mcpb_names = [tool["name"] for tool in mcpb.get("tools", [])]
    if len(mcpb_names) != actual_count:
        errors.append(
            f"tool count mismatch: code={actual_count}, mcpb tools[]={len(mcpb_names)}"
        )

    code_set = set(code_names)
    mcpb_set = set(mcpb_names)
    only_code = sorted(code_set - mcpb_set)
    only_mcpb = sorted(mcpb_set - code_set)
    if only_code:
        errors.append("registered in code, missing from mcpb: " + ", ".join(only_code))
    if only_mcpb:
        errors.append("present in mcpb tools[], missing from code: " + ", ".join(only_mcpb))

    if errors:
        print("validate_manifests: FAILED", file=sys.stderr)
        for err in errors:
            print(f"  ERROR: {err}", file=sys.stderr)
        sys.exit(1)

    print(
        f"validate_manifests: OK (version={expected_version}, tools={actual_count})"
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env bash
# Phase 1 CI guardrails: version sync, tool count claims, mcpb tool name parity.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ERRORS=()

err() {
  ERRORS+=("$1")
}

for cmd in python3 rg; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    err "Required command not found: $cmd"
  fi
done

if ((${#ERRORS[@]} > 0)); then
  printf 'validate_manifests.sh: %s\n' "${ERRORS[@]}" >&2
  exit 1
fi

# --- 1. Version strings (source of truth: pyproject.toml [project].version) ---
EXPECTED_VERSION="$(python3 <<'PY'
import re
from pathlib import Path

text = Path("pyproject.toml").read_text(encoding="utf-8")
block = re.search(r"^\[project\]\s*$([\s\S]*?)(?=^\[|\Z)", text, re.M)
if not block:
    raise SystemExit("pyproject.toml: missing [project] section")
m = re.search(r'^version\s*=\s*"([^"]+)"', block.group(1), re.M)
if not m:
    raise SystemExit("pyproject.toml: missing [project].version")
print(m.group(1))
PY
)"

read_json_field() {
  python3 - "$1" "$2" <<'PY'
import json
import sys

path, dotted = sys.argv[1], sys.argv[2]
data = json.load(open(path, encoding="utf-8"))
cur = data
for part in dotted.split("."):
    if "[" in part:
        key, rest = part.split("[", 1)
        idx = int(rest.rstrip("]"))
        cur = cur[key][idx]
    else:
        cur = cur[part]
print(cur)
PY
}

assert_version() {
  local file="$1"
  local field="$2"
  local label="$3"
  local actual
  actual="$(read_json_field "$file" "$field")"
  if [[ "$actual" != "$EXPECTED_VERSION" ]]; then
    err "${label}: got ${actual}, expected ${EXPECTED_VERSION} (from pyproject.toml)"
  fi
}

assert_version "plugin/.claude-plugin/plugin.json" "version" \
  "plugin/.claude-plugin/plugin.json version"
assert_version ".claude-plugin/marketplace.json" "plugins[0].version" \
  "marketplace.json plugins[0].version"
assert_version "server.json" "version" "server.json version"
assert_version "server.json" "packages[0].version" "server.json packages[0].version"
assert_version "apple-mail-mcpb/manifest.json" "version" "mcpb manifest.json version"

# --- 2. Registered tool count vs description claims ---
ACTUAL_TOOL_COUNT="$(rg "^@mcp\.tool" plugin/apple_mail_mcp/tools/*.py | wc -l | tr -d " ")"
if [[ -z "$ACTUAL_TOOL_COUNT" || "$ACTUAL_TOOL_COUNT" == "0" ]]; then
  err "No @mcp.tool registrations found under plugin/apple_mail_mcp/tools/*.py"
fi

if ! python3 - "$ACTUAL_TOOL_COUNT" <<'PY'
import json
import re
import sys

actual = int(sys.argv[1])
errors = []


def check_claim(text, source):
    m = re.search(r"(\d+)\s+(?:MCP\s+)?tools?\b", text or "", re.I)
    if not m:
        errors.append(f"{source}: missing N tools / N MCP tools claim in description")
        return
    claimed = int(m.group(1))
    if claimed != actual:
        errors.append(
            f"{source}: description claims {claimed} tools, registry has {actual}"
        )


plugin = json.load(open("plugin/.claude-plugin/plugin.json", encoding="utf-8"))
check_claim(plugin.get("description"), "plugin/.claude-plugin/plugin.json description")

market = json.load(open(".claude-plugin/marketplace.json", encoding="utf-8"))
plugins = market.get("plugins") or []
if not plugins:
    errors.append(".claude-plugin/marketplace.json: missing plugins[0]")
else:
    check_claim(
        plugins[0].get("description"),
        ".claude-plugin/marketplace.json plugins[0].description",
    )

mcpb = json.load(open("apple-mail-mcpb/manifest.json", encoding="utf-8"))
check_claim(mcpb.get("description"), "apple-mail-mcpb/manifest.json description")

for msg in errors:
    print(msg, file=sys.stderr)
sys.exit(1 if errors else 0)
PY
then
  err "Tool count claim validation failed (see stderr above)"
fi

# --- 3. @mcp.tool function names vs mcpb manifest tools[] ---
if ! python3 <<'PY'
import glob
import json
import re
import sys
from pathlib import Path


def extract_registered_tool_names():
    names = []
    for path in sorted(glob.glob("plugin/apple_mail_mcp/tools/*.py")):
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        i = 0
        while i < len(lines):
            if re.match(r"^@mcp\.tool", lines[i]):
                j = i + 1
                while j < len(lines) and lines[j].startswith("@"):
                    j += 1
                if j >= len(lines):
                    print(f"no def after @mcp.tool in {path}:{i + 1}", file=sys.stderr)
                    sys.exit(1)
                m = re.match(r"(?:async )?def (\w+)", lines[j])
                if not m:
                    print(f"no def after @mcp.tool in {path}:{i + 1}", file=sys.stderr)
                    sys.exit(1)
                names.append(m.group(1))
                i = j + 1
            else:
                i += 1
    return names


code_names = extract_registered_tool_names()
manifest = json.loads(Path("apple-mail-mcpb/manifest.json").read_text(encoding="utf-8"))
mcpb_names = [t["name"] for t in manifest.get("tools", [])]

errors = []
if len(code_names) != len(mcpb_names):
    errors.append(
        f"tool count mismatch: code={len(code_names)}, mcpb tools[]={len(mcpb_names)}"
    )

code_set = set(code_names)
mcpb_set = set(mcpb_names)
only_code = sorted(code_set - mcpb_set)
only_mcpb = sorted(mcpb_set - code_set)
if only_code:
    errors.append("registered in code, missing from mcpb: " + ", ".join(only_code))
if only_mcpb:
    errors.append("present in mcpb tools[], missing from code: " + ", ".join(only_mcpb))

for msg in errors:
    print(msg, file=sys.stderr)
sys.exit(1 if errors else 0)
PY
then
  err "MCPB tools[] parity check failed (see stderr above)"
fi

if ((${#ERRORS[@]} > 0)); then
  echo "validate_manifests.sh: FAILED" >&2
  for e in "${ERRORS[@]}"; do
    echo "  ERROR: $e" >&2
  done
  exit 1
fi

echo "validate_manifests.sh: OK (version=${EXPECTED_VERSION}, tools=${ACTUAL_TOOL_COUNT})"

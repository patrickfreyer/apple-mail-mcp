#!/usr/bin/env bash
# Unified local dev gate — manifests, pytest, optional wrapper surface check.
#
# Tiers:
#   default  — validate_manifests + pytest; wrapper check when staged tool surface changes
#   surface  — default + check_wrapper_surface.py (skips if no wrapper on PATH)
#   manifest — validate_manifests.sh only
#   live     — default + quick-check against Mail.app (macOS, explicit)
#   all      — default + wrapper check always
#
# Usage:
#   bash tools/dev-check.sh
#   bash tools/dev-check.sh surface
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${ROOT}/.venv/bin/python"
PYTEST="${ROOT}/.venv/bin/pytest"
CLI="${ROOT}/.venv/bin/apple-mail"

TIER="${1:-default}"

if [[ ! -x "$PYTEST" ]]; then
  echo "error: missing .venv — run: python3 -m venv .venv && .venv/bin/pip install -e . pytest" >&2
  exit 1
fi

run_manifests() {
  bash tools/validate_manifests.sh
}

run_pytest() {
  "$PYTEST" tests/ -q
}

run_wrapper() {
  "$PY" tools/check_wrapper_surface.py
}

staged_touches_tool_surface() {
  git diff --cached --name-only 2>/dev/null | grep -Eq \
    '^plugin/apple_mail_mcp/tools/|^plugin/apple_mail_mcp/__init__\.py|^plugin/apple_mail_mcp/server\.py|^apple-mail-mcpb/manifest\.json'
}

run_default() {
  run_manifests
  run_pytest
}

maybe_run_wrapper_for_staged_surface() {
  if staged_touches_tool_surface; then
    echo "→ staged MCP tool surface changes detected; running wrapper check"
    run_wrapper
  fi
}

case "$TIER" in
  default)
    run_default
    maybe_run_wrapper_for_staged_surface
    ;;
  surface)
    run_default
    run_wrapper
    ;;
  manifest)
    run_manifests
    ;;
  live)
    run_default
    if [[ ! -x "$CLI" ]]; then
      echo "error: missing repo CLI at .venv/bin/apple-mail" >&2
      exit 1
    fi
    "$CLI" quick-check --json
    ;;
  all)
    run_default
    run_wrapper
    ;;
  *)
    echo "Usage: bash tools/dev-check.sh [default|surface|manifest|live|all]" >&2
    exit 2
    ;;
esac

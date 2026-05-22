#!/usr/bin/env bash
# Install repo git hooks (pre-commit → dev-check default tier).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK_DIR="$ROOT/.git/hooks"
HOOK="$HOOK_DIR/pre-commit"

if [[ ! -d "$HOOK_DIR" ]]; then
  echo "error: $HOOK_DIR not found — is this a git checkout?" >&2
  exit 1
fi

chmod +x "$ROOT/tools/dev-check.sh" "$ROOT/tools/pre-commit-validate.sh" "$ROOT/tools/install-git-hooks.sh"
ln -sf ../../tools/pre-commit-validate.sh "$HOOK"

echo "Installed pre-commit hook:"
echo "  $HOOK → tools/pre-commit-validate.sh"
echo ""
echo "Each commit runs: bash tools/dev-check.sh default"
echo "  • validate_manifests.sh + pytest (always)"
echo "  • check_wrapper_surface.py when staged files touch MCP tool surface"
echo ""
echo "Run manually: bash tools/dev-check.sh"

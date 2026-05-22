#!/usr/bin/env bash
# Optional local pre-push check — manifest drift + mocked pytest (no live Mail).
# Wire into git: ln -sf ../../tools/pre-commit-validate.sh .git/hooks/pre-commit
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

bash tools/validate_manifests.sh
.venv/bin/pytest tests/ -q

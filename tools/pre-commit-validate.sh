#!/usr/bin/env bash
# Git pre-commit hook — manifest drift + mocked pytest (+ wrapper when tool surface staged).
# Install once per clone: bash tools/install-git-hooks.sh
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

bash tools/dev-check.sh default

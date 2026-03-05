#!/bin/bash

# Startup wrapper for Apple Mail MCP
# Uses uv for fast, reproducible virtual environment and dependency management

set -e

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PYTHON_SCRIPT="${SCRIPT_DIR}/apple_mail_mcp.py"

# Function to log to stderr (visible in Claude Desktop logs)
log_error() {
    echo "[Apple Mail MCP] $1" >&2
}

# Resolve uv binary
if command -v uv &> /dev/null; then
    UV_BIN="$(command -v uv)"
elif [ -x "${HOME}/.cargo/bin/uv" ]; then
    UV_BIN="${HOME}/.cargo/bin/uv"
elif [ -x "${HOME}/.local/bin/uv" ]; then
    UV_BIN="${HOME}/.local/bin/uv"
else
    log_error "ERROR: uv not found. Install it with: curl -Ls https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Sync dependencies (creates venv if needed)
log_error "Syncing dependencies..."
cd "${SCRIPT_DIR}"
"${UV_BIN}" sync --quiet 2>&1 | while read line; do log_error "$line"; done

# Run the Python MCP server
exec "${UV_BIN}" run python "${PYTHON_SCRIPT}" "$@"

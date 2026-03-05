#!/bin/bash

# Startup wrapper for Apple Mail MCP
# Uses uv for fast, reproducible virtual environment and dependency management

set -e

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV_DIR="${SCRIPT_DIR}/.venv"
REQUIREMENTS="${SCRIPT_DIR}/requirements.txt"
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

# Create venv and sync dependencies if needed
if [ ! -d "${VENV_DIR}" ] || [ ! -f "${VENV_DIR}/bin/python3" ]; then
    log_error "Virtual environment not found. Creating with uv..."
    "${UV_BIN}" venv "${VENV_DIR}" 2>&1 | while read line; do log_error "$line"; done
    log_error "Installing dependencies..."
    "${UV_BIN}" pip install --quiet -r "${REQUIREMENTS}" --python "${VENV_DIR}/bin/python3" 2>&1 | while read line; do log_error "$line"; done
    log_error "Setup complete. Starting MCP server..."
fi

# Run the Python MCP server
exec "${VENV_DIR}/bin/python3" "${PYTHON_SCRIPT}" "$@"

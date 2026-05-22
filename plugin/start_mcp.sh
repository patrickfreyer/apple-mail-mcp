#!/bin/bash

# Startup wrapper for Apple Mail MCP
# This script ensures the virtual environment is created on the user's machine
# to avoid Python version/path conflicts

set -e

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV_DIR="${SCRIPT_DIR}/venv"
REQUIREMENTS="${SCRIPT_DIR}/requirements.txt"
PYTHON_SCRIPT="${SCRIPT_DIR}/apple_mail_mcp.py"

# Function to log to stderr (visible in Claude Desktop logs)
log_error() {
    echo "[Apple Mail MCP] $1" >&2
}

find_python() {
    for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "${candidate}" >/dev/null 2>&1; then
            version="$("${candidate}" - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
            major="${version%%.*}"
            minor="${version#*.}"
            if [ "${major}" -gt 3 ] || { [ "${major}" -eq 3 ] && [ "${minor}" -ge 10 ]; }; then
                command -v "${candidate}"
                return 0
            fi
        fi
    done
    return 1
}

PYTHON_BIN="$(find_python || true)"

# Check if venv exists and is valid
if [ ! -d "${VENV_DIR}" ] || [ ! -f "${VENV_DIR}/bin/python3" ]; then
    log_error "Virtual environment not found. Creating on first run..."

    if [ -z "${PYTHON_BIN}" ]; then
        log_error "ERROR: Python 3.10+ not found. Install Python 3.12 or later."
        exit 1
    fi

    # Create venv
    log_error "Creating virtual environment with ${PYTHON_BIN}..."
    "${PYTHON_BIN}" -m venv "${VENV_DIR}" 2>&1 | while read line; do log_error "$line"; done

    # Upgrade pip and install dependencies
    log_error "Installing dependencies..."
    "${VENV_DIR}/bin/pip" install --quiet --upgrade pip 2>&1 | while read line; do log_error "$line"; done
    "${VENV_DIR}/bin/pip" install --quiet -r "${REQUIREMENTS}" 2>&1 | while read line; do log_error "$line"; done

    log_error "Setup complete. Starting MCP server..."
fi

# Run the Python MCP server
exec "${VENV_DIR}/bin/python3" "${PYTHON_SCRIPT}" "$@"

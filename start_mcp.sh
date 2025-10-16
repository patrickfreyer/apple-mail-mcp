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

# Check if venv exists and is valid
if [ ! -d "${VENV_DIR}" ] || [ ! -f "${VENV_DIR}/bin/python3" ]; then
    log_error "Virtual environment not found. Creating on first run..."

    # Check if python3 is available
    if ! command -v python3 &> /dev/null; then
        log_error "ERROR: python3 not found. Please install Python 3.7 or later."
        exit 1
    fi

    # Create venv
    log_error "Creating virtual environment..."
    python3 -m venv "${VENV_DIR}" 2>&1 | while read line; do log_error "$line"; done

    # Upgrade pip and install dependencies
    log_error "Installing dependencies..."
    "${VENV_DIR}/bin/pip" install --quiet --upgrade pip 2>&1 | while read line; do log_error "$line"; done
    "${VENV_DIR}/bin/pip" install --quiet -r "${REQUIREMENTS}" 2>&1 | while read line; do log_error "$line"; done

    log_error "Setup complete. Starting MCP server..."
fi

# Run the Python MCP server
exec "${VENV_DIR}/bin/python3" "${PYTHON_SCRIPT}" "$@"

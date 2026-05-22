"""FastMCP server instance and user preferences."""

import os
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("Apple Mail MCP")

# Load user preferences from environment
USER_PREFERENCES = os.environ.get("USER_EMAIL_PREFERENCES", "")

# Default Mail account name. When set, search/list tools default to this
# account instead of fanning out across every configured account. Tests
# monkeypatch ``apple_mail_mcp.server.DEFAULT_MAIL_ACCOUNT`` directly, so
# tools should read this lazily (e.g. ``from apple_mail_mcp import server;
# server.DEFAULT_MAIL_ACCOUNT``) rather than importing the constant once.
DEFAULT_MAIL_ACCOUNT = os.environ.get("DEFAULT_MAIL_ACCOUNT", "").strip() or None

# Read-only mode flag — set via --read-only CLI argument.
# When enabled, tools that send email are disabled. Drafts remain available.
READ_ONLY = False

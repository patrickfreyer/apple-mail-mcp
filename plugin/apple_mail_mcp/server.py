"""FastMCP server instance and user preferences."""

import os
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("Apple Mail MCP")

# Load user preferences from environment
USER_PREFERENCES = os.environ.get("USER_EMAIL_PREFERENCES", "")

# Read-only mode flag — set via --read-only CLI argument.
# When enabled, tools that send email are disabled. Drafts remain available.
READ_ONLY = False

# Draft-safe mode flag — set via --draft-safe CLI argument.
# When enabled, sending is disabled but draft/open workflows remain available.
DRAFT_SAFE = False

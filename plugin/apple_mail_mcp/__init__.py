"""Apple Mail MCP - Modular package."""

from apple_mail_mcp.server import mcp

# UI availability flag
try:
    from ui import create_inbox_dashboard_ui

    UI_AVAILABLE = True
except ImportError:
    UI_AVAILABLE = False

# Import all tool modules to register @mcp.tool() decorators
from apple_mail_mcp.tools import inbox  # noqa: F401  (5 tools)
from apple_mail_mcp.tools import search  # noqa: F401  (2 tools)
from apple_mail_mcp.tools import compose  # noqa: F401  (5 tools)
from apple_mail_mcp.tools import manage  # noqa: F401  (5 tools)
from apple_mail_mcp.tools import analytics  # noqa: F401  (4 tools)
from apple_mail_mcp.tools import smart_inbox  # noqa: F401  (3 tools)

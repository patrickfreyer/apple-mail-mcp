"""Entry point for `python -m apple_mail_mcp`."""

from apple_mail_mcp.server import mcp

# Import tool modules to register @mcp.tool() decorators
from apple_mail_mcp.tools import inbox      # noqa: F401
from apple_mail_mcp.tools import search     # noqa: F401
from apple_mail_mcp.tools import compose    # noqa: F401
from apple_mail_mcp.tools import manage     # noqa: F401
from apple_mail_mcp.tools import analytics  # noqa: F401

mcp.run()

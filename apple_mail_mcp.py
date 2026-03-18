#!/usr/bin/env python3
"""Apple Mail MCP Server - Entry point.

Supports --read-only to disable tools that send email (compose, reply, forward).
Draft management (list, create, delete) remains available; only the draft "send"
action is blocked.
"""

import argparse
import apple_mail_mcp.server as server

parser = argparse.ArgumentParser(description="Apple Mail MCP Server")
parser.add_argument(
    "--read-only",
    action="store_true",
    help="Disable tools that send email (compose, reply, forward). "
         "Drafts can still be created and listed.",
)
args = parser.parse_args()

# Set the flag before tools are imported (decorator registration happens on import).
server.READ_ONLY = args.read_only

from apple_mail_mcp import mcp  # noqa: E402

# In read-only mode, remove send-capable tools that were registered by decorators.
SEND_TOOLS = ["compose_email", "reply_to_email", "forward_email"]

if args.read_only:
    for name in SEND_TOOLS:
        try:
            mcp.remove_tool(name)
        except (KeyError, ValueError):
            pass  # Tool may not exist — fine to skip.

if __name__ == "__main__":
    mcp.run()

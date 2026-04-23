"""Entry point for `python -m apple_mail_mcp` and `apple-mail-mcp` CLI."""

import argparse
import os
import threading
import time

import apple_mail_mcp.server as server


# When the MCP client (e.g. Claude) exits without closing stdin
# cleanly, the FastMCP server can keep running orphaned in the background
# (see modelcontextprotocol/python-sdk#526). The orphaned server keeps
# polling Mail.app via Apple Events, which causes Mail to relaunch after
# the user quits it. Detect the orphan state (PPID reparented to launchd)
# and self-terminate. Uses os._exit because sys.exit does not tear down
# FastMCP's background asyncio loop reliably.
def _start_orphan_watcher(interval_sec: int = 10) -> None:
    def _watch() -> None:
        while True:
            if os.getppid() < 100:
                os._exit(0)
            time.sleep(interval_sec)

    threading.Thread(target=_watch, daemon=True).start()


def main():
    _start_orphan_watcher()

    parser = argparse.ArgumentParser(description="Apple Mail MCP Server")
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Disable tools that send email (compose, reply, forward). "
             "Drafts can still be created and listed.",
    )
    args = parser.parse_args()

    server.READ_ONLY = args.read_only

    from apple_mail_mcp import mcp  # noqa: E402

    SEND_TOOLS = ["compose_email", "reply_to_email", "forward_email"]
    if args.read_only:
        for name in SEND_TOOLS:
            try:
                mcp.remove_tool(name)
            except (KeyError, ValueError):
                pass

    mcp.run()


if __name__ == "__main__":
    main()

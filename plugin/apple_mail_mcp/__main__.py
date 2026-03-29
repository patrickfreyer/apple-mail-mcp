"""Entry point for `python -m apple_mail_mcp` and `apple-mail-mcp` CLI."""

import argparse

import apple_mail_mcp.server as server


def main():
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

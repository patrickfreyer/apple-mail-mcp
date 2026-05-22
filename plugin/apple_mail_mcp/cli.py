"""Command-line interface for Apple Mail MCP tools.

This CLI intentionally wraps the same Python tool functions used by the MCP
server. It is a portable, repo-owned alternative to generated local wrappers.
"""

from __future__ import annotations

import argparse
import json
import sys
from importlib import metadata
from pathlib import Path
from typing import Any, Callable, Sequence


def _version() -> str:
    try:
        return metadata.version("mcp-apple-mail")
    except metadata.PackageNotFoundError:
        return "0.0.0"


def _print_result(result: Any, *, json_mode: bool = False) -> int:
    if json_mode:
        if isinstance(result, str):
            try:
                parsed = json.loads(result)
            except json.JSONDecodeError:
                parsed = {"result": result}
            print(json.dumps(parsed, indent=2, ensure_ascii=False))
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if isinstance(result, (dict, list)):
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(result)
    return 0


def _read_text_arg(value: str | None, file_value: str | None) -> str:
    if value is not None and file_value is not None:
        raise ValueError("Use either --body or --body-file, not both")
    if file_value:
        return Path(file_value).expanduser().read_text()
    return value or ""


def _run_tool(func: Callable[..., Any], json_mode: bool, **kwargs: Any) -> int:
    try:
        return _print_result(func(**kwargs), json_mode=json_mode)
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # pragma: no cover - safety net for CLI UX
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _add_account_flag(parser: argparse.ArgumentParser, required: bool = False) -> None:
    parser.add_argument("--account", required=required, help="Mail account name")


def _add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Print structured JSON")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apple-mail",
        description="Portable CLI for the Apple Mail MCP tools.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_version()}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    accounts = subparsers.add_parser("accounts", help="List Mail accounts")
    _add_json_flag(accounts)

    addresses = subparsers.add_parser(
        "addresses", help="List configured email addresses by account"
    )
    _add_json_flag(addresses)

    inbox = subparsers.add_parser("inbox", help="List inbox emails")
    _add_account_flag(inbox)
    inbox.add_argument("--limit", type=int, default=10, help="Maximum emails per account")
    inbox.add_argument(
        "--unread-only", action="store_true", help="Only include unread emails"
    )
    inbox.add_argument("--content", action="store_true", help="Include content preview")
    _add_json_flag(inbox)

    search = subparsers.add_parser("search", help="Search emails")
    _add_account_flag(search)
    search.add_argument("--mailbox", default="INBOX", help="Mailbox path")
    search.add_argument("--query", help="Subject keyword alias")
    search.add_argument("--subject", help="Subject keyword")
    search.add_argument("--sender", help="Sender substring")
    search.add_argument("--body", help="Body text search, slower")
    search.add_argument("--date-from", help="Start date YYYY-MM-DD")
    search.add_argument("--date-to", help="End date YYYY-MM-DD")
    search.add_argument("--limit", type=int, default=20, help="Maximum results")
    search.add_argument("--offset", type=int, default=0, help="Pagination offset")
    search.add_argument("--content", action="store_true", help="Include content preview")
    _add_json_flag(search)

    show = subparsers.add_parser("show", help="Fetch one email by exact message id")
    _add_account_flag(show, required=True)
    show.add_argument("--id", required=True, dest="message_id", help="Mail message id")
    show.add_argument("--mailbox", default="INBOX", help="Mailbox path")
    show.add_argument(
        "--no-content", action="store_true", help="Do not include message content"
    )
    show.add_argument(
        "--max-content-length",
        type=int,
        default=5000,
        help="Maximum content chars when content is enabled",
    )
    _add_json_flag(show)

    mailboxes = subparsers.add_parser("mailboxes", help="List mailboxes")
    _add_account_flag(mailboxes)
    mailboxes.add_argument(
        "--no-counts", action="store_true", help="Skip message/unread counts"
    )
    _add_json_flag(mailboxes)

    draft = subparsers.add_parser("draft", help="Create a draft email")
    _add_account_flag(draft, required=True)
    draft.add_argument("--to", required=True, help="Recipient address(es)")
    draft.add_argument("--subject", required=True, help="Subject line")
    draft.add_argument("--body", help="Plain text body")
    draft.add_argument("--body-file", help="Read plain text body from file")
    draft.add_argument("--html-file", help="Read HTML body from file")
    draft.add_argument("--cc", help="CC address(es)")
    draft.add_argument("--bcc", help="BCC address(es)")
    draft.add_argument("--from-address", help="Sender alias on the account")
    draft.add_argument("--open", action="store_true", help="Open compose window")
    _add_json_flag(draft)

    config = subparsers.add_parser(
        "mcp-config", help="Print Claude/OpenClaw MCP config JSON"
    )
    config.add_argument(
        "--repo",
        default=str(Path(__file__).resolve().parents[2]),
        help="Path to the apple-mail-mcp repository checkout",
    )
    config.add_argument(
        "--unsafe-send",
        action="store_true",
        help="Omit --draft-safe from generated config",
    )

    smoke = subparsers.add_parser("smoke-test", help="Run privacy-safe live checks")
    _add_account_flag(smoke)
    _add_json_flag(smoke)

    return parser


def _cmd_accounts(args: argparse.Namespace) -> int:
    from apple_mail_mcp.tools.inbox import list_accounts

    return _run_tool(list_accounts, args.json)


def _cmd_addresses(args: argparse.Namespace) -> int:
    from apple_mail_mcp.tools.inbox import list_account_addresses

    return _run_tool(list_account_addresses, args.json)


def _cmd_inbox(args: argparse.Namespace) -> int:
    from apple_mail_mcp.tools.inbox import list_inbox_emails

    return _run_tool(
        list_inbox_emails,
        args.json,
        account=args.account,
        max_emails=args.limit,
        include_read=not args.unread_only,
        include_content=args.content,
        output_format="json" if args.json else "text",
    )


def _cmd_search(args: argparse.Namespace) -> int:
    from apple_mail_mcp.tools.search import search_emails

    subject = args.subject or args.query
    return _run_tool(
        search_emails,
        args.json,
        account=args.account,
        mailbox=args.mailbox,
        subject_keyword=subject,
        sender=args.sender,
        body_text=args.body,
        date_from=args.date_from,
        date_to=args.date_to,
        include_content=args.content,
        limit=args.limit,
        offset=args.offset,
        output_format="json" if args.json else "text",
    )


def _cmd_show(args: argparse.Namespace) -> int:
    from apple_mail_mcp.tools.search import get_email_by_id

    return _run_tool(
        get_email_by_id,
        args.json,
        account=args.account,
        message_id=args.message_id,
        mailbox=args.mailbox,
        include_content=not args.no_content,
        max_content_length=args.max_content_length,
        output_format="json" if args.json else "text",
    )


def _cmd_mailboxes(args: argparse.Namespace) -> int:
    from apple_mail_mcp.tools.inbox import list_mailboxes

    return _run_tool(
        list_mailboxes,
        args.json,
        account=args.account,
        include_counts=not args.no_counts,
        output_format="json" if args.json else "text",
    )


def _cmd_draft(args: argparse.Namespace) -> int:
    from apple_mail_mcp.tools.compose import compose_email

    try:
        body = _read_text_arg(args.body, args.body_file)
        body_html = (
            Path(args.html_file).expanduser().read_text() if args.html_file else None
        )
    except OSError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    return _run_tool(
        compose_email,
        args.json,
        account=args.account,
        to=args.to,
        subject=args.subject,
        body=body,
        cc=args.cc,
        bcc=args.bcc,
        mode="open" if args.open else "draft",
        body_html=body_html,
        from_address=args.from_address,
    )


def _cmd_mcp_config(args: argparse.Namespace) -> int:
    start_script = Path(args.repo).expanduser() / "plugin" / "start_mcp.sh"
    tool_args = [str(start_script)]
    if not args.unsafe_send:
        tool_args.append("--draft-safe")
    payload = {
        "mcpServers": {
            "apple-mail": {
                "command": "/bin/bash",
                "args": tool_args,
            }
        }
    }
    return _print_result(payload, json_mode=True)


def _cmd_smoke_test(args: argparse.Namespace) -> int:
    from apple_mail_mcp.tools.inbox import list_accounts, list_inbox_emails
    from apple_mail_mcp.tools.search import search_emails

    checks: list[dict[str, Any]] = []

    def record(name: str, fn: Callable[[], Any]) -> None:
        try:
            value = fn()
            checks.append({"name": name, "ok": True, "detail": _redact(value)})
        except Exception as exc:  # pragma: no cover - live safety path
            checks.append({"name": name, "ok": False, "error": str(exc)})

    accounts = list_accounts()
    selected_account = args.account or (accounts[0] if accounts else None)
    record("accounts", lambda: {"count": len(accounts)})
    if selected_account:
        record(
            "inbox_json",
            lambda: json.loads(
                list_inbox_emails(
                    account=selected_account,
                    max_emails=1,
                    include_read=True,
                    include_content=False,
                    output_format="json",
                )
            ),
        )
        record(
            "no_hit_search",
            lambda: json.loads(
                search_emails(
                    account=selected_account,
                    subject_keyword="NO_SUCH_SUBJECT_APPLE_MAIL_CLI_SMOKE_20991231",
                    output_format="json",
                    limit=1,
                )
            ),
        )
    else:
        checks.append({"name": "mail_account_required", "ok": False})

    ok = all(item["ok"] for item in checks)
    payload = {"ok": ok, "account": selected_account, "checks": checks}
    if args.json:
        _print_result(payload, json_mode=True)
    else:
        for item in checks:
            status = "ok" if item["ok"] else "failed"
            print(f"{status} {item['name']}")
    return 0 if ok else 1


def _redact(value: Any) -> Any:
    if isinstance(value, list):
        return {"count": len(value)}
    if isinstance(value, dict):
        redacted = dict(value)
        if "items" in redacted and isinstance(redacted["items"], list):
            redacted["items"] = {"count": len(redacted["items"])}
        return redacted
    if isinstance(value, str):
        return {"chars": len(value)}
    return value


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "accounts": _cmd_accounts,
    "addresses": _cmd_addresses,
    "inbox": _cmd_inbox,
    "search": _cmd_search,
    "show": _cmd_show,
    "mailboxes": _cmd_mailboxes,
    "draft": _cmd_draft,
    "mcp-config": _cmd_mcp_config,
    "smoke-test": _cmd_smoke_test,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())

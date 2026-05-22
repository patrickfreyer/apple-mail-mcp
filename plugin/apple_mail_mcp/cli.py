"""Command-line interface for Apple Mail MCP tools.

This CLI intentionally wraps the same Python tool functions used by the MCP
server. It is a portable, repo-owned alternative to generated local wrappers.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Callable, Sequence

NO_HIT_SUBJECT = "NO_SUCH_SUBJECT_APPLE_MAIL_CLI_SMOKE_20991231"
INVALID_ACCOUNT = "__INVALID_APPLE_MAIL_CLI_ACCOUNT__"

PERF_THRESHOLDS_MS: dict[str, int] = {
    "metadata": 2000,
    "no_hit_search": 3000,
    "inbox": 5000,
    "dry_run": 5000,
    "overview": 10000,
    "bad_account": 2000,
    "dashboard": 5000,
}


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
        result = func(**kwargs)
        if asyncio.iscoroutine(result):
            result = asyncio.run(result)
        return _print_result(result, json_mode=json_mode)
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


def _await_if_coro(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return asyncio.run(value)
    return value


def _redact(value: Any, *, verbose_sensitive: bool = False) -> Any:
    if verbose_sensitive:
        return value
    if isinstance(value, list):
        if value and all(isinstance(item, str) for item in value):
            return {"count": len(value)}
        return {"count": len(value)}
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"accounts", "available_accounts"} and isinstance(item, list):
                redacted[key] = {"count": len(item)}
            elif key == "addresses" and isinstance(item, dict):
                redacted[key] = {"account_count": len(item)}
            elif key in {"emails", "items", "recent", "mailboxes"} and isinstance(item, list):
                redacted[key] = {"count": len(item)}
            elif key == "account" and isinstance(item, str):
                redacted[key] = "(redacted)"
            else:
                redacted[key] = _redact(item, verbose_sensitive=False)
        return redacted
    if isinstance(value, str):
        return {"chars": len(value)}
    return value


def _parse_tool_result(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _result_is_error(value: Any) -> bool:
    parsed = _parse_tool_result(value)
    if isinstance(parsed, str):
        return parsed.startswith("Error:")
    if isinstance(parsed, dict):
        if parsed.get("error"):
            return True
        if parsed.get("errors") and not parsed.get("accounts") and not parsed.get("emails"):
            return True
    return False


def _is_expected_account_not_found(value: Any) -> bool:
    parsed = _parse_tool_result(value)
    if isinstance(parsed, dict):
        return parsed.get("error") == "account_not_found"
    if isinstance(parsed, str):
        return "account_not_found" in parsed
    return False


def _resolve_test_account(explicit: str | None) -> tuple[str | None, str | None]:
    from apple_mail_mcp import server as _server
    from apple_mail_mcp.tools.inbox import list_accounts

    if explicit:
        return explicit, None
    if _server.DEFAULT_MAIL_ACCOUNT:
        return _server.DEFAULT_MAIL_ACCOUNT, None
    accounts = list_accounts()
    if accounts:
        return accounts[0], None
    return None, "No Mail accounts configured"


@dataclass(frozen=True)
class PerfCase:
    name: str
    category: str
    threshold_ms: int
    runner: Callable[[], Any]
    expect_error: bool = False


def _timed_call(fn: Callable[[], Any]) -> tuple[Any, float]:
    start = time.perf_counter()
    result = _await_if_coro(fn())
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return result, elapsed_ms


def _evaluate_perf_case(
    case: PerfCase, *, verbose_sensitive: bool = False
) -> dict[str, Any]:
    try:
        result, duration_ms = _timed_call(case.runner)
        parsed = _parse_tool_result(result)
        error = _result_is_error(parsed)
        if case.expect_error:
            passed = (
                duration_ms < case.threshold_ms
                and _is_expected_account_not_found(parsed)
            )
        else:
            passed = duration_ms < case.threshold_ms and not error
        entry: dict[str, Any] = {
            "name": case.name,
            "category": case.category,
            "duration_ms": round(duration_ms, 1),
            "threshold_ms": case.threshold_ms,
            "pass": passed,
            "sample": _redact(parsed, verbose_sensitive=verbose_sensitive),
        }
        if error or case.expect_error:
            entry["error"] = (
                parsed if isinstance(parsed, str) else parsed.get("error", "tool_error")
            )
        return entry
    except Exception as exc:  # pragma: no cover - live safety path
        return {
            "name": case.name,
            "category": case.category,
            "duration_ms": None,
            "threshold_ms": case.threshold_ms,
            "pass": False,
            "error": str(exc),
        }


def build_perf_cases(account: str, *, quick: bool = False) -> list[PerfCase]:
    from apple_mail_mcp.tools.analytics import _get_recent_emails_structured_async
    from apple_mail_mcp.tools.inbox import (
        get_inbox_overview,
        get_mailbox_unread_counts,
        list_account_addresses,
        list_accounts,
        list_inbox_emails,
        list_mailboxes,
    )
    from apple_mail_mcp.tools.manage import manage_trash, move_email
    from apple_mail_mcp.tools.search import search_emails

    async def _dashboard_metadata_probe() -> dict[str, Any]:
        unread = await asyncio.to_thread(get_mailbox_unread_counts, summary_only=True)
        recent = await _get_recent_emails_structured_async(
            max_total=5,
            max_per_account=3,
            include_preview=False,
            timeout=30,
        )
        return {"unread": unread, "recent": recent}

    cases: list[PerfCase] = [
        PerfCase(
            name="metadata",
            category="metadata",
            threshold_ms=PERF_THRESHOLDS_MS["metadata"],
            runner=lambda: {
                "accounts": list_accounts(),
                "addresses": list_account_addresses(),
                "mailboxes": _parse_tool_result(
                    _await_if_coro(
                        list_mailboxes(
                            account=account,
                            include_counts=False,
                            output_format="json",
                        )
                    )
                ),
            },
        ),
        PerfCase(
            name="no_hit_search",
            category="no_hit_search",
            threshold_ms=PERF_THRESHOLDS_MS["no_hit_search"],
            runner=lambda: search_emails(
                account=account,
                subject_keyword=NO_HIT_SUBJECT,
                output_format="json",
                limit=1,
            ),
        ),
        PerfCase(
            name="inbox",
            category="inbox",
            threshold_ms=PERF_THRESHOLDS_MS["inbox"],
            runner=lambda: list_inbox_emails(
                account=account,
                max_emails=1 if quick else 2,
                include_read=True,
                include_content=False,
                output_format="json",
            ),
        ),
    ]

    if quick:
        return cases

    cases.extend(
        [
            PerfCase(
                name="dry_run_move",
                category="dry_run",
                threshold_ms=PERF_THRESHOLDS_MS["dry_run"],
                runner=lambda: move_email(
                    account=account,
                    to_mailbox="Archive",
                    subject_keyword=NO_HIT_SUBJECT,
                    dry_run=True,
                    max_moves=3,
                ),
            ),
            PerfCase(
                name="dry_run_trash",
                category="dry_run",
                threshold_ms=PERF_THRESHOLDS_MS["dry_run"],
                runner=lambda: manage_trash(
                    account=account,
                    action="move_to_trash",
                    subject_keyword=NO_HIT_SUBJECT,
                    dry_run=True,
                    max_deletes=3,
                ),
            ),
            PerfCase(
                name="overview",
                category="overview",
                threshold_ms=PERF_THRESHOLDS_MS["overview"],
                runner=lambda: get_inbox_overview(
                    account=account,
                    output_format="compact",
                    include_mailboxes=False,
                    include_recent=False,
                    include_suggestions=False,
                ),
            ),
            PerfCase(
                name="bad_account",
                category="bad_account",
                threshold_ms=PERF_THRESHOLDS_MS["bad_account"],
                expect_error=True,
                runner=lambda: list_inbox_emails(
                    account=INVALID_ACCOUNT,
                    max_emails=1,
                    output_format="json",
                ),
            ),
            PerfCase(
                name="dashboard_metadata",
                category="dashboard",
                threshold_ms=PERF_THRESHOLDS_MS["dashboard"],
                runner=lambda: _await_if_coro(_dashboard_metadata_probe()),
            ),
        ]
    )
    return cases


def run_perf_battery(
    account: str | None = None,
    *,
    quick: bool = False,
    verbose_sensitive: bool = False,
) -> dict[str, Any]:
    selected_account, account_error = _resolve_test_account(account)
    if not selected_account:
        return {
            "ok": False,
            "account": None,
            "quick": quick,
            "thresholds_ms": PERF_THRESHOLDS_MS,
            "cases": [],
            "error": account_error,
        }

    cases = build_perf_cases(selected_account, quick=quick)
    results = [
        _evaluate_perf_case(case, verbose_sensitive=verbose_sensitive)
        for case in cases
    ]
    ok = all(item["pass"] for item in results)
    total_ms = sum(item["duration_ms"] or 0 for item in results)
    return {
        "ok": ok,
        "account": selected_account,
        "quick": quick,
        "thresholds_ms": PERF_THRESHOLDS_MS,
        "total_duration_ms": round(total_ms, 1),
        "cases": results,
    }


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

    unread = subparsers.add_parser("unread", help="Unread counts by mailbox or account")
    _add_account_flag(unread)
    unread.add_argument(
        "--summary",
        action="store_true",
        help="Return per-account inbox unread totals only",
    )
    unread.add_argument(
        "--include-zero",
        action="store_true",
        help="Include mailboxes with zero unread messages",
    )
    _add_json_flag(unread)

    overview = subparsers.add_parser("overview", help="Inbox overview for one account")
    _add_account_flag(overview)
    overview.add_argument(
        "--format",
        dest="output_format",
        choices=["text", "json", "compact"],
        default="text",
        help="Output format (default: text)",
    )
    overview.add_argument(
        "--no-mailboxes", action="store_true", help="Omit mailbox breakdown"
    )
    overview.add_argument(
        "--no-recent", action="store_true", help="Omit recent email preview"
    )
    overview.add_argument(
        "--no-suggestions", action="store_true", help="Omit suggested actions"
    )
    _add_json_flag(overview)

    needs = subparsers.add_parser(
        "needs-response", help="Unread emails that likely need a response"
    )
    _add_account_flag(needs)
    needs.add_argument("--mailbox", default="INBOX", help="Mailbox to scan")
    needs.add_argument("--days", type=int, default=7, dest="days_back")
    needs.add_argument("--limit", type=int, default=20, dest="max_results")
    _add_json_flag(needs)

    awaiting = subparsers.add_parser(
        "awaiting-reply", help="Sent emails still awaiting a reply"
    )
    _add_account_flag(awaiting)
    awaiting.add_argument("--days", type=int, default=7, dest="days_back")
    awaiting.add_argument("--limit", type=int, default=20, dest="max_results")
    _add_json_flag(awaiting)

    top = subparsers.add_parser("top-senders", help="Most frequent senders in a mailbox")
    _add_account_flag(top)
    top.add_argument("--mailbox", default="INBOX")
    top.add_argument("--days", type=int, default=30, dest="days_back")
    top.add_argument("--limit", type=int, default=10, dest="top_n")
    top.add_argument(
        "--by-domain", action="store_true", dest="group_by_domain", help="Group by domain"
    )
    _add_json_flag(top)

    stats = subparsers.add_parser("statistics", help="Email statistics for an account")
    _add_account_flag(stats)
    stats.add_argument(
        "--scope",
        default="account_overview",
        choices=["account_overview", "sender_stats", "mailbox_breakdown"],
    )
    stats.add_argument("--sender", help="Sender filter for sender_stats scope")
    stats.add_argument("--mailbox", help="Mailbox for mailbox_breakdown scope")
    stats.add_argument("--days", type=int, default=30, dest="days_back")
    _add_json_flag(stats)

    move_dry = subparsers.add_parser(
        "move-dry-run", help="Preview emails that would be moved (no changes)"
    )
    _add_account_flag(move_dry, required=True)
    move_dry.add_argument("--to", required=True, dest="to_mailbox")
    move_dry.add_argument("--from", default="INBOX", dest="from_mailbox")
    move_dry.add_argument("--subject", default=NO_HIT_SUBJECT)
    move_dry.add_argument("--sender")
    move_dry.add_argument("--limit", type=int, default=10, dest="max_moves")
    _add_json_flag(move_dry)

    trash_dry = subparsers.add_parser(
        "trash-dry-run", help="Preview emails that would be trashed (no changes)"
    )
    _add_account_flag(trash_dry, required=True)
    trash_dry.add_argument("--mailbox", default="INBOX")
    trash_dry.add_argument("--subject", default=NO_HIT_SUBJECT)
    trash_dry.add_argument("--sender")
    trash_dry.add_argument("--limit", type=int, default=5, dest="max_deletes")
    _add_json_flag(trash_dry)

    drafts = subparsers.add_parser("drafts", help="Draft email operations")
    drafts_sub = drafts.add_subparsers(dest="drafts_action", required=True)
    drafts_list = drafts_sub.add_parser("list", help="List draft emails")
    _add_account_flag(drafts_list)
    _add_json_flag(drafts_list)

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

    perf = subparsers.add_parser(
        "perf-test",
        help="Time safe read-only checks against Mail.app with pass/fail thresholds",
    )
    _add_account_flag(perf)
    _add_json_flag(perf)
    perf.add_argument(
        "--quick",
        action="store_true",
        help="Run a ~30s subset (metadata, no-hit search, inbox)",
    )
    perf.add_argument(
        "--verbose-sensitive",
        action="store_true",
        help="Include account names and other sensitive fields in perf samples",
    )

    quick = subparsers.add_parser(
        "quick-check",
        help="Fast post-edit battery (~30s); alias for perf-test --quick",
    )
    _add_account_flag(quick)
    _add_json_flag(quick)
    quick.add_argument(
        "--verbose-sensitive",
        action="store_true",
        help="Include account names and other sensitive fields in perf samples",
    )

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


def _cmd_unread(args: argparse.Namespace) -> int:
    from apple_mail_mcp.tools.inbox import get_mailbox_unread_counts

    return _run_tool(
        get_mailbox_unread_counts,
        args.json,
        account=args.account,
        include_zero=args.include_zero,
        summary_only=args.summary,
    )


def _cmd_overview(args: argparse.Namespace) -> int:
    from apple_mail_mcp.tools.inbox import get_inbox_overview

    output_format = args.output_format
    if args.json and output_format == "text":
        output_format = "json"

    return _run_tool(
        get_inbox_overview,
        args.json,
        account=args.account,
        output_format=output_format,
        include_mailboxes=not args.no_mailboxes,
        include_recent=not args.no_recent,
        include_suggestions=not args.no_suggestions,
    )


def _cmd_needs_response(args: argparse.Namespace) -> int:
    from apple_mail_mcp.tools.smart_inbox import get_needs_response

    return _run_tool(
        get_needs_response,
        args.json,
        account=args.account,
        mailbox=args.mailbox,
        days_back=args.days_back,
        max_results=args.max_results,
    )


def _cmd_awaiting_reply(args: argparse.Namespace) -> int:
    from apple_mail_mcp.tools.smart_inbox import get_awaiting_reply

    return _run_tool(
        get_awaiting_reply,
        args.json,
        account=args.account,
        days_back=args.days_back,
        max_results=args.max_results,
    )


def _cmd_top_senders(args: argparse.Namespace) -> int:
    from apple_mail_mcp.tools.smart_inbox import get_top_senders

    return _run_tool(
        get_top_senders,
        args.json,
        account=args.account,
        mailbox=args.mailbox,
        days_back=args.days_back,
        top_n=args.top_n,
        group_by_domain=args.group_by_domain,
    )


def _cmd_statistics(args: argparse.Namespace) -> int:
    from apple_mail_mcp.tools.analytics import get_statistics

    return _run_tool(
        get_statistics,
        args.json,
        account=args.account,
        scope=args.scope,
        sender=args.sender,
        mailbox=args.mailbox,
        days_back=args.days_back,
        output_format="json" if args.json else "text",
    )


def _cmd_move_dry_run(args: argparse.Namespace) -> int:
    from apple_mail_mcp.tools.manage import move_email

    return _run_tool(
        move_email,
        args.json,
        account=args.account,
        to_mailbox=args.to_mailbox,
        from_mailbox=args.from_mailbox,
        subject_keyword=args.subject,
        sender=args.sender,
        max_moves=args.max_moves,
        dry_run=True,
    )


def _cmd_trash_dry_run(args: argparse.Namespace) -> int:
    from apple_mail_mcp.tools.manage import manage_trash

    return _run_tool(
        manage_trash,
        args.json,
        account=args.account,
        action="move_to_trash",
        mailbox=args.mailbox,
        subject_keyword=args.subject,
        sender=args.sender,
        max_deletes=args.max_deletes,
        dry_run=True,
    )


def _cmd_drafts(args: argparse.Namespace) -> int:
    if args.drafts_action == "list":
        from apple_mail_mcp.tools.compose import manage_drafts

        return _run_tool(
            manage_drafts,
            args.json,
            account=args.account,
            action="list",
        )
    print(f"Unsupported drafts action: {args.drafts_action}", file=sys.stderr)
    return 2


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
    from apple_mail_mcp import server as _server
    from apple_mail_mcp.tools.compose import _send_blocked
    from apple_mail_mcp.tools.inbox import list_accounts, list_inbox_emails
    from apple_mail_mcp.tools.search import search_emails

    checks: list[dict[str, Any]] = []

    def record(name: str, fn: Callable[[], Any]) -> None:
        try:
            value = _await_if_coro(fn())
            checks.append(
                {
                    "name": name,
                    "ok": True,
                    "detail": _redact(_parse_tool_result(value)),
                }
            )
        except Exception as exc:  # pragma: no cover - live safety path
            checks.append({"name": name, "ok": False, "error": str(exc)})

    def record_expect(name: str, fn: Callable[[], Any], predicate: Callable[[Any], bool]) -> None:
        try:
            value = _await_if_coro(fn())
            parsed = _parse_tool_result(value)
            ok = predicate(parsed)
            entry: dict[str, Any] = {
                "name": name,
                "ok": ok,
                "detail": _redact(parsed),
            }
            if not ok:
                entry["error"] = "unexpected_result"
            checks.append(entry)
        except Exception as exc:  # pragma: no cover - live safety path
            checks.append({"name": name, "ok": False, "error": str(exc)})

    accounts = list_accounts()
    selected_account, _ = _resolve_test_account(args.account)
    record("accounts", lambda: {"count": len(accounts)})

    if selected_account:
        record(
            "inbox_json",
            lambda: list_inbox_emails(
                account=selected_account,
                max_emails=1,
                include_read=True,
                include_content=False,
                output_format="json",
            ),
        )
        record(
            "no_hit_search",
            lambda: search_emails(
                account=selected_account,
                subject_keyword=NO_HIT_SUBJECT,
                output_format="json",
                limit=1,
            ),
        )
    else:
        checks.append({"name": "mail_account_required", "ok": False})

    record_expect(
        "invalid_account",
        lambda: list_inbox_emails(
            account=INVALID_ACCOUNT,
            max_emails=1,
            output_format="json",
        ),
        _is_expected_account_not_found,
    )

    def _draft_safe_blocked() -> str:
        previous = _server.DRAFT_SAFE
        _server.DRAFT_SAFE = True
        try:
            return _send_blocked("send") or ""
        finally:
            _server.DRAFT_SAFE = previous

    record_expect(
        "draft_safe_send_block",
        _draft_safe_blocked,
        lambda value: isinstance(value, str) and "draft-safe" in value.lower(),
    )

    ok = all(item["ok"] for item in checks)
    payload = {"ok": ok, "account": selected_account, "checks": checks}
    if args.json:
        _print_result(payload, json_mode=True)
    else:
        for item in checks:
            status = "ok" if item["ok"] else "failed"
            print(f"{status} {item['name']}")
    return 0 if ok else 1


def _print_perf_report(payload: dict[str, Any], *, json_mode: bool) -> None:
    if json_mode:
        _print_result(payload, json_mode=True)
        return

    if payload.get("error") and not payload.get("cases"):
        print(f"failed account resolution: {payload['error']}")
        return

    mode = "quick" if payload.get("quick") else "full"
    print(f"perf-test ({mode}) account={payload.get('account')}")
    for item in payload.get("cases", []):
        status = "pass" if item.get("pass") else "FAIL"
        duration = item.get("duration_ms")
        threshold = item.get("threshold_ms")
        duration_text = f"{duration:.1f}ms" if duration is not None else "n/a"
        print(
            f"  {status} {item['name']} ({item['category']}): "
            f"{duration_text} / {threshold}ms"
        )
        if item.get("error"):
            print(f"         error: {item['error']}")
    total = payload.get("total_duration_ms")
    if total is not None:
        print(f"total: {total:.1f}ms")


def _cmd_perf_test(args: argparse.Namespace) -> int:
    payload = run_perf_battery(
        args.account,
        quick=args.quick,
        verbose_sensitive=args.verbose_sensitive,
    )
    _print_perf_report(payload, json_mode=args.json)
    return 0 if payload.get("ok") else 1


def _cmd_quick_check(args: argparse.Namespace) -> int:
    payload = run_perf_battery(
        args.account,
        quick=True,
        verbose_sensitive=args.verbose_sensitive,
    )
    _print_perf_report(payload, json_mode=args.json)
    return 0 if payload.get("ok") else 1


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "accounts": _cmd_accounts,
    "addresses": _cmd_addresses,
    "inbox": _cmd_inbox,
    "search": _cmd_search,
    "show": _cmd_show,
    "mailboxes": _cmd_mailboxes,
    "unread": _cmd_unread,
    "overview": _cmd_overview,
    "needs-response": _cmd_needs_response,
    "awaiting-reply": _cmd_awaiting_reply,
    "top-senders": _cmd_top_senders,
    "statistics": _cmd_statistics,
    "move-dry-run": _cmd_move_dry_run,
    "trash-dry-run": _cmd_trash_dry_run,
    "drafts": _cmd_drafts,
    "draft": _cmd_draft,
    "mcp-config": _cmd_mcp_config,
    "smoke-test": _cmd_smoke_test,
    "perf-test": _cmd_perf_test,
    "quick-check": _cmd_quick_check,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())

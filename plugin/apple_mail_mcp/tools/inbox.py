"""Inbox tools: listing, counting, and overview."""

import asyncio
import json
from typing import Optional, List, Dict, Any, Tuple

from apple_mail_mcp import server as _server
from apple_mail_mcp.server import mcp
from apple_mail_mcp.core import (
    AppleScriptTimeout,
    inject_preferences,
    escape_applescript,
    run_applescript,
    inbox_mailbox_script,
    content_preview_script,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _list_accounts_script() -> str:
    """Tiny AppleScript that returns one Mail account name per line."""
    return '''
    tell application "Mail"
        set acctNames to {}
        repeat with anAccount in (every account)
            set end of acctNames to (name of anAccount)
        end repeat
        set AppleScript's text item delimiters to linefeed
        return acctNames as string
    end tell
    '''


def _list_mail_accounts(timeout: Optional[int] = 30) -> List[str]:
    """Return the list of Mail account names (cheap; under 1s)."""
    raw = run_applescript(_list_accounts_script(), timeout=timeout)
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _parse_pipe_delimited_emails(raw: str) -> List[Dict[str, Any]]:
    """Parse '|||'-delimited AppleScript output into a list of email dicts."""
    emails = []
    if not raw:
        return emails
    for line in raw.split("\n"):
        if "|||" not in line:
            continue
        parts = line.split("|||", 5)
        if len(parts) >= 5:
            item = {
                "subject": parts[0].strip(),
                "sender": parts[1].strip(),
                "date": parts[2].strip(),
                "is_read": parts[3].strip().lower() == "true",
                "account": parts[4].strip(),
            }
            if len(parts) > 5 and parts[5].strip():
                item["content_preview"] = parts[5].strip()
            emails.append(item)
    return emails


# ---------------------------------------------------------------------------
# list_inbox_emails — async, per-account dispatch
# ---------------------------------------------------------------------------

def _build_list_inbox_text_script(
    account: str,
    max_emails: int,
    include_read: bool,
    include_content: bool,
) -> str:
    """Build a text-format inbox script for one account.

    A1: caps the message scan via `messages 1 thru max_emails` (when
    max_emails > 0) and `whose read status is false` when include_read=False,
    so we never enumerate a 24K-message Exchange inbox.
    """
    escaped_account = escape_applescript(account)

    if max_emails > 0:
        if not include_read:
            collection = (
                f'set inboxMessages to (messages of inboxMailbox '
                f'whose read status is false)\n'
                f'                if (count of inboxMessages) > {max_emails} then '
                f'set inboxMessages to items 1 thru {max_emails} of inboxMessages'
            )
        else:
            collection = (
                f'if (count of messages of inboxMailbox) > {max_emails} then\n'
                f'                    set inboxMessages to messages 1 thru {max_emails} of inboxMailbox\n'
                f'                else\n'
                f'                    set inboxMessages to messages of inboxMailbox\n'
                f'                end if'
            )
    else:
        if not include_read:
            collection = (
                'set inboxMessages to (messages of inboxMailbox '
                'whose read status is false)'
            )
        else:
            collection = 'set inboxMessages to messages of inboxMailbox'

    return f"""
    tell application "Mail"
        set outputText to ""
        try
            set anAccount to account "{escaped_account}"
            set accountName to name of anAccount
            {inbox_mailbox_script("inboxMailbox", "anAccount")}
            {collection}
            set messageCount to count of inboxMessages

            if messageCount > 0 then
                set outputText to outputText & "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" & return
                set outputText to outputText & "📧 ACCOUNT: " & accountName & " (" & messageCount & " messages)" & return
                set outputText to outputText & "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" & return & return

                set currentIndex to 0
                set sentCount to 0
                repeat with aMessage in inboxMessages
                    set currentIndex to currentIndex + 1
                    if {max_emails} > 0 and currentIndex > {max_emails} then exit repeat

                    try
                        set messageSubject to subject of aMessage
                        set messageSender to sender of aMessage
                        set messageDate to date received of aMessage
                        set messageRead to read status of aMessage

                        if messageRead then
                            set readIndicator to "✓"
                        else
                            set readIndicator to "✉"
                        end if

                        set outputText to outputText & readIndicator & " " & messageSubject & return
                        set outputText to outputText & "   From: " & messageSender & return
                        set outputText to outputText & "   Date: " & (messageDate as string) & return

                        {content_preview_script(200) if include_content else ""}

                        set outputText to outputText & return
                        set sentCount to sentCount + 1
                    end try
                end repeat
                set outputText to outputText & "__COUNT__|||" & sentCount & return
            end if
        on error errMsg
            set outputText to outputText & "⚠ Error accessing inbox for account {escaped_account}" & return & "   " & errMsg & return & return
        end try

        return outputText
    end tell
    """


def _build_list_inbox_json_script(
    account: str, max_emails: int, include_read: bool
) -> str:
    """Build a JSON-format inbox script for one account."""
    escaped_account = escape_applescript(account)

    if max_emails > 0:
        if not include_read:
            collection = (
                f'set inboxMessages to (messages of inboxMailbox '
                f'whose read status is false)\n'
                f'                if (count of inboxMessages) > {max_emails} then '
                f'set inboxMessages to items 1 thru {max_emails} of inboxMessages'
            )
        else:
            collection = (
                f'if (count of messages of inboxMailbox) > {max_emails} then\n'
                f'                    set inboxMessages to messages 1 thru {max_emails} of inboxMailbox\n'
                f'                else\n'
                f'                    set inboxMessages to messages of inboxMailbox\n'
                f'                end if'
            )
    else:
        if not include_read:
            collection = (
                'set inboxMessages to (messages of inboxMailbox '
                'whose read status is false)'
            )
        else:
            collection = 'set inboxMessages to messages of inboxMailbox'

    return f"""
    tell application "Mail"
        set resultLines to {{}}
        try
            set anAccount to account "{escaped_account}"
            set accountName to name of anAccount
            {inbox_mailbox_script("inboxMailbox", "anAccount")}
            {collection}
            set currentIndex to 0
            repeat with aMessage in inboxMessages
                set currentIndex to currentIndex + 1
                if {max_emails} > 0 and currentIndex > {max_emails} then exit repeat
                try
                    set messageSubject to subject of aMessage
                    set messageSender to sender of aMessage
                    set messageDate to date received of aMessage
                    set messageRead to read status of aMessage
                    set end of resultLines to messageSubject & "|||" & messageSender & "|||" & (messageDate as string) & "|||" & messageRead & "|||" & accountName
                end try
            end repeat
        end try
        set AppleScript's text item delimiters to linefeed
        return resultLines as string
    end tell
    """


def _strip_count_marker(raw: str) -> Tuple[str, int]:
    """Split out the `__COUNT__|||N` marker line if present.

    Returns (clean_text_without_marker, count). Count defaults to 0 when
    no marker is present (e.g. an empty-inbox account).
    """
    if not raw:
        return "", 0
    lines = raw.splitlines()
    count = 0
    kept: List[str] = []
    for line in lines:
        if line.startswith("__COUNT__|||"):
            try:
                count = int(line.split("|||", 1)[1])
            except (IndexError, ValueError):
                count = 0
        else:
            kept.append(line)
    return "\n".join(kept), count


@mcp.tool()
@inject_preferences
async def list_inbox_emails(
    account: Optional[str] = None,
    all_accounts: bool = False,
    max_emails: int = 50,
    include_read: bool = True,
    include_content: bool = False,
    output_format: str = "text",
    timeout: Optional[int] = None,
) -> str:
    """Defaults to 50 most-recent emails from the default account.

    List all emails from inbox across all accounts or a specific account.

    Replaces the former get_recent_emails tool — use account + max_emails to
    get recent emails from a single account.

    Smart defaults:
        - When `account` is None and `all_accounts` is False, the tool falls
          back to the ``DEFAULT_MAIL_ACCOUNT`` env-configured account if one
          is set. Pass `all_accounts=True` to opt back into multi-account
          dispatch even when a default is configured.
        - `max_emails` defaults to 50; pass `0` for unbounded.

    Performance guidance:
        - On multi-account setups with a 10K+ Exchange/Gmail inbox, prefer
          passing an explicit `account` plus a small `max_emails` (e.g. 20)
          — multi-account calls now fan out in parallel, but the slowest
          account still bounds the wall time.
        - `include_read=False` is now pushed into the AppleScript
          `whose read status is false` clause, so it is dramatically faster
          than scanning all messages and filtering Python-side.
        - When one account times out, the call returns partial data for the
          other accounts plus an `errors` field listing the slow account(s).

    Args:
        account: Optional account name to filter (e.g., "Gmail", "Work"). If None, shows all accounts.
        max_emails: Maximum number of emails to return per account (0 = all)
        include_read: Whether to include read emails (default: True)
        include_content: Whether to include a content preview for each email (slower, default: False)
        output_format: "text" (default, human-readable) or "json" (structured list of email dicts)
        timeout: Optional per-account AppleScript timeout in seconds (default: 120s).
            Raise this for known-slow accounts (large Exchange inboxes) when
            the default budget is too tight.

    Returns:
        Formatted list of emails with subject, sender, date, and read status.
        When multi-account dispatch encounters per-account timeouts, the
        response includes the slow account names so the caller can retry
        them individually.
    """

    if output_format not in {"text", "json"}:
        return "Error: Invalid output_format. Use: text, json"

    # Smart default: fall back to the configured default account when neither
    # `account` nor `all_accounts` is set. Lazy attribute read so tests can
    # monkeypatch `apple_mail_mcp.server.DEFAULT_MAIL_ACCOUNT` after import.
    if account is None and not all_accounts and _server.DEFAULT_MAIL_ACCOUNT:
        account = _server.DEFAULT_MAIL_ACCOUNT

    if output_format == "json":
        return await _list_inbox_emails_json(
            account, max_emails, include_read, include_content, timeout
        )

    return await _list_inbox_emails_text(
        account, max_emails, include_read, include_content, timeout
    )


def _run_text_one(
    account: str,
    max_emails: int,
    include_read: bool,
    include_content: bool,
    timeout: Optional[int],
) -> str:
    """Synchronously run one account's text inbox script."""
    script = _build_list_inbox_text_script(
        account, max_emails, include_read, include_content
    )
    return run_applescript(script, timeout=timeout if timeout is not None else 120)


async def _list_inbox_emails_text(
    account: Optional[str],
    max_emails: int,
    include_read: bool,
    include_content: bool,
    timeout: Optional[int],
) -> str:
    """Async text-format implementation, dispatching one script per account."""
    header = "INBOX EMAILS - ALL ACCOUNTS\n\n"
    footer_template = (
        "========================================\n"
        "TOTAL EMAILS: {total}\n"
        "========================================\n"
    )

    if account:
        try:
            body = await asyncio.to_thread(
                _run_text_one, account, max_emails, include_read, include_content, timeout
            )
        except AppleScriptTimeout:
            return (
                header
                + footer_template.format(total=0)
                + f"\nPARTIAL: 1 account(s) timed out: {account}\n"
            )
        clean, count = _strip_count_marker(body)
        return header + clean + "\n" + footer_template.format(total=count)

    # Multi-account: probe account list, then dispatch in parallel.
    try:
        accounts = await asyncio.to_thread(_list_mail_accounts, timeout)
    except AppleScriptTimeout:
        return header + footer_template.format(total=0) + "\nPARTIAL: account listing timed out\n"

    if not accounts:
        return header + footer_template.format(total=0)

    async def run_one(acct: str):
        try:
            return acct, await asyncio.to_thread(
                _run_text_one, acct, max_emails, include_read, include_content, timeout
            )
        except AppleScriptTimeout:
            return acct, AppleScriptTimeout(acct)

    results = await asyncio.gather(*(run_one(a) for a in accounts))

    pieces: List[str] = [header]
    total = 0
    errors: List[str] = []
    for acct, outcome in results:
        if isinstance(outcome, AppleScriptTimeout):
            errors.append(acct)
            continue
        clean, count = _strip_count_marker(outcome)
        if clean:
            pieces.append(clean)
            pieces.append("\n")
        total += count
    pieces.append(footer_template.format(total=total))
    if errors:
        pieces.append(f"\nPARTIAL: {len(errors)} account(s) timed out: {', '.join(errors)}\n")
    return "".join(pieces)


def _run_json_one(
    account: str,
    max_emails: int,
    include_read: bool,
    timeout: Optional[int],
) -> str:
    """Synchronously run one account's JSON inbox script."""
    script = _build_list_inbox_json_script(account, max_emails, include_read)
    return run_applescript(script, timeout=timeout if timeout is not None else 120)


async def _list_inbox_emails_json(
    account: Optional[str],
    max_emails: int,
    include_read: bool,
    include_content: bool,
    timeout: Optional[int],
) -> str:
    """Return inbox emails as a JSON string. Always returns an object with
    `emails` and (optionally) `errors` keys so callers can detect partial
    multi-account responses."""
    # include_content is accepted but not surfaced in JSON (matches prior
    # behavior — JSON format historically omits content previews).
    _ = include_content

    if account:
        try:
            raw = await asyncio.to_thread(
                _run_json_one, account, max_emails, include_read, timeout
            )
            emails = _parse_pipe_delimited_emails(raw)
            return json.dumps({"emails": emails}, indent=2)
        except AppleScriptTimeout:
            return json.dumps({"emails": [], "errors": [account]}, indent=2)

    try:
        accounts = await asyncio.to_thread(_list_mail_accounts, timeout)
    except AppleScriptTimeout:
        return json.dumps({"emails": [], "errors": ["__account_listing__"]}, indent=2)

    if not accounts:
        return json.dumps({"emails": []}, indent=2)

    async def run_one(acct: str):
        try:
            return acct, await asyncio.to_thread(
                _run_json_one, acct, max_emails, include_read, timeout
            )
        except AppleScriptTimeout:
            return acct, AppleScriptTimeout(acct)

    results = await asyncio.gather(*(run_one(a) for a in accounts))
    combined: List[Dict[str, Any]] = []
    errors: List[str] = []
    for acct, outcome in results:
        if isinstance(outcome, AppleScriptTimeout):
            errors.append(acct)
            continue
        combined.extend(_parse_pipe_delimited_emails(outcome))

    payload: Dict[str, Any] = {"emails": combined}
    if errors:
        payload["errors"] = errors
    return json.dumps(payload, indent=2)


# ---------------------------------------------------------------------------
# get_mailbox_unread_counts and other tools (unchanged)
# ---------------------------------------------------------------------------

@mcp.tool()
@inject_preferences
def get_mailbox_unread_counts(
    account: Optional[str] = None,
    include_zero: bool = False,
    summary_only: bool = False,
) -> Dict[str, Any]:
    """
    Get unread counts per mailbox for one account or all accounts.

    When summary_only=True, returns only per-account inbox unread totals
    (replaces the former get_unread_count tool).

    Args:
        account: Optional account name filter
        include_zero: Whether to include mailboxes with zero unread messages
        summary_only: If True, return only per-account inbox unread totals
                      (flat dict of account name -> unread count)

    Returns:
        If summary_only=False: nested dict keyed by account name then mailbox path
        If summary_only=True: flat dict mapping account names to inbox unread counts
    """
    escaped_account = escape_applescript(account) if account else None

    # Fast path: summary_only returns just per-account inbox unread totals
    if summary_only:
        script = f"""
        tell application "Mail"
            set resultList to {{}}
            set allAccounts to every account

            repeat with anAccount in allAccounts
                set accountName to name of anAccount

                try
                    {inbox_mailbox_script("inboxMailbox", "anAccount")}
                    set unreadCount to unread count of inboxMailbox
                    set end of resultList to accountName & ":" & unreadCount
                on error
                    set end of resultList to accountName & ":ERROR"
                end try
            end repeat

            set AppleScript's text item delimiters to "|"
            return resultList as string
        end tell
        """
        result = run_applescript(script)
        counts: Dict[str, int] = {}
        for item in result.split("|"):
            if ":" in item:
                acct_name, count_str = item.split(":", 1)
                if count_str != "ERROR":
                    counts[acct_name] = int(count_str)
                else:
                    counts[acct_name] = -1
        return counts

    account_filter = (
        f'''
            if accountName is not "{escaped_account}" then
                set shouldIncludeAccount to false
            end if
    '''
        if account
        else ""
    )

    script = f"""
    tell application "Mail"
        set resultList to {{}}
        set allAccounts to every account

        repeat with anAccount in allAccounts
            set accountName to name of anAccount
            set shouldIncludeAccount to true
            {account_filter}

            if shouldIncludeAccount then
                try
                    set accountMailboxes to every mailbox of anAccount

                    repeat with aMailbox in accountMailboxes
                        try
                            set mailboxName to name of aMailbox
                            set unreadCount to unread count of aMailbox
                            if {str(include_zero).lower()} or unreadCount > 0 then
                                set end of resultList to accountName & "|||" & mailboxName & "|||" & unreadCount
                            end if

                            try
                                set subMailboxes to every mailbox of aMailbox
                                repeat with subBox in subMailboxes
                                    set subName to name of subBox
                                    set subUnread to unread count of subBox
                                    if {str(include_zero).lower()} or subUnread > 0 then
                                        set end of resultList to accountName & "|||" & mailboxName & "/" & subName & "|||" & subUnread
                                    end if
                                end repeat
                            end try
                        end try
                    end repeat
                end try
            end if
        end repeat

        if (count of resultList) is 0 then
            return ""
        end if

        set AppleScript's text item delimiters to linefeed
        set outputText to resultList as string
        set AppleScript's text item delimiters to ""
        return outputText
    end tell
    """

    result = run_applescript(script)
    counts: Dict[str, Dict[str, int]] = {}
    if not result:
        return counts

    for line in result.splitlines():
        parts = line.split("|||", 2)
        if len(parts) != 3:
            continue
        account_name, mailbox_name, unread_value = parts
        counts.setdefault(account_name, {})[mailbox_name] = int(unread_value)

    return counts


@mcp.tool()
@inject_preferences
def list_accounts() -> List[str]:
    """
    List all available Mail accounts.

    Returns:
        List of account names
    """

    script = """
    tell application "Mail"
        set accountNames to {}
        set allAccounts to every account

        repeat with anAccount in allAccounts
            set accountName to name of anAccount
            set end of accountNames to accountName
        end repeat

        set AppleScript's text item delimiters to "|"
        return accountNames as string
    end tell
    """

    result = run_applescript(script)
    return result.split("|") if result else []


@mcp.tool()
@inject_preferences
def list_account_addresses() -> Dict[str, List[str]]:
    """
    List all configured email addresses for each Mail account.

    Useful for mapping a Mail.app account name (e.g. "Gmail", "Work") to the
    actual email address(es) it receives mail at — handy when an integration
    needs to know which inbox a message landed in by address rather than by
    Mail.app's display name.

    Returns:
        Dict mapping account name -> list of email addresses configured on
        that account. Accounts with no addresses configured map to [].
    """

    script = """
    tell application "Mail"
        set outLines to {}
        set allAccounts to every account

        repeat with anAccount in allAccounts
            set acctName to name of anAccount
            try
                set emailAddrs to email addresses of anAccount
            on error
                set emailAddrs to {}
            end try
            if emailAddrs is missing value then
                set emailAddrs to {}
            end if
            set AppleScript's text item delimiters to ","
            set addrStr to emailAddrs as string
            set AppleScript's text item delimiters to ""
            set end of outLines to acctName & "|" & addrStr
        end repeat

        set AppleScript's text item delimiters to linefeed
        set joined to outLines as string
        set AppleScript's text item delimiters to ""
        return joined
    end tell
    """

    result = run_applescript(script)
    out: Dict[str, List[str]] = {}
    if not result:
        return out
    for line in result.splitlines():
        if "|" not in line:
            continue
        name, addrs = line.split("|", 1)
        out[name] = [a.strip() for a in addrs.split(",") if a.strip()]
    return out


@mcp.tool()
@inject_preferences
def list_mailboxes(
    account: Optional[str] = None,
    include_counts: bool = True,
    output_format: str = "text",
) -> str:
    """
    List all mailboxes (folders) for a specific account or all accounts.

    Args:
        account: Optional account name to filter (e.g., "Gmail", "Work"). If None, shows all accounts.
        include_counts: Whether to include message counts for each mailbox (default: True)
        output_format: "text" (default, human-readable) or "json" (structured list of mailbox dicts)

    Returns:
        Formatted list of mailboxes with optional message counts.
        For nested mailboxes, shows both indented format and path format (e.g., "Projects/Amplify Impact")
    """

    if output_format == "json":
        return _list_mailboxes_json(account, include_counts)

    count_script = (
        """
        try
            set msgCount to count of messages of aMailbox
            set unreadCount to unread count of aMailbox
            set outputText to outputText & " (" & msgCount & " total, " & unreadCount & " unread)"
        on error
            set outputText to outputText & " (count unavailable)"
        end try
    """
        if include_counts
        else ""
    )

    # Escape user inputs for AppleScript
    escaped_account = escape_applescript(account) if account else None

    account_filter = (
        f'''
        if accountName is "{escaped_account}" then
    '''
        if account
        else ""
    )

    account_filter_end = "end if" if account else ""

    script = f"""
    tell application "Mail"
        set outputText to "MAILBOXES" & return & return
        set allAccounts to every account

        repeat with anAccount in allAccounts
            set accountName to name of anAccount

            {account_filter}
                set outputText to outputText & "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" & return
                set outputText to outputText & "📁 ACCOUNT: " & accountName & return
                set outputText to outputText & "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" & return & return

                try
                    set accountMailboxes to every mailbox of anAccount

                    repeat with aMailbox in accountMailboxes
                        set mailboxName to name of aMailbox
                        set outputText to outputText & "  📂 " & mailboxName

                        {count_script}

                        set outputText to outputText & return

                        -- List sub-mailboxes with path notation
                        try
                            set subMailboxes to every mailbox of aMailbox
                            repeat with subBox in subMailboxes
                                set subName to name of subBox
                                set outputText to outputText & "    └─ " & subName & " [Path: " & mailboxName & "/" & subName & "]"

                                {count_script.replace("aMailbox", "subBox") if include_counts else ""}

                                set outputText to outputText & return
                            end repeat
                        end try
                    end repeat

                    set outputText to outputText & return
                on error errMsg
                    set outputText to outputText & "  ⚠ Error accessing mailboxes: " & errMsg & return & return
                end try
            {account_filter_end}
        end repeat

        return outputText
    end tell
    """

    result = run_applescript(script)
    return result


def _list_mailboxes_json(account: Optional[str], include_counts: bool = True) -> str:
    """Return mailboxes as a JSON list."""
    escaped_account = escape_applescript(account) if account else None
    account_filter = (
        f'if accountName is "{escaped_account}" then'
        if account
        else ""
    )
    account_filter_end = "end if" if account else ""
    def count_fields(var_name: str) -> str:
        if not include_counts:
            return """
        set msgCount to -1
        set unreadCount to -1
        """
        return f"""
        set msgCount to -1
        set unreadCount to -1
        try
            set msgCount to count of messages of {var_name}
            set unreadCount to unread count of {var_name}
        end try
        """

    script = f"""
    tell application "Mail"
        set resultLines to {{}}
        set allAccounts to every account
        repeat with anAccount in allAccounts
            set accountName to name of anAccount
            {account_filter}
            try
                set accountMailboxes to every mailbox of anAccount
                repeat with currentMailbox in accountMailboxes
                    try
                        set mailboxName to name of currentMailbox
                        {count_fields("currentMailbox")}
                        set end of resultLines to accountName & "|||" & mailboxName & "|||" & mailboxName & "|||" & msgCount & "|||" & unreadCount
                        try
                            set childMailboxes to every mailbox of currentMailbox
                            repeat with childMailbox in childMailboxes
                                set childName to name of childMailbox
                                {count_fields("childMailbox")}
                                set end of resultLines to accountName & "|||" & childName & "|||" & mailboxName & "/" & childName & "|||" & msgCount & "|||" & unreadCount
                            end repeat
                        end try
                    end try
                end repeat
            end try
            {account_filter_end}
        end repeat
        set AppleScript's text item delimiters to linefeed
        return resultLines as string
    end tell
    """
    raw = run_applescript(script)
    mailboxes = []
    for line in raw.splitlines():
        parts = line.split("|||")
        if len(parts) != 5:
            continue
        msg_count = int(parts[3]) if parts[3].lstrip("-").isdigit() else -1
        unread_count = int(parts[4]) if parts[4].lstrip("-").isdigit() else -1
        item = {
            "account": parts[0],
            "name": parts[1],
            "path": parts[2],
        }
        if include_counts:
            item["message_count"] = msg_count
            item["unread_count"] = unread_count
        mailboxes.append(item)
    return json.dumps(mailboxes, indent=2)


# ---------------------------------------------------------------------------
# get_inbox_overview — async, per-account parallel
# ---------------------------------------------------------------------------

def _build_overview_one_account_script(account: str) -> str:
    """Build a script that returns one account's unread/total/recent slice.

    Returns a structured payload:
        accountName|||unreadCount|||totalCount
        MAILBOX|||name|||unreadCount
        MAILBOX|||name/subName|||subUnread
        RECENT|||subject|||sender|||date|||read
        ...

    A1: caps recent-message enumeration to 10 via
    `messages 1 thru 10 of inboxMailbox`.
    """
    escaped_account = escape_applescript(account)
    return f"""
    tell application "Mail"
        set resultLines to {{}}
        try
            set anAccount to account "{escaped_account}"
            set accountName to name of anAccount

            try
                {inbox_mailbox_script("inboxMailbox", "anAccount")}
                set unreadCount to unread count of inboxMailbox
                set totalMessages to count of messages of inboxMailbox
                set end of resultLines to "HEADER|||" & accountName & "|||" & unreadCount & "|||" & totalMessages

                -- Recent messages (cap at 10)
                if (count of messages of inboxMailbox) > 10 then
                    set recentMessages to messages 1 thru 10 of inboxMailbox
                else
                    set recentMessages to messages of inboxMailbox
                end if

                repeat with aMessage in recentMessages
                    try
                        set messageSubject to subject of aMessage
                        set messageSender to sender of aMessage
                        set messageDate to date received of aMessage
                        set messageRead to read status of aMessage
                        set end of resultLines to "RECENT|||" & messageSubject & "|||" & messageSender & "|||" & (messageDate as string) & "|||" & messageRead
                    end try
                end repeat
            on error errMsg
                set end of resultLines to "HEADER|||" & accountName & "|||ERROR|||" & errMsg
            end try

            -- Mailbox structure with unread counts
            try
                set accountMailboxes to every mailbox of anAccount
                repeat with aMailbox in accountMailboxes
                    try
                        set mailboxName to name of aMailbox
                        set unreadCount to unread count of aMailbox
                        set end of resultLines to "MAILBOX|||" & mailboxName & "|||" & unreadCount
                        try
                            set subMailboxes to every mailbox of aMailbox
                            repeat with subBox in subMailboxes
                                set subName to name of subBox
                                set subUnread to unread count of subBox
                                set end of resultLines to "SUBMAILBOX|||" & mailboxName & "/" & subName & "|||" & subUnread
                            end repeat
                        end try
                    end try
                end repeat
            end try
        on error errMsg
            set end of resultLines to "FATAL|||" & errMsg
        end try

        set AppleScript's text item delimiters to linefeed
        return resultLines as string
    end tell
    """


def _run_overview_one(account: str, timeout: Optional[int]) -> str:
    return run_applescript(
        _build_overview_one_account_script(account),
        timeout=timeout if timeout is not None else 180,
    )


def _parse_overview_account(raw: str) -> Dict[str, Any]:
    """Parse one account's overview payload."""
    result: Dict[str, Any] = {
        "account": None,
        "unread": None,
        "total": None,
        "error": None,
        "mailboxes": [],  # list of (name, unread_count) tuples
        "recent": [],     # list of dicts
    }
    if not raw:
        return result
    for line in raw.splitlines():
        if "|||" not in line:
            continue
        parts = line.split("|||")
        tag = parts[0]
        if tag == "HEADER" and len(parts) >= 4:
            result["account"] = parts[1]
            if parts[2] == "ERROR":
                result["error"] = parts[3] if len(parts) > 3 else "unknown error"
            else:
                try:
                    result["unread"] = int(parts[2])
                    result["total"] = int(parts[3])
                except ValueError:
                    pass
        elif tag in ("MAILBOX", "SUBMAILBOX") and len(parts) >= 3:
            try:
                result["mailboxes"].append((parts[1], int(parts[2])))
            except ValueError:
                pass
        elif tag == "RECENT" and len(parts) >= 5:
            result["recent"].append({
                "subject": parts[1],
                "sender": parts[2],
                "date": parts[3],
                "is_read": parts[4].strip().lower() == "true",
            })
        elif tag == "FATAL" and len(parts) >= 2:
            result["error"] = parts[1]
    return result


def _format_overview(accounts: List[Dict[str, Any]], errors: List[str]) -> str:
    """Format combined per-account overview payloads into the legacy text shape."""
    lines: List[str] = []
    lines.append("╔══════════════════════════════════════════╗")
    lines.append("║      EMAIL INBOX OVERVIEW                ║")
    lines.append("╚══════════════════════════════════════════╝")
    lines.append("")
    lines.append("📊 UNREAD EMAILS BY ACCOUNT")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    total_unread = 0
    for acct in accounts:
        name = acct.get("account") or "(unknown)"
        if acct.get("error"):
            lines.append(f"  ❌ {name}: Error accessing inbox")
            continue
        unread = acct.get("unread") or 0
        total = acct.get("total") or 0
        total_unread += unread
        prefix = "⚠️ " if unread > 0 else "✅"
        lines.append(f"  {prefix} {name}: {unread} unread ({total} total)")

    lines.append("")
    lines.append(f"📈 TOTAL UNREAD: {total_unread} across all accounts")
    lines.append("")
    lines.append("")

    lines.append("📁 MAILBOX STRUCTURE")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    for acct in accounts:
        name = acct.get("account") or "(unknown)"
        lines.append(f"\nAccount: {name}")
        for mb_name, mb_unread in acct.get("mailboxes", []):
            if "/" in mb_name:
                if mb_unread > 0:
                    lines.append(f"     └─ {mb_name.split('/', 1)[1]} ({mb_unread} unread)")
            else:
                if mb_unread > 0:
                    lines.append(f"  📂 {mb_name} ({mb_unread} unread)")
                else:
                    lines.append(f"  📂 {mb_name}")

    lines.append("")
    lines.append("")
    lines.append("📬 RECENT EMAILS PREVIEW (10 Most Recent)")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Collect up to 10 recent across all accounts (matching prior behavior).
    recent_combined = []
    for acct in accounts:
        name = acct.get("account") or "(unknown)"
        for r in acct.get("recent", []):
            recent_combined.append((name, r))
    display_count = 0
    for name, r in recent_combined:
        if display_count >= 10:
            break
        display_count += 1
        indicator = "✓" if r["is_read"] else "✉"
        lines.append("")
        lines.append(f"{indicator} {r['subject']}")
        lines.append(f"   Account: {name}")
        lines.append(f"   From: {r['sender']}")
        lines.append(f"   Date: {r['date']}")

    if display_count == 0:
        lines.append("")
        lines.append("No recent emails found.")

    lines.append("")
    lines.append("")
    lines.append("💡 SUGGESTED ACTIONS FOR ASSISTANT")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("Based on this overview, consider suggesting:")
    lines.append("")
    if total_unread > 0:
        lines.append("1. 📧 Review unread emails - Use list_inbox_emails to show recent unread messages")
        lines.append("2. 🔍 Search for action items - Look for keywords like 'urgent', 'action required', 'deadline'")
        lines.append("3. 📤 Move processed emails - Suggest moving read emails to appropriate folders")
    else:
        lines.append("1. ✅ Inbox is clear! No unread emails.")
    lines.append("4. 📋 Organize by topic - Suggest moving emails to project-specific folders")
    lines.append("5. ✉️  Draft replies - Identify emails that need responses")
    lines.append("6. 🗂️  Archive old emails - Move older read emails to archive folders")
    lines.append("7. 🔔 Highlight priority items - Identify emails from important senders or with urgent keywords")
    lines.append("")
    lines.append("═══════════════════════════════════════════════════")
    lines.append("💬 Ask me to drill down into any account or take specific actions!")
    lines.append("═══════════════════════════════════════════════════")

    if errors:
        lines.append("")
        lines.append(f"PARTIAL: {len(errors)} account(s) timed out: {', '.join(errors)}")

    return "\n".join(lines)


@mcp.tool()
@inject_preferences
async def get_inbox_overview(timeout: Optional[int] = None) -> str:
    """
    Get a comprehensive overview of your email inbox status across all accounts.

    Each account is queried in parallel via its own AppleScript call, so a
    single slow account (e.g. a large Exchange inbox) no longer blocks the
    overview — it appears as an entry in a `PARTIAL` line and the rest of
    the data is returned anyway.

    Args:
        timeout: Optional per-account AppleScript timeout in seconds
            (default: 180s).

    Returns:
        Comprehensive overview including:
        - Unread email counts by account
        - List of available mailboxes/folders
        - AI suggestions for actions (move emails, respond to messages, etc.)

        When one or more accounts time out, the response includes the slow
        account names so the caller can retry them individually with a
        larger `timeout`.
    """
    try:
        accounts = await asyncio.to_thread(_list_mail_accounts, timeout)
    except AppleScriptTimeout:
        return "Error: Mail account listing timed out"

    if not accounts:
        return _format_overview([], [])

    async def run_one(acct: str):
        try:
            return acct, await asyncio.to_thread(_run_overview_one, acct, timeout)
        except AppleScriptTimeout:
            return acct, AppleScriptTimeout(acct)

    results = await asyncio.gather(*(run_one(a) for a in accounts))

    parsed: List[Dict[str, Any]] = []
    errors: List[str] = []
    for acct, outcome in results:
        if isinstance(outcome, AppleScriptTimeout):
            errors.append(acct)
            continue
        parsed.append(_parse_overview_account(outcome))

    return _format_overview(parsed, errors)

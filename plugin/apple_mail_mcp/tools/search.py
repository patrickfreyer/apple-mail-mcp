"""Search tools: finding and filtering emails."""

import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from urllib.parse import quote

from apple_mail_mcp import server as _server
from apple_mail_mcp.server import mcp
from apple_mail_mcp.core import (
    AppleScriptTimeout,
    build_mailbox_ref,
    contains_any_condition,
    inject_preferences,
    escape_applescript,
    normalize_message_ids,
    normalize_search_terms,
    run_applescript,
)


MONTH_NAMES = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def _build_applescript_date(
    var_name: str, date_value: Optional[str], end_of_day: bool = False
) -> str:
    """Build AppleScript to create a date from an ISO day string."""
    if not date_value:
        return ""

    try:
        parsed_date = datetime.strptime(date_value, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Invalid date '{date_value}'. Use YYYY-MM-DD")

    month_name = MONTH_NAMES[parsed_date.month - 1]
    seconds = 86399 if end_of_day else 0
    return f"""
                set {var_name} to current date
                set year of {var_name} to {parsed_date.year}
                set month of {var_name} to {month_name}
                set day of {var_name} to {parsed_date.day}
                set time of {var_name} to {seconds}
    """


def _parse_search_records(output: str) -> List[Dict[str, Any]]:
    """Parse structured search output into dict records."""
    if not output:
        return []

    records = []
    for line in output.splitlines():
        parts = line.split("|||", 8)
        if len(parts) < 8:
            continue

        internet_message_id = parts[1].strip()
        record = {
            "message_id": parts[0].strip(),
            "internet_message_id": internet_message_id,
            "subject": parts[2].strip(),
            "sender": parts[3].strip(),
            "mailbox": parts[4].strip(),
            "account": parts[5].strip(),
            "is_read": parts[6].strip().lower() == "true",
            "received_date": parts[7].strip(),
        }
        if internet_message_id:
            # Apple Mail requires: message:// scheme, angle brackets (percent-encoded),
            # and raw @ in the Message-ID. Normalize ID in case angle brackets are
            # present or missing (AppleScript returns both forms).
            msg_id = internet_message_id.strip("<>")
            record["mail_link"] = f"message://%3C{quote(msg_id, safe='@')}%3E"
        if len(parts) > 8 and parts[8].strip():
            record["content_preview"] = parts[8].strip()
        records.append(record)

    return records


def _sort_search_records(
    records: List[Dict[str, Any]], sort: str
) -> List[Dict[str, Any]]:
    """Sort records by received date."""
    reverse = sort == "date_desc"
    return sorted(
        records, key=lambda item: item.get("received_date", ""), reverse=reverse
    )


def _format_search_records_text(
    records: List[Dict[str, Any]],
    subject_only: bool = False,
    errors: Optional[List[str]] = None,
    recent_days_applied: Optional[float] = None,
) -> str:
    """Format search records as human-readable text."""
    lines = []

    if subject_only:
        lines.append("SUBJECT SEARCH RESULTS")
        lines.append("")
        for item in records:
            lines.append(f"- {item['subject']}")
    else:
        lines.append("SEARCH RESULTS")
        if recent_days_applied is not None:
            if recent_days_applied <= 0:
                lines.append("Window: full inbox")
            elif recent_days_applied == 2.0:
                lines.append("Window: last 48h")
            else:
                lines.append(f"Window: last {recent_days_applied}d")
        lines.append("")
        for item in records:
            indicator = "✓" if item["is_read"] else "✉"
            lines.append(f"{indicator} {item['subject']}")
            lines.append(f"   From: {item['sender']}")
            lines.append(f"   Date: {item['received_date']}")
            lines.append(f"   Mailbox: {item['mailbox']}")
            if item.get("mail_link"):
                lines.append(f"   Link: {item['mail_link']}")
            if item.get("content_preview"):
                lines.append(f"   Content: {item['content_preview']}")
            lines.append("")

    lines.append("========================================")
    lines.append(f"FOUND: {len(records)} matching email(s)")
    if errors:
        lines.append(f"PARTIAL: {len(errors)} account(s) timed out: {', '.join(errors)}")
    lines.append("========================================")
    return "\n".join(lines)


def _build_search_response(
    records: List[Dict[str, Any]],
    offset: int,
    limit: int,
    sort: str,
    output_format: str,
    subject_only: bool = False,
    errors: Optional[List[str]] = None,
    recent_days_applied: Optional[float] = None,
    searched_from: Optional[str] = None,
) -> str:
    """Return either JSON or text for search results."""
    sorted_records = _sort_search_records(records, sort)
    has_more = len(sorted_records) > limit
    items = sorted_records[:limit]
    next_offset = offset + len(items) if has_more else None

    if output_format == "json":
        payload: Dict[str, Any] = {
            "items": items,
            "offset": offset,
            "limit": limit,
            "returned": len(items),
            "has_more": has_more,
            "next_offset": next_offset,
            "sort": sort,
            "recent_days_applied": recent_days_applied if recent_days_applied is not None else 0.0,
            "searched_from": searched_from,
        }
        if errors:
            payload["errors"] = errors
        return json.dumps(payload)

    return _format_search_records_text(
        items,
        subject_only=subject_only,
        errors=errors,
        recent_days_applied=recent_days_applied,
    )


def _build_search_script(
    account: str,
    mailbox: str,
    subject_terms: Optional[List[str]],
    sender: Optional[str],
    has_attachments: Optional[bool],
    read_status: str,
    date_from: Optional[str],
    date_to: Optional[str],
    include_content: bool,
    content_length: int,
    offset: int,
    limit: int,
    body_text: Optional[str],
) -> str:
    """Build the AppleScript for a single account's search.

    The script caps message collection inside AppleScript via either a
    ``whose`` clause sliced down to ``items 1 thru collectLimit`` or a
    ``messages 1 thru collectLimit`` bound directly, so we never materialize
    the full message list of a large (10K+) mailbox.
    """
    escaped_sender = escape_applescript(sender) if sender else None
    use_body_search = body_text is not None

    # Build whose-clause filter conditions (only used when NOT doing body search)
    filter_conditions: List[str] = []
    if not use_body_search:
        if subject_terms:
            filter_conditions.append(contains_any_condition("subject", subject_terms))
        if sender:
            filter_conditions.append(f'sender contains "{escaped_sender}"')
        if has_attachments is not None:
            if has_attachments:
                filter_conditions.append("(count of mail attachments) > 0")
            else:
                filter_conditions.append("(count of mail attachments) = 0")
        if read_status == "read":
            filter_conditions.append("read status is true")
        elif read_status == "unread":
            filter_conditions.append("read status is false")
        if date_from:
            filter_conditions.append("date received >= fromDate")
        if date_to:
            filter_conditions.append("date received <= toDate")

    collect_limit = limit + 1  # +1 for has_more probe; offset is decremented separately
    # A1 cap includes offset because matching messages are skipped *after* binding.
    scan_cap = collect_limit + offset

    if filter_conditions:
        # A1: bind the whose-filtered list once, then immediately cap to
        # scanCap so subsequent field access doesn't materialize every
        # remaining matching message in a 24K-message Exchange mailbox.
        matching_messages_script = (
            f"set matchingMessages to (every message of currentMailbox whose "
            f"{' and '.join(filter_conditions)})\n"
            f"                                if (count of matchingMessages) > {scan_cap} then "
            f"set matchingMessages to items 1 thru {scan_cap} of matchingMessages"
        )
    else:
        # A1: no filter — still cap by binding messages 1 thru N rather than
        # `every message`, which forces Mail to enumerate the whole mailbox.
        matching_messages_script = (
            f"if (count of messages of currentMailbox) > {scan_cap} then\n"
            f"                                    set matchingMessages to messages 1 thru {scan_cap} of currentMailbox\n"
            f"                                else\n"
            f"                                    set matchingMessages to messages of currentMailbox\n"
            f"                                end if"
        )

    if mailbox == "All":
        mailbox_script = """
                set searchMailboxes to every mailbox of targetAccount
        """
        skip_script = """
                        set skipFolders to {"Trash", "Junk", "Junk Email", "Deleted Items", "Sent", "Sent Items", "Sent Messages", "Drafts", "Spam", "Deleted Messages"}
                        repeat with skipFolder in skipFolders
                            if mailboxName is skipFolder then
                                set shouldSkip to true
                                exit repeat
                            end if
                        end repeat
        """
    else:
        escaped_mailbox = escape_applescript(mailbox)
        mailbox_script = f'''
                try
                    set searchMailbox to mailbox "{escaped_mailbox}" of targetAccount
                on error
                    if "{escaped_mailbox}" is "INBOX" then
                        set searchMailbox to mailbox "Inbox" of targetAccount
                    else
                        error "Mailbox not found: {escaped_mailbox}"
                    end if
                end try
                set searchMailboxes to {{searchMailbox}}
        '''
        skip_script = ""

    date_setup = _build_applescript_date("fromDate", date_from)
    date_setup += _build_applescript_date("toDate", date_to, end_of_day=True)

    escaped_account = escape_applescript(account)
    account_setup = f'''
                set searchAccounts to {{account "{escaped_account}"}}
        '''

    # Build body search per-message filter block
    if use_body_search:
        escaped_body = escape_applescript(body_text.lower()) if body_text else ""
        # A4c: case-insensitive checks via `ignoring case`, no shell handler.
        per_msg_conditions: List[str] = []
        if subject_terms:
            subject_checks = " or ".join(
                f'messageSubject contains "{escape_applescript(t)}"'
                for t in subject_terms
            )
            per_msg_conditions.append(f"({subject_checks})")
        if sender:
            per_msg_conditions.append(
                f'messageSender contains "{escape_applescript(sender)}"'
            )
        if read_status == "read":
            per_msg_conditions.append("messageRead is true")
        elif read_status == "unread":
            per_msg_conditions.append("messageRead is false")
        if date_from:
            per_msg_conditions.append("messageDate >= fromDate")
        if date_to:
            per_msg_conditions.append("messageDate <= toDate")
        if has_attachments is True:
            per_msg_conditions.append("(count of mail attachments of aMessage) > 0")
        elif has_attachments is False:
            per_msg_conditions.append("(count of mail attachments of aMessage) = 0")

        # Body text condition is always present in body search mode
        per_msg_conditions.append(f'msgContent contains "{escaped_body}"')

        combined_condition = " and ".join(per_msg_conditions)

        # A1 + A4c: cap the candidate set via `messages 1 thru collectLimit`
        # so body search on a 24K-mailbox doesn't enumerate every message,
        # and use `ignoring case` instead of an O(N) shell-out per message.
        body_search_loop = f'''
                            set matchingMessages to {{}}
                            if (count of messages of currentMailbox) > {scan_cap} then
                                set candidateMessages to messages 1 thru {scan_cap} of currentMailbox
                            else
                                set candidateMessages to messages of currentMailbox
                            end if
                            ignoring case
                                repeat with aMessage in candidateMessages
                                    if (count of matchingMessages) >= {scan_cap} then exit repeat
                                    try
                                        set messageSubject to subject of aMessage
                                        set messageSender to sender of aMessage
                                        set messageRead to read status of aMessage
                                        set messageDate to date received of aMessage
                                        set msgContent to ""
                                        try
                                            set msgContent to content of aMessage
                                        end try
                                        if {combined_condition} then
                                            set end of matchingMessages to aMessage
                                        end if
                                    end try
                                end repeat
                            end ignoring
        '''
    else:
        body_search_loop = ""

    # Choose the message collection strategy
    if use_body_search:
        message_collection = body_search_loop
    else:
        message_collection = f"                                {matching_messages_script}"

    script = f'''
    on sanitize_field(value)
        try
            set valueText to value as string
        on error
            set valueText to ""
        end try

        set AppleScript's text item delimiters to {{return, linefeed, tab}}
        set valueParts to text items of valueText
        set AppleScript's text item delimiters to " "
        set valueText to valueParts as string
        set AppleScript's text item delimiters to "|||"
        set valueParts to text items of valueText
        set AppleScript's text item delimiters to " | "
        set valueText to valueParts as string
        set AppleScript's text item delimiters to ""
        return valueText
    end sanitize_field

    on pad2(numberValue)
        if numberValue < 10 then
            return "0" & (numberValue as string)
        end if
        return numberValue as string
    end pad2

    on month_number(monthValue)
        set monthValues to {{January, February, March, April, May, June, July, August, September, October, November, December}}
        repeat with monthIndex from 1 to 12
            if item monthIndex of monthValues is monthValue then
                return monthIndex
            end if
        end repeat
        return 0
    end month_number

    on iso_datetime(dateValue)
        set yearValue to year of dateValue as integer
        set monthValue to my month_number(month of dateValue)
        set dayValue to day of dateValue as integer
        set hourValue to hours of dateValue
        set minuteValue to minutes of dateValue
        set secondValue to seconds of dateValue
        return (yearValue as string) & "-" & my pad2(monthValue) & "-" & my pad2(dayValue) & "T" & my pad2(hourValue) & ":" & my pad2(minuteValue) & ":" & my pad2(secondValue)
    end iso_datetime

    tell application "Mail"
        with timeout of 180 seconds
            try
                set recordLines to {{}}
                set offsetRemaining to {offset}
                set collectLimit to {collect_limit}
                {date_setup}
                {account_setup}

                repeat with targetAccount in searchAccounts
                    if collectLimit <= 0 then exit repeat
                    set accountName to my sanitize_field(name of targetAccount)
                    {mailbox_script}

                    repeat with currentMailbox in searchMailboxes
                        if collectLimit <= 0 then exit repeat

                        try
                            set mailboxName to my sanitize_field(name of currentMailbox)
                            set shouldSkip to false
                            {skip_script}

                            if not shouldSkip then
                                {message_collection}
                                set matchingCount to count of matchingMessages

                                if offsetRemaining >= matchingCount then
                                    set offsetRemaining to offsetRemaining - matchingCount
                                else
                                    set startIndex to offsetRemaining + 1
                                    set availableCount to matchingCount - offsetRemaining
                                    if availableCount > collectLimit then
                                        set endIndex to startIndex + collectLimit - 1
                                    else
                                        set endIndex to startIndex + availableCount - 1
                                    end if

                                    if endIndex >= startIndex then
                                        set targetMessages to items startIndex thru endIndex of matchingMessages

                                        repeat with aMessage in targetMessages
                                            try
                                                set messageId to my sanitize_field(id of aMessage)
                                                set internetMessageId to ""
                                                try
                                                    set internetMessageId to my sanitize_field(message id of aMessage)
                                                end try
                                                set messageSubject to my sanitize_field(subject of aMessage)
                                                set messageSender to my sanitize_field(sender of aMessage)
                                                set messageRead to read status of aMessage
                                                set messageDate to date received of aMessage
                                                set receivedAt to my iso_datetime(messageDate)
                                                set contentPreview to ""

                                                if {str(include_content).lower()} then
                                                    try
                                                        set msgContent to content of aMessage
                                                        set AppleScript's text item delimiters to {{return, linefeed, tab}}
                                                        set contentParts to text items of msgContent
                                                        set AppleScript's text item delimiters to " "
                                                        set cleanText to contentParts as string
                                                        set AppleScript's text item delimiters to ""
                                                        if {content_length} > 0 and length of cleanText > {content_length} then
                                                            set contentPreview to my sanitize_field(text 1 thru {content_length} of cleanText & "...")
                                                        else
                                                            set contentPreview to my sanitize_field(cleanText)
                                                        end if
                                                    on error
                                                        set contentPreview to ""
                                                    end try
                                                end if

                                                set readValue to "false"
                                                if messageRead then
                                                    set readValue to "true"
                                                end if

                                                set recordLine to messageId & "|||" & internetMessageId & "|||" & messageSubject & "|||" & messageSender & "|||" & mailboxName & "|||" & accountName & "|||" & readValue & "|||" & receivedAt & "|||" & contentPreview
                                                set end of recordLines to recordLine
                                                set collectLimit to collectLimit - 1
                                                if collectLimit <= 0 then exit repeat
                                            end try
                                        end repeat
                                    end if

                                    set offsetRemaining to 0
                                end if
                            end if
                        on error
                            -- Skip mailboxes that cannot be searched
                        end try
                    end repeat
                end repeat

                if (count of recordLines) is 0 then
                    return ""
                end if

                set AppleScript's text item delimiters to linefeed
                set outputText to recordLines as string
                set AppleScript's text item delimiters to ""
                return outputText
            on error errMsg
                return "ERROR|||" & errMsg
            end try
        end timeout
    end tell
    '''

    return script


def _list_accounts_script() -> str:
    """Tiny AppleScript that returns one account name per line."""
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
    """Return the list of Mail account names. Cheap (<1s) on any setup."""
    raw = run_applescript(_list_accounts_script(), timeout=timeout)
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _search_one_account(
    account: str,
    mailbox: str,
    subject_terms: Optional[List[str]],
    sender: Optional[str],
    has_attachments: Optional[bool],
    read_status: str,
    date_from: Optional[str],
    date_to: Optional[str],
    include_content: bool,
    content_length: int,
    offset: int,
    limit: int,
    body_text: Optional[str],
    timeout: Optional[int],
) -> List[Dict[str, Any]]:
    """Run the search AppleScript for a single account synchronously."""
    script = _build_search_script(
        account=account,
        mailbox=mailbox,
        subject_terms=subject_terms,
        sender=sender,
        has_attachments=has_attachments,
        read_status=read_status,
        date_from=date_from,
        date_to=date_to,
        include_content=include_content,
        content_length=content_length,
        offset=offset,
        limit=limit,
        body_text=body_text,
    )
    result = run_applescript(script, timeout=timeout if timeout is not None else 180)
    if result.startswith("ERROR|||"):
        raise ValueError(result.split("|||", 1)[1])
    return _parse_search_records(result)


async def _search_mail_records(
    account: Optional[str] = None,
    mailbox: str = "INBOX",
    subject_terms: Optional[List[str]] = None,
    sender: Optional[str] = None,
    has_attachments: Optional[bool] = None,
    read_status: str = "all",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    include_content: bool = False,
    content_length: int = 300,
    offset: int = 0,
    limit: int = 100,
    sort: str = "date_desc",
    body_text: Optional[str] = None,
    timeout: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], List[str]]:
    """Return (records, error_account_names) from Apple Mail.

    When account is None, dispatches one AppleScript per account in parallel
    via ``asyncio.to_thread`` so wall time is bounded by the slowest single
    account rather than the sum. A per-account ``AppleScriptTimeout`` becomes
    an entry in the returned errors list — the call still returns whatever
    other accounts produced.
    """
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if limit <= 0:
        return [], []
    if sort not in {"date_desc", "date_asc"}:
        raise ValueError("Invalid sort. Use: date_desc, date_asc")
    if read_status not in {"all", "read", "unread"}:
        raise ValueError("Invalid read_status. Use: all, read, unread")

    # Single-account: short-circuit, no gather overhead.
    if account:
        try:
            records = await asyncio.to_thread(
                _search_one_account,
                account,
                mailbox,
                subject_terms,
                sender,
                has_attachments,
                read_status,
                date_from,
                date_to,
                include_content,
                content_length,
                offset,
                limit,
                body_text,
                timeout,
            )
            return records, []
        except AppleScriptTimeout:
            return [], [account]

    # Multi-account: fetch account list cheaply, then dispatch in parallel.
    try:
        accounts = await asyncio.to_thread(_list_mail_accounts, timeout)
    except AppleScriptTimeout:
        raise ValueError("Mail account listing timed out")

    if not accounts:
        return [], []

    async def run_one(acct: str) -> tuple[str, Any]:
        try:
            recs = await asyncio.to_thread(
                _search_one_account,
                acct,
                mailbox,
                subject_terms,
                sender,
                has_attachments,
                read_status,
                date_from,
                date_to,
                include_content,
                content_length,
                offset,
                limit,
                body_text,
                timeout,
            )
            return acct, recs
        except AppleScriptTimeout:
            return acct, AppleScriptTimeout(acct)
        except Exception as exc:
            return acct, exc

    results = await asyncio.gather(*(run_one(acct) for acct in accounts))

    combined: List[Dict[str, Any]] = []
    errors: List[str] = []
    for acct, outcome in results:
        if isinstance(outcome, AppleScriptTimeout):
            errors.append(acct)
        elif isinstance(outcome, Exception):
            # Treat unexpected per-account errors as soft failures too — caller
            # still gets partial data plus the account name in errors.
            errors.append(acct)
        else:
            combined.extend(outcome)

    return combined, errors


def _search_mail_records_sync(**kwargs) -> List[Dict[str, Any]]:
    """Synchronous bridge for sync tools (move_email, manage_trash,
    list_email_attachments) that need preflight records. Returns just the
    record list. When a per-account ``AppleScriptTimeout`` was caught
    inside the async helper, re-raise it here so sync callers can surface
    a structured "timed out" error rather than silently treating it as
    "no matches". Sync callers should pass an explicit ``account`` so this
    stays a single-account dispatch and avoids the multi-account gather
    path."""
    account = kwargs.get("account")
    if account:
        try:
            return _search_one_account(
                account=account,
                mailbox=kwargs.get("mailbox", "INBOX"),
                subject_terms=kwargs.get("subject_terms"),
                sender=kwargs.get("sender"),
                has_attachments=kwargs.get("has_attachments"),
                read_status=kwargs.get("read_status", "all"),
                date_from=kwargs.get("date_from"),
                date_to=kwargs.get("date_to"),
                include_content=kwargs.get("include_content", False),
                content_length=kwargs.get("content_length", 300),
                offset=kwargs.get("offset", 0),
                limit=kwargs.get("limit", 100),
                body_text=kwargs.get("body_text"),
                timeout=kwargs.get("timeout"),
            )
        except AppleScriptTimeout:
            raise

    records, errors = asyncio.run(_search_mail_records(**kwargs))
    if errors and not records:
        raise AppleScriptTimeout(
            f"AppleScript timed out for account(s): {', '.join(errors)}"
        )
    return records


@mcp.tool()
@inject_preferences
async def search_emails(
    account: Optional[str] = None,
    all_accounts: bool = False,
    mailbox: str = "INBOX",
    subject_keyword: Optional[str] = None,
    subject_keywords: Optional[List[str]] = None,
    sender: Optional[str] = None,
    has_attachments: Optional[bool] = None,
    read_status: str = "all",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    recent_days: float = 2.0,
    include_content: bool = False,
    max_content_length: int = 500,
    body_text: Optional[str] = None,
    max_results: Optional[int] = 20,
    output_format: str = "text",
    offset: int = 0,
    limit: Optional[int] = None,
    sort: str = "date_desc",
    timeout: Optional[int] = None,
) -> str:
    """Defaults to the last 48 hours and the configured default account. Pass `recent_days=7` for the past week, `recent_days=0` for the full inbox, `all_accounts=True` to search every account.

    Unified search tool with JSON output, pagination, and real date filtering.

    Consolidates subject search, sender search, body content search, and
    cross-account search into a single tool.

    Smart defaults:
        - When `date_from` is None and `recent_days > 0`, an effective window
          of `now - recent_days` days is applied. Set `recent_days=0` for an
          unbounded full-inbox sweep. An explicit `date_from` always wins.
        - When `account` is None and `all_accounts` is False, the tool falls
          back to the ``DEFAULT_MAIL_ACCOUNT`` env-configured account if one
          is set. Pass `all_accounts=True` to opt back into multi-account
          dispatch even when a default is configured.
        - `recent_days` is applied BEFORE pagination, so `offset` counts
          within the windowed result set.

    Performance guidance (read before omitting filters on large mailboxes):
        - Multi-account search (account=None) on a 10K+ inbox can be slow.
          Prefer passing `account` plus `date_from` together when you know
          which mailbox the messages are in.
        - body_text=True is O(N x message-size) — pair it with tight other
          filters (account, date_from, subject_keyword) to keep wall time
          predictable on Exchange / Gmail accounts with deep history.
        - When account is None each account runs in parallel; one slow
          account no longer blocks the others, but its name will appear in
          the response's `errors` field (JSON) or partial banner (text) so
          you can retry it alone with a longer `timeout`.

    Args:
        account: Account name to search in (e.g., "Gmail", "Work").
            If None, searches ALL accounts in parallel (slower wall time on
            very large inboxes — prefer specifying account + date_from).
        mailbox: Mailbox to search (default: "INBOX", use "All" for all mailboxes, or specific folder name)
        subject_keyword: Optional keyword to search in subject
        subject_keywords: Optional list of subject keywords; matches any keyword
        sender: Optional sender email or name to filter by
        has_attachments: Optional filter for emails with attachments (True/False/None)
        read_status: Filter by read status: "all", "read", "unread" (default: "all")
        date_from: Optional start date filter (format: "YYYY-MM-DD")
        date_to: Optional end date filter (format: "YYYY-MM-DD")
        include_content: Whether to include email content preview (slower)
        max_content_length: Maximum content length in characters when include_content=True (default: 500, 0 = unlimited)
        body_text: Optional text to search for in email body content (case-insensitive).
            WARNING: body search is significantly slower as it reads each message body.
            Always combine with account + date_from for inboxes over a few thousand messages.
        max_results: Backward-compatible alias for limit
        output_format: Output format: "text" or "json" (default: "text")
        offset: Number of matching results to skip before returning data
        limit: Maximum number of results to return per page
        sort: Result sort order: "date_desc" or "date_asc"
        timeout: Optional per-account AppleScript timeout in seconds. Defaults
            to 180s. Raise this for known-slow accounts (e.g. large Exchange
            inboxes) when the default times out.

    Returns:
        Formatted list of matching emails or JSON payload with stable message
        metadata. When one or more accounts time out during a multi-account
        call, the response includes the slow account names so the caller can
        retry them individually with a larger `timeout`.
    """
    if output_format not in {"text", "json"}:
        return "Error: Invalid output_format. Use: text, json"

    if limit is None:
        limit = max_results if max_results is not None else 100

    # Smart default: fall back to the configured default account when neither
    # `account` nor `all_accounts` is set. Lazy attribute read so tests can
    # monkeypatch `apple_mail_mcp.server.DEFAULT_MAIL_ACCOUNT` after import.
    if account is None and not all_accounts and _server.DEFAULT_MAIL_ACCOUNT:
        account = _server.DEFAULT_MAIL_ACCOUNT

    # Smart default: 48h window when no explicit start date was passed.
    effective_recent_days = float(recent_days) if recent_days else 0.0
    searched_from: Optional[str] = None
    if date_from is None and effective_recent_days > 0:
        cutoff = datetime.now() - timedelta(days=effective_recent_days)
        date_from = cutoff.strftime("%Y-%m-%d")
        searched_from = date_from
    elif date_from is not None:
        # Explicit caller override — effective window is 0 for reporting purposes.
        effective_recent_days = 0.0
        searched_from = date_from

    subject_terms = normalize_search_terms(subject_keyword, subject_keywords)

    try:
        records, errors = await _search_mail_records(
            account=account,
            mailbox=mailbox,
            subject_terms=subject_terms,
            sender=sender,
            has_attachments=has_attachments,
            read_status=read_status,
            date_from=date_from,
            date_to=date_to,
            include_content=include_content,
            content_length=max_content_length,
            offset=offset,
            limit=limit,
            sort=sort,
            body_text=body_text,
            timeout=timeout,
        )
        return _build_search_response(
            records,
            offset=offset,
            limit=limit,
            sort=sort,
            output_format=output_format,
            subject_only=False,
            errors=errors or None,
            recent_days_applied=effective_recent_days,
            searched_from=searched_from,
        )
    except ValueError as exc:
        return f"Error: {exc}"


@mcp.tool()
@inject_preferences
def get_email_by_id(
    account: str,
    message_id: str,
    mailbox: str = "INBOX",
    include_content: bool = True,
    max_content_length: int = 5000,
    output_format: str = "text",
) -> str:
    """
    Fetch one email by its exact Apple Mail message id.

    Use this after `search_emails` returns a `message_id` when you need the
    full message body or stable metadata without running another broad subject
    search.

    Args:
        account: Account name to search in (e.g., "Gmail", "Work").
        message_id: Exact numeric Apple Mail message id returned by search tools.
        mailbox: Mailbox to search in (default: "INBOX").
        include_content: Whether to include email content (default: True).
        max_content_length: Maximum content characters to return when include_content=True.
        output_format: Output format: "text" or "json" (default: "text").

    Returns:
        One matching email as text, or JSON with {"item": ...}. If no message is
        found, JSON returns {"item": null}.
    """
    if output_format not in {"text", "json"}:
        return "Error: Invalid output_format. Use: text, json"

    normalized_ids = normalize_message_ids([message_id])
    if not normalized_ids:
        return "Error: message_id must be a numeric Apple Mail message id"

    if max_content_length < 0:
        return "Error: max_content_length must be >= 0"

    safe_account = escape_applescript(account)
    numeric_id = normalized_ids[0]

    script = f'''
    on sanitize_field(value)
        try
            set valueText to value as string
        on error
            set valueText to ""
        end try

        set AppleScript's text item delimiters to {{return, linefeed, tab}}
        set valueParts to text items of valueText
        set AppleScript's text item delimiters to " "
        set valueText to valueParts as string
        set AppleScript's text item delimiters to "|||"
        set valueParts to text items of valueText
        set AppleScript's text item delimiters to " | "
        set valueText to valueParts as string
        set AppleScript's text item delimiters to ""
        return valueText
    end sanitize_field

    on pad2(numberValue)
        if numberValue < 10 then
            return "0" & (numberValue as string)
        end if
        return numberValue as string
    end pad2

    on month_number(monthValue)
        set monthValues to {{January, February, March, April, May, June, July, August, September, October, November, December}}
        repeat with monthIndex from 1 to 12
            if item monthIndex of monthValues is monthValue then
                return monthIndex
            end if
        end repeat
        return 0
    end month_number

    on iso_datetime(dateValue)
        set yearValue to year of dateValue as integer
        set monthValue to my month_number(month of dateValue)
        set dayValue to day of dateValue as integer
        set hourValue to hours of dateValue
        set minuteValue to minutes of dateValue
        set secondValue to seconds of dateValue
        return (yearValue as string) & "-" & my pad2(monthValue) & "-" & my pad2(dayValue) & "T" & my pad2(hourValue) & ":" & my pad2(minuteValue) & ":" & my pad2(secondValue)
    end iso_datetime

    tell application "Mail"
        with timeout of 120 seconds
            try
                set targetAccount to account "{safe_account}"
                {build_mailbox_ref(mailbox, var_name="targetMailbox")}
                set targetMessages to every message of targetMailbox whose id is {numeric_id}

                if (count of targetMessages) is 0 then
                    return ""
                end if

                set aMessage to item 1 of targetMessages
                set messageId to my sanitize_field(id of aMessage)
                set internetMessageId to ""
                try
                    set internetMessageId to my sanitize_field(message id of aMessage)
                end try
                set messageSubject to my sanitize_field(subject of aMessage)
                set messageSender to my sanitize_field(sender of aMessage)
                set messageRead to read status of aMessage
                set messageDate to date received of aMessage
                set receivedAt to my iso_datetime(messageDate)
                set mailboxName to my sanitize_field(name of targetMailbox)
                set accountName to my sanitize_field(name of targetAccount)
                set contentPreview to ""

                if {str(include_content).lower()} then
                    try
                        set msgContent to content of aMessage
                        set AppleScript's text item delimiters to {{return, linefeed, tab}}
                        set contentParts to text items of msgContent
                        set AppleScript's text item delimiters to " "
                        set cleanText to contentParts as string
                        set AppleScript's text item delimiters to ""
                        if {max_content_length} > 0 and length of cleanText > {max_content_length} then
                            set contentPreview to my sanitize_field(text 1 thru {max_content_length} of cleanText & "...")
                        else
                            set contentPreview to my sanitize_field(cleanText)
                        end if
                    end try
                end if

                set readValue to "false"
                if messageRead then
                    set readValue to "true"
                end if

                return messageId & "|||" & internetMessageId & "|||" & messageSubject & "|||" & messageSender & "|||" & mailboxName & "|||" & accountName & "|||" & readValue & "|||" & receivedAt & "|||" & contentPreview
            on error errMsg
                return "ERROR|||" & errMsg
            end try
        end timeout
    end tell
    '''

    result = run_applescript(script, timeout=120)
    if result.startswith("ERROR|||"):
        return f"Error: {result.split('|||', 1)[1]}"

    records = _parse_search_records(result)
    item = records[0] if records else None
    if output_format == "json":
        return json.dumps({"item": item})

    if item is None:
        return f"No email found for message_id={numeric_id} in {mailbox}"
    return _format_search_records_text([item])


@mcp.tool()
@inject_preferences
def get_email_thread(
    account: str, subject_keyword: str, mailbox: str = "INBOX", max_messages: int = 50
) -> str:
    """
    Get an email conversation thread - all messages with the same or similar subject.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        subject_keyword: Keyword to identify the thread (e.g., "Re: Project Update")
        mailbox: Mailbox to search in (default: "INBOX", use "All" for all mailboxes)
        max_messages: Maximum number of thread messages to return (default: 50)

    Returns:
        Formatted thread view with all related messages sorted by date
    """

    # Escape user inputs for AppleScript
    escaped_account = escape_applescript(account)
    escaped_mailbox = escape_applescript(mailbox)

    # For thread detection, we'll strip common prefixes
    thread_keywords = ["Re:", "Fwd:", "FW:", "RE:", "Fw:"]
    cleaned_keyword = subject_keyword
    for prefix in thread_keywords:
        cleaned_keyword = cleaned_keyword.replace(prefix, "").strip()
    escaped_keyword = escape_applescript(cleaned_keyword)

    mailbox_script = f'''
        try
            set searchMailbox to mailbox "{escaped_mailbox}" of targetAccount
        on error
            if "{escaped_mailbox}" is "INBOX" then
                set searchMailbox to mailbox "Inbox" of targetAccount
            else if "{escaped_mailbox}" is "All" then
                set searchMailboxes to every mailbox of targetAccount
                set useAllMailboxes to true
            else
                error "Mailbox not found: {escaped_mailbox}"
            end if
        end try

        if "{escaped_mailbox}" is not "All" then
            set searchMailboxes to {{searchMailbox}}
            set useAllMailboxes to false
        end if
    '''

    script = f'''
    tell application "Mail"
        set outputText to "EMAIL THREAD VIEW" & return & return
        set outputText to outputText & "Thread topic: {escaped_keyword}" & return
        set outputText to outputText & "Account: {escaped_account}" & return & return
        set threadMessages to {{}}

        try
            set targetAccount to account "{escaped_account}"
            {mailbox_script}

            -- Collect all matching messages from all mailboxes
            repeat with currentMailbox in searchMailboxes
                set mailboxMessages to every message of currentMailbox

                repeat with aMessage in mailboxMessages
                    if (count of threadMessages) >= {max_messages} then exit repeat

                    try
                        set messageSubject to subject of aMessage

                        -- Remove common prefixes for matching
                        set cleanSubject to messageSubject
                        if cleanSubject starts with "Re: " then
                            set cleanSubject to text 5 thru -1 of cleanSubject
                        end if
                        if cleanSubject starts with "RE: " then
                            set cleanSubject to text 5 thru -1 of cleanSubject
                        end if
                        if cleanSubject starts with "Fwd: " then
                            set cleanSubject to text 6 thru -1 of cleanSubject
                        else if cleanSubject starts with "FW: " then
                            set cleanSubject to text 5 thru -1 of cleanSubject
                        else if cleanSubject starts with "Fw: " then
                            set cleanSubject to text 5 thru -1 of cleanSubject
                        end if

                        -- Check if this message is part of the thread
                        if cleanSubject contains "{escaped_keyword}" or messageSubject contains "{escaped_keyword}" then
                            set end of threadMessages to aMessage
                        end if
                    end try
                end repeat
            end repeat

            -- Display thread messages
            set messageCount to count of threadMessages
            set outputText to outputText & "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" & return
            set outputText to outputText & "FOUND " & messageCount & " MESSAGE(S) IN THREAD" & return
            set outputText to outputText & "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" & return & return

            repeat with aMessage in threadMessages
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

                    -- Get content preview
                    try
                        set msgContent to content of aMessage
                        set AppleScript's text item delimiters to {{return, linefeed}}
                        set contentParts to text items of msgContent
                        set AppleScript's text item delimiters to " "
                        set cleanText to contentParts as string
                        set AppleScript's text item delimiters to ""

                        if length of cleanText > 150 then
                            set contentPreview to text 1 thru 150 of cleanText & "..."
                        else
                            set contentPreview to cleanText
                        end if

                        set outputText to outputText & "   Preview: " & contentPreview & return
                    end try

                    set outputText to outputText & return
                end try
            end repeat

        on error errMsg
            return "Error: " & errMsg
        end try

        return outputText
    end tell
    '''

    result = run_applescript(script)
    return result

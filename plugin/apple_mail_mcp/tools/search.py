"""Search tools: finding and filtering emails."""

import json
import os
import re
from datetime import datetime
from typing import Optional, List, Dict, Any
from urllib.parse import quote

from apple_mail_mcp.server import mcp
from apple_mail_mcp.constants import FLAG_COLOR_NAMES
from apple_mail_mcp.core import (
    contains_any_condition,
    inject_preferences,
    escape_applescript,
    normalize_search_terms,
    resolve_flag_color,
    read_flag_index_script,
    run_applescript,
    LOWERCASE_HANDLER,
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
        parts = line.split("|||", 9)
        if len(parts) < 9:
            continue

        internet_message_id = parts[1].strip()
        try:
            flag_index = int(parts[8].strip())
        except ValueError:
            flag_index = -1
        record = {
            "message_id": parts[0].strip(),
            "internet_message_id": internet_message_id,
            "subject": parts[2].strip(),
            "sender": parts[3].strip(),
            "mailbox": parts[4].strip(),
            "account": parts[5].strip(),
            "is_read": parts[6].strip().lower() == "true",
            "received_date": parts[7].strip(),
            "is_flagged": flag_index >= 0,
        }
        if flag_index in FLAG_COLOR_NAMES:
            record["flag_color"] = FLAG_COLOR_NAMES[flag_index]
        if internet_message_id:
            # Apple Mail requires: message:// scheme, angle brackets (percent-encoded),
            # and raw @ in the Message-ID. Normalize ID in case angle brackets are
            # present or missing (AppleScript returns both forms).
            msg_id = internet_message_id.strip("<>")
            record["mail_link"] = f"message://%3C{quote(msg_id, safe='@')}%3E"
        if len(parts) > 9 and parts[9].strip():
            record["content_preview"] = parts[9].strip()
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
        lines.append("")
        for item in records:
            indicator = "\u2713" if item["is_read"] else "\u2709"
            subject_line = f"{indicator} {item['subject']}"
            if item.get("flag_color"):
                subject_line += f" \u2691 {item['flag_color']}"
            elif item.get("is_flagged"):
                subject_line += " \u2691"
            lines.append(subject_line)
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
    lines.append("========================================")
    return "\n".join(lines)


def _build_search_response(
    records: List[Dict[str, Any]],
    offset: int,
    limit: int,
    sort: str,
    output_format: str,
    subject_only: bool = False,
) -> str:
    """Return either JSON or text for search results."""
    sorted_records = _sort_search_records(records, sort)
    has_more = len(sorted_records) > limit
    items = sorted_records[:limit]
    next_offset = offset + len(items) if has_more else None

    if output_format == "json":
        return json.dumps(
            {
                "items": items,
                "offset": offset,
                "limit": limit,
                "returned": len(items),
                "has_more": has_more,
                "next_offset": next_offset,
                "sort": sort,
            }
        )

    return _format_search_records_text(items, subject_only=subject_only)


def _search_mail_records(
    account: Optional[str] = None,
    mailbox: str = "INBOX",
    subject_terms: Optional[List[str]] = None,
    sender: Optional[str] = None,
    has_attachments: Optional[bool] = None,
    flagged: Optional[bool] = None,
    flag_color: Optional[str] = None,
    read_status: str = "all",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    include_content: bool = False,
    content_length: int = 300,
    offset: int = 0,
    limit: int = 100,
    sort: str = "date_desc",
    body_text: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return structured search records from Apple Mail.

    When account is None, iterates all accounts.
    When body_text is provided, uses per-message iteration with case-insensitive
    content matching (slower than subject/sender-only searches).
    """
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if limit <= 0:
        return []
    if sort not in {"date_desc", "date_asc"}:
        raise ValueError("Invalid sort. Use: date_desc, date_asc")
    if read_status not in {"all", "read", "unread"}:
        raise ValueError("Invalid read_status. Use: all, read, unread")

    flag_index: Optional[int] = None
    if flag_color is not None:
        flag_index = resolve_flag_color(flag_color)
        if flagged is False:
            raise ValueError(
                "flag_color cannot be combined with flagged=False "
                "(a colored flag implies the message is flagged)"
            )

    escaped_sender = escape_applescript(sender) if sender else None

    # When body_text is provided, we must iterate per-message (can't use whose clause)
    use_body_search = body_text is not None

    # Build whose-clause filter conditions (only used when NOT doing body search)
    filter_conditions = []
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
        if flag_index is not None:
            # flag index survives unflagging; require the active-flag boolean
            # so residual indexes on unflagged messages don't match.
            filter_conditions.append(
                f"(flagged status is true and flag index is {flag_index})"
            )
        elif flagged is not None:
            filter_conditions.append(
                f"flagged status is {'true' if flagged else 'false'}"
            )
        if read_status == "read":
            filter_conditions.append("read status is true")
        elif read_status == "unread":
            filter_conditions.append("read status is false")
        if date_from:
            filter_conditions.append("date received >= fromDate")
        if date_to:
            filter_conditions.append("date received <= toDate")

    if filter_conditions:
        matching_messages_script = f"set matchingMessages to every message of currentMailbox whose {' and '.join(filter_conditions)}"
    else:
        matching_messages_script = (
            "set matchingMessages to every message of currentMailbox"
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

    # Build account iteration
    if account:
        escaped_account = escape_applescript(account)
        account_setup = f'''
                set searchAccounts to {{account "{escaped_account}"}}
        '''
    else:
        account_setup = """
                set searchAccounts to every account
        """

    # Build body search per-message filter block
    if use_body_search:
        escaped_body = escape_applescript(body_text.lower()) if body_text else ""
        # Only pay the per-message flag-index read when a flag filter needs it.
        flag_read_script = ""
        if flag_index is not None or flagged is not None:
            flag_read_script = read_flag_index_script()
        # Build per-message conditions for subject, sender, read_status, dates, attachments
        per_msg_conditions = []
        if subject_terms:
            # Case-insensitive subject check
            subject_checks = " or ".join(
                f'lowerSubject contains "{escape_applescript(t.lower())}"'
                for t in subject_terms
            )
            per_msg_conditions.append(f"({subject_checks})")
        if sender:
            per_msg_conditions.append(f'lowerSender contains "{escape_applescript(sender.lower())}"')
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
        if flag_index is not None:
            per_msg_conditions.append(f"messageFlagIndex is {flag_index}")
        elif flagged is True:
            per_msg_conditions.append("messageFlagIndex is not -1")
        elif flagged is False:
            per_msg_conditions.append("messageFlagIndex is -1")

        # Body text condition is always present in body search mode
        per_msg_conditions.append(f'lowerContent contains "{escaped_body}"')

        combined_condition = " and ".join(per_msg_conditions)

        body_search_loop = f'''
                            set matchingMessages to {{}}
                            set allMessages to every message of currentMailbox
                            repeat with aMessage in allMessages
                                if collectLimit <= 0 then exit repeat
                                try
                                    set messageSubject to subject of aMessage
                                    set messageSender to sender of aMessage
                                    set messageRead to read status of aMessage
                                    set messageDate to date received of aMessage
                                    {flag_read_script}
                                    set lowerSubject to my lowercase(messageSubject)
                                    set lowerSender to my lowercase(messageSender)
                                    set msgContent to ""
                                    try
                                        set msgContent to content of aMessage
                                    end try
                                    set lowerContent to my lowercase(msgContent)
                                    if {combined_condition} then
                                        set end of matchingMessages to aMessage
                                    end if
                                end try
                            end repeat
        '''
    else:
        body_search_loop = ""

    # Choose the message collection strategy
    if use_body_search:
        message_collection = body_search_loop
    else:
        message_collection = f"                            {matching_messages_script}"

    lowercase_handler = LOWERCASE_HANDLER if use_body_search else ""

    script = f'''
    {lowercase_handler}

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
                set collectLimit to {limit + 1}
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
                                                {read_flag_index_script()}
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

                                                set recordLine to messageId & "|||" & internetMessageId & "|||" & messageSubject & "|||" & messageSender & "|||" & mailboxName & "|||" & accountName & "|||" & readValue & "|||" & receivedAt & "|||" & (messageFlagIndex as string) & "|||" & contentPreview
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

    result = run_applescript(script, timeout=180)
    if result.startswith("ERROR|||"):
        raise ValueError(result.split("|||", 1)[1])

    return _parse_search_records(result)


@mcp.tool()
@inject_preferences
def search_emails(
    account: Optional[str] = None,
    mailbox: str = "INBOX",
    subject_keyword: Optional[str] = None,
    subject_keywords: Optional[List[str]] = None,
    sender: Optional[str] = None,
    has_attachments: Optional[bool] = None,
    flagged: Optional[bool] = None,
    flag_color: Optional[str] = None,
    read_status: str = "all",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    include_content: bool = False,
    max_content_length: int = 500,
    body_text: Optional[str] = None,
    max_results: Optional[int] = 20,
    output_format: str = "text",
    offset: int = 0,
    limit: Optional[int] = None,
    sort: str = "date_desc",
) -> str:
    """
    Unified search tool with JSON output, pagination, and real date filtering.

    Consolidates subject search, sender search, body content search, and
    cross-account search into a single tool.

    Args:
        account: Account name to search in (e.g., "Gmail", "Work").
            If None, searches ALL accounts (slower).
        mailbox: Mailbox to search (default: "INBOX", use "All" for all mailboxes, or specific folder name)
        subject_keyword: Optional keyword to search in subject
        subject_keywords: Optional list of subject keywords; matches any keyword
        sender: Optional sender email or name to filter by
        has_attachments: Optional filter for emails with attachments (True/False/None)
        flagged: Optional filter for flagged emails (True/False/None)
        flag_color: Optional filter for a specific flag color: "red", "orange",
            "yellow", "green", "blue", "purple", or "gray". Implies flagged=True.
        read_status: Filter by read status: "all", "read", "unread" (default: "all")
        date_from: Optional start date filter (format: "YYYY-MM-DD")
        date_to: Optional end date filter (format: "YYYY-MM-DD")
        include_content: Whether to include email content preview (slower)
        max_content_length: Maximum content length in characters when include_content=True (default: 500, 0 = unlimited)
        body_text: Optional text to search for in email body content (case-insensitive).
            WARNING: body search is significantly slower as it reads each message body.
        max_results: Backward-compatible alias for limit
        output_format: Output format: "text" or "json" (default: "text")
        offset: Number of matching results to skip before returning data
        limit: Maximum number of results to return per page
        sort: Result sort order: "date_desc" or "date_asc"

    Returns:
        Formatted list of matching emails or JSON payload with stable message metadata
    """
    if output_format not in {"text", "json"}:
        return "Error: Invalid output_format. Use: text, json"

    if limit is None:
        limit = max_results if max_results is not None else 100

    subject_terms = normalize_search_terms(subject_keyword, subject_keywords)

    try:
        records = _search_mail_records(
            account=account,
            mailbox=mailbox,
            subject_terms=subject_terms,
            sender=sender,
            has_attachments=has_attachments,
            flagged=flagged,
            flag_color=flag_color,
            read_status=read_status,
            date_from=date_from,
            date_to=date_to,
            include_content=include_content,
            content_length=max_content_length,
            offset=offset,
            limit=limit,
            sort=sort,
            body_text=body_text,
        )
        return _build_search_response(
            records,
            offset=offset,
            limit=limit,
            sort=sort,
            output_format=output_format,
            subject_only=False,
        )
    except ValueError as exc:
        return f"Error: {exc}"


_THREAD_PREFIX_RE = re.compile(r"^\s*(re|aw|fwd|fw|wg)\s*(\[\d+\])?\s*:\s*", re.IGNORECASE)
_MESSAGE_ID_RE = re.compile(r"<([^<>@\s]+@[^<>\s]+)>")
_REFERENCE_HEADER_RE = re.compile(
    r"^(?:references|in-reply-to)\s*:(.*?)(?=^\S|\Z)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)


def _strip_thread_prefixes(subject: str) -> str:
    """Strip repeated Re:/AW:/Fwd:/WG: prefixes from a subject."""
    cleaned = (subject or "").strip()
    while True:
        stripped = _THREAD_PREFIX_RE.sub("", cleaned, count=1)
        if stripped == cleaned:
            return cleaned.strip()
        cleaned = stripped.strip()


def _referenced_ids(headers: str) -> set:
    """Return every Message-ID referenced by In-Reply-To / References."""
    found = set()
    for block in _REFERENCE_HEADER_RE.findall(headers or ""):
        found.update(_MESSAGE_ID_RE.findall(block))
    return found


def _collect_thread_candidates(
    account: str, mailbox: str, cleaned_keyword: str, max_messages: int
):
    """Return (records, error) for messages whose subject carries the keyword.

    Each record holds the fields needed to display a message plus the raw
    headers used to work out who is actually talking to whom.
    """
    separator = "<<<AMMCP-" + os.urandom(8).hex() + ">>>"
    row_separator = "<<<AMMCPROW-" + os.urandom(8).hex() + ">>>"
    safe_account = escape_applescript(account)
    safe_keyword = escape_applescript(cleaned_keyword)
    safe_mailbox = escape_applescript(mailbox)

    if mailbox == "All":
        mailbox_setup = "set searchMailboxes to every mailbox of targetAccount"
    else:
        mailbox_setup = f'''try
                set searchMailboxes to {{mailbox "{safe_mailbox}" of targetAccount}}
            on error
                if "{safe_mailbox}" is "INBOX" then
                    set searchMailboxes to {{mailbox "Inbox" of targetAccount}}
                else
                    error "Mailbox not found: {safe_mailbox}"
                end if
            end try'''

    script = f'''
    tell application "Mail"
        with timeout of 300 seconds
            try
                set targetAccount to account "{safe_account}"
                {mailbox_setup}

                set collected to 0
                set outputText to ""

                repeat with currentMailbox in searchMailboxes
                    if collected >= {int(max_messages)} then exit repeat
                    try
                        -- `whose` filters inside Mail; walking every message
                        -- over Apple Events takes minutes on a big archive.
                        set candidates to (messages of currentMailbox whose subject contains "{safe_keyword}")
                        repeat with aMessage in candidates
                            if collected >= {int(max_messages)} then exit repeat
                            try
                                set headerText to ""
                                try
                                    set headerText to all headers of aMessage
                                end try
                                set messageIdText to ""
                                try
                                    set messageIdText to message id of aMessage
                                end try

                                set previewText to ""
                                try
                                    set rawContent to content of aMessage
                                    set AppleScript's text item delimiters to {{return, linefeed, tab}}
                                    set contentParts to text items of rawContent
                                    set AppleScript's text item delimiters to " "
                                    set previewText to contentParts as string
                                    set AppleScript's text item delimiters to ""
                                    if length of previewText > 150 then
                                        set previewText to text 1 thru 150 of previewText & "..."
                                    end if
                                end try

                                set outputText to outputText & messageIdText & "{separator}" & ¬
                                    (subject of aMessage) & "{separator}" & ¬
                                    (sender of aMessage) & "{separator}" & ¬
                                    ((date received of aMessage) as string) & "{separator}" & ¬
                                    (((date received of aMessage) - (current date)) as text) & "{separator}" & ¬
                                    ((read status of aMessage) as text) & "{separator}" & ¬
                                    (name of currentMailbox) & "{separator}" & ¬
                                    previewText & "{separator}" & ¬
                                    headerText & "{row_separator}"
                                set collected to collected + 1
                            end try
                        end repeat
                    end try
                end repeat

                return outputText
            on error errMsg
                return "ERROR{separator}" & errMsg
            end try
        end timeout
    end tell
    '''

    raw = run_applescript(script, timeout=300) or ""
    if raw.startswith("ERROR" + separator):
        return [], "Error: " + raw.split(separator, 1)[1].strip()

    records = []
    for row in raw.split(row_separator):
        if not row.strip():
            continue
        parts = row.split(separator)
        if len(parts) < 9:
            continue
        try:
            age_seconds = int(float(parts[4].strip()))
        except ValueError:
            age_seconds = 0
        records.append(
            {
                "message_id": parts[0].strip().strip("<>"),
                "subject": parts[1].strip(),
                "sender": parts[2].strip(),
                "date": parts[3].strip(),
                "age_seconds": age_seconds,
                "read": parts[5].strip().lower() == "true",
                "mailbox": parts[6].strip(),
                "preview": parts[7].strip(),
                "references": _referenced_ids(separator.join(parts[8:])),
            }
        )
    records.sort(key=lambda record: record["age_seconds"])
    return records, None


def _split_thread_by_linkage(records: List[Dict[str, Any]]):
    """Split candidates into the real thread and same-subject strangers.

    The newest candidate seeds the thread; everything reachable from it
    through Message-ID references belongs to it. A message without any
    Message-ID at all stays in the thread — dropping it would hide mail that
    the old subject-only grouping did show.
    """
    if not records:
        return [], []

    # Sort here rather than trusting the caller: the seed must be the newest
    # message, otherwise the thread is grown from the wrong end.
    records = sorted(records, key=lambda record: record["age_seconds"])
    seed = records[-1]
    thread_ids = set()
    if seed["message_id"]:
        thread_ids.add(seed["message_id"])
    thread_ids.update(seed["references"])

    # Repeat until nothing new joins: a reply can reference a message that
    # itself only joins the thread later in the list.
    linked = [seed]
    remaining = [record for record in records if record is not seed]
    changed = True
    while changed:
        changed = False
        for record in list(remaining):
            own_id = record["message_id"]
            if (own_id and own_id in thread_ids) or (record["references"] & thread_ids):
                linked.append(record)
                remaining.remove(record)
                if own_id:
                    thread_ids.add(own_id)
                thread_ids.update(record["references"])
                changed = True

    for record in list(remaining):
        if not record["message_id"] and not record["references"]:
            linked.append(record)
            remaining.remove(record)

    linked.sort(key=lambda record: record["age_seconds"])
    remaining.sort(key=lambda record: record["age_seconds"])
    return linked, remaining


def _format_thread_record(record: Dict[str, Any]) -> List[str]:
    indicator = "✓" if record["read"] else "✉"
    lines = [
        f"{indicator} {record['subject']}",
        f"   From: {record['sender']}",
        f"   Date: {record['date']}",
    ]
    if record["mailbox"]:
        lines.append(f"   Mailbox: {record['mailbox']}")
    if record["preview"]:
        lines.append(f"   Preview: {record['preview']}")
    lines.append("")
    return lines


@mcp.tool()
@inject_preferences
def get_email_thread(
    account: str, subject_keyword: str, mailbox: str = "INBOX", max_messages: int = 50
) -> str:
    """
    Get an email conversation thread - messages linked by Message-ID, not just by subject.

    Candidates are found by subject (fast, filtered inside Mail), then linked
    through their Message-ID / In-Reply-To / References headers. Messages that
    merely share the subject but belong to a different conversation are listed
    separately instead of being mixed into the thread.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        subject_keyword: Keyword to identify the thread (e.g., "Re: Project Update")
        mailbox: Mailbox to search in (default: "INBOX", use "All" for all mailboxes)
        max_messages: Maximum number of candidate messages to inspect (default: 50)

    Returns:
        Formatted thread view sorted oldest first, with unlinked same-subject
        messages called out separately
    """
    cleaned_keyword = _strip_thread_prefixes(subject_keyword)
    if not cleaned_keyword:
        return "Error: 'subject_keyword' is empty after stripping Re:/Fwd: prefixes"

    records, error = _collect_thread_candidates(
        account, mailbox, cleaned_keyword, max_messages
    )
    if error:
        return error
    if not records:
        return (
            f"EMAIL THREAD VIEW\n\nThread topic: {cleaned_keyword}\n"
            f"Account: {account}\n\nNo message found matching: {subject_keyword} "
            f"(searched mailbox: {mailbox})"
        )

    linked, unlinked = _split_thread_by_linkage(records)

    lines = [
        "EMAIL THREAD VIEW",
        "",
        f"Thread topic: {cleaned_keyword}",
        f"Account: {account}",
        "",
        "━" * 40,
        f"FOUND {len(linked)} MESSAGE(S) IN THREAD",
        "━" * 40,
        "",
    ]
    for record in linked:
        lines.extend(_format_thread_record(record))

    if unlinked:
        lines.append("━" * 40)
        lines.append(
            f"{len(unlinked)} MESSAGE(S) WITH THE SAME SUBJECT BUT NO LINK TO THIS THREAD"
        )
        lines.append("━" * 40)
        lines.append("")
        for record in unlinked:
            lines.extend(_format_thread_record(record))

    return "\n".join(lines).rstrip() + "\n"

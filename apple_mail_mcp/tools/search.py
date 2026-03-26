"""Search tools: finding and filtering emails."""

import json
import re
from datetime import datetime
from typing import Optional, List, Dict, Any
from urllib.parse import quote

from apple_mail_mcp.server import mcp
from apple_mail_mcp.core import (
    contains_any_condition,
    inject_preferences,
    escape_applescript,
    normalize_search_terms,
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
            record["mail_link"] = "message:" + quote(internet_message_id, safe="")
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
            indicator = "✓" if item["is_read"] else "✉"
            lines.append(f"{indicator} {item['subject']}")
            lines.append(f"   From: {item['sender']}")
            lines.append(f"   Date: {item['received_date']}")
            lines.append(f"   Mailbox: {item['mailbox']}")
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
    account: str,
    mailbox: str,
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
) -> List[Dict[str, Any]]:
    """Return structured search records from Apple Mail."""
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if limit <= 0:
        return []
    if sort not in {"date_desc", "date_asc"}:
        raise ValueError("Invalid sort. Use: date_desc, date_asc")
    if read_status not in {"all", "read", "unread"}:
        raise ValueError("Invalid read_status. Use: all, read, unread")

    escaped_account = escape_applescript(account)
    escaped_mailbox = escape_applescript(mailbox)
    escaped_sender = escape_applescript(sender) if sender else None

    filter_conditions = []
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
        mailbox_script = f'''
                try
                    set searchMailbox to mailbox "{escaped_mailbox}" of targetAccount
                on error
                    if "{escaped_mailbox}" is "INBOX" then
                        try
                            set searchMailbox to mailbox "Inbox" of targetAccount
                        on error
                            set searchMailbox to missing value
                            repeat with mb in mailboxes of targetAccount
                                set mbName to name of mb
                                if mbName is "Входящие" or mbName is "Posteingang" or mbName is "Boîte de réception" or mbName is "Bandeja de entrada" or mbName is "受信トレイ" or mbName is "收件箱" then
                                    set searchMailbox to mb
                                    exit repeat
                                end if
                            end repeat
                            if searchMailbox is missing value then
                                error "Could not find inbox mailbox"
                            end if
                        end try
                    else
                        error "Mailbox not found: {escaped_mailbox}"
                    end if
                end try
                set searchMailboxes to {{searchMailbox}}
        '''
        skip_script = ""

    date_setup = _build_applescript_date("fromDate", date_from)
    date_setup += _build_applescript_date("toDate", date_to, end_of_day=True)

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
                set collectLimit to {limit + 1}
                set targetAccount to account "{escaped_account}"
                set accountName to my sanitize_field(name of targetAccount)
                {date_setup}
                {mailbox_script}

                repeat with currentMailbox in searchMailboxes
                    if collectLimit <= 0 then exit repeat

                    try
                        set mailboxName to my sanitize_field(name of currentMailbox)
                        set shouldSkip to false
                        {skip_script}

                        if not shouldSkip then
                            {matching_messages_script}
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
def search_subjects(
    account: str,
    subject_keyword: Optional[str] = None,
    mailbox: str = "INBOX",
    max_results: Optional[int] = 25,
    subject_keywords: Optional[List[str]] = None,
    read_status: str = "all",
    output_format: str = "text",
    offset: int = 0,
    limit: Optional[int] = None,
    sort: str = "date_desc",
) -> str:
    """
    Search for emails by subject and return matching subjects or structured JSON.

    Args:
        account: Account name to search in (e.g., "Gmail", "Work")
        subject_keyword: Optional keyword to search for in email subjects
        mailbox: Mailbox to search (default: "INBOX", use "All" for all mailboxes)
        max_results: Backward-compatible alias for limit
        subject_keywords: Optional list of subject keywords; matches any keyword
        read_status: Filter by read status: "all", "read", "unread" (default: "all")
        output_format: Output format: "text" or "json" (default: "text")
        offset: Number of matching results to skip before returning data
        limit: Maximum number of results to return per page
        sort: Result sort order: "date_desc" or "date_asc"

    Returns:
        Formatted subject list or JSON payload with message metadata
    """
    if output_format not in {"text", "json"}:
        return "Error: Invalid output_format. Use: text, json"

    subject_terms = normalize_search_terms(subject_keyword, subject_keywords)
    if not subject_terms:
        return "Error: 'subject_keyword' or 'subject_keywords' is required"

    if limit is None:
        limit = max_results if max_results is not None else 25

    try:
        records = _search_mail_records(
            account=account,
            mailbox=mailbox,
            subject_terms=subject_terms,
            read_status=read_status,
            include_content=False,
            offset=offset,
            limit=limit,
            sort=sort,
        )
        return _build_search_response(
            records,
            offset=offset,
            limit=limit,
            sort=sort,
            output_format=output_format,
            subject_only=True,
        )
    except ValueError as exc:
        return f"Error: {exc}"


@mcp.tool()
@inject_preferences
def get_email_with_content(
    account: str,
    subject_keyword: str,
    max_results: int = 5,
    max_content_length: int = 300,
    mailbox: str = "INBOX",
) -> str:
    """
    Search for emails by subject keyword and return with full content preview.

    Args:
        account: Account name to search in (e.g., "Gmail", "Work")
        subject_keyword: Keyword to search for in email subjects
        max_results: Maximum number of matching emails to return (default: 5)
        max_content_length: Maximum content length in characters (default: 300, 0 = unlimited)
        mailbox: Mailbox to search (default: "INBOX", use "All" for all mailboxes)

    Returns:
        Detailed email information including content preview
    """
    try:
        records = _search_mail_records(
            account=account,
            mailbox=mailbox,
            subject_terms=normalize_search_terms(subject_keyword),
            include_content=True,
            content_length=max_content_length,
            offset=0,
            limit=max_results,
            sort="date_desc",
        )
        return _build_search_response(
            records,
            offset=0,
            limit=max_results,
            sort="date_desc",
            output_format="text",
            subject_only=False,
        )
    except ValueError as exc:
        return f"Error: {exc}"


@mcp.tool()
@inject_preferences
def search_emails(
    account: str,
    mailbox: str = "INBOX",
    subject_keyword: Optional[str] = None,
    subject_keywords: Optional[List[str]] = None,
    sender: Optional[str] = None,
    has_attachments: Optional[bool] = None,
    read_status: str = "all",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    include_content: bool = False,
    max_results: Optional[int] = 20,
    output_format: str = "text",
    offset: int = 0,
    limit: Optional[int] = None,
    sort: str = "date_desc",
) -> str:
    """
    Unified search tool with JSON output, pagination, and real date filtering.

    Args:
        account: Account name to search in (e.g., "Gmail", "Work")
        mailbox: Mailbox to search (default: "INBOX", use "All" for all mailboxes, or specific folder name)
        subject_keyword: Optional keyword to search in subject
        subject_keywords: Optional list of subject keywords; matches any keyword
        sender: Optional sender email or name to filter by
        has_attachments: Optional filter for emails with attachments (True/False/None)
        read_status: Filter by read status: "all", "read", "unread" (default: "all")
        date_from: Optional start date filter (format: "YYYY-MM-DD")
        date_to: Optional end date filter (format: "YYYY-MM-DD")
        include_content: Whether to include email content preview (slower)
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
            read_status=read_status,
            date_from=date_from,
            date_to=date_to,
            include_content=include_content,
            offset=offset,
            limit=limit,
            sort=sort,
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


@mcp.tool()
@inject_preferences
def group_emails_by_subject_regex(
    account: str,
    mailbox: str = "INBOX",
    read_status: str = "unread",
    regex: str = "",
    offset: int = 0,
    limit: int = 200,
    sort: str = "date_desc",
) -> str:
    """
    Group email subjects by a regex key and return grouped JSON.

    Args:
        account: Account name to search in
        mailbox: Mailbox to scan (default: "INBOX")
        read_status: Filter by read status: "all", "read", "unread" (default: "unread")
        regex: Regex used to extract a grouping key from the subject
        offset: Number of matching results to skip before grouping
        limit: Maximum number of emails to scan for grouping
        sort: Result sort order before grouping: "date_desc" or "date_asc"

    Returns:
        JSON payload grouped by extracted regex key
    """
    if not regex:
        return "Error: 'regex' is required"

    try:
        pattern = re.compile(regex)
    except re.error as exc:
        return f"Error: Invalid regex - {exc}"

    try:
        records = _search_mail_records(
            account=account,
            mailbox=mailbox,
            read_status=read_status,
            include_content=False,
            offset=offset,
            limit=limit,
            sort=sort,
        )
    except ValueError as exc:
        return f"Error: {exc}"

    sorted_records = _sort_search_records(records, sort)[:limit]
    groups: Dict[str, Dict[str, Any]] = {}

    for item in sorted_records:
        match = pattern.search(item["subject"])
        if not match:
            continue

        if match.lastindex:
            key = next((group for group in match.groups() if group), match.group(0))
        else:
            key = match.group(0)

        group = groups.setdefault(
            key,
            {
                "key": key,
                "count": 0,
                "message_ids": [],
                "internet_message_ids": [],
                "mail_links": [],
                "subjects": [],
            },
        )
        group["count"] += 1
        group["message_ids"].append(item["message_id"])
        if item.get("internet_message_id"):
            group["internet_message_ids"].append(item["internet_message_id"])
        if item.get("mail_link"):
            group["mail_links"].append(item["mail_link"])
        group["subjects"].append(item["subject"])

    grouped_items = sorted(
        groups.values(), key=lambda item: (-item["count"], item["key"])
    )
    return json.dumps(
        {
            "groups": grouped_items,
            "offset": offset,
            "limit": limit,
            "returned_groups": len(grouped_items),
            "regex": regex,
            "read_status": read_status,
            "mailbox": mailbox,
            "account": account,
        }
    )


@mcp.tool()
@inject_preferences
def search_by_sender(
    sender: str,
    account: Optional[str] = None,
    days_back: int = 30,
    max_results: int = 20,
    include_content: bool = True,
    max_content_length: int = 500,
    mailbox: str = "INBOX",
) -> str:
    """
    Find all emails from a specific sender across one or all accounts.
    Perfect for tracking newsletters, contacts, or communications from specific people/organizations.

    Args:
        sender: Sender name or email to search for (partial match, e.g., "alphasignal" or "john@")
        account: Optional account name. If None, searches all accounts.
        days_back: Only search emails from the last N days (default: 30, 0 = all time)
        max_results: Maximum number of emails to return (default: 20)
        include_content: Whether to include email content preview (default: True)
        max_content_length: Maximum length of content preview (default: 500)
        mailbox: Mailbox to search (default: "INBOX", use "All" for all mailboxes)

    Returns:
        Formatted list of emails from the sender, sorted by date (newest first)
    """

    # Build date filter if days_back > 0
    date_filter_script = ""
    date_check = ""
    if days_back > 0:
        date_filter_script = f"""
            set targetDate to (current date) - ({days_back} * days)
        """
        date_check = "and messageDate > targetDate"

    # Build content preview script
    content_script = ""
    if include_content:
        content_script = f"""
                            try
                                set msgContent to content of aMessage
                                set AppleScript's text item delimiters to {{return, linefeed}}
                                set contentParts to text items of msgContent
                                set AppleScript's text item delimiters to " "
                                set cleanText to contentParts as string
                                set AppleScript's text item delimiters to ""

                                if {max_content_length} > 0 and length of cleanText > {max_content_length} then
                                    set contentPreview to text 1 thru {max_content_length} of cleanText & "..."
                                else
                                    set contentPreview to cleanText
                                end if

                                set outputText to outputText & "   Content: " & contentPreview & return
                            on error
                                set outputText to outputText & "   Content: [Not available]" & return
                            end try
        """

    # Escape user inputs for AppleScript
    escaped_sender = escape_applescript(sender)
    escaped_mailbox = escape_applescript(mailbox)
    search_all_mailboxes = mailbox == "All"

    # Build mailbox selection: INBOX-only (fast) vs all mailboxes
    if search_all_mailboxes:
        mailbox_loop_start = """
                set accountMailboxes to every mailbox of anAccount
                repeat with aMailbox in accountMailboxes
                    set mailboxName to name of aMailbox
                    -- Skip system and aggregate folders to avoid scanning huge mailboxes
                    if mailboxName is not in {"Trash", "Junk", "Junk Email", "Deleted Items", "Deleted Messages", "Spam", "Drafts", "Sent", "Sent Items", "Sent Messages", "Sent Mail", "All Mail", "Bin"} then
        """
        mailbox_loop_end = f"""
                        if resultCount >= {max_results} then exit repeat
                    end if
                end repeat
        """
    else:
        mailbox_loop_start = f'''
                -- Fast path: only search the target mailbox
                try
                    set aMailbox to mailbox "{escaped_mailbox}" of anAccount
                on error
                    if "{escaped_mailbox}" is "INBOX" then
                        try
                            set aMailbox to mailbox "Inbox" of anAccount
                        on error
                            set aMailbox to missing value
                            repeat with mb in mailboxes of anAccount
                                set mbName to name of mb
                                if mbName is "Входящие" or mbName is "Posteingang" or mbName is "Boîte de réception" or mbName is "Bandeja de entrada" or mbName is "受信トレイ" or mbName is "收件箱" then
                                    set aMailbox to mb
                                    exit repeat
                                end if
                            end repeat
                            if aMailbox is missing value then
                                error "Could not find inbox mailbox"
                            end if
                        end try
                    else
                        error "Mailbox not found: {escaped_mailbox}"
                    end if
                end try
                set mailboxName to name of aMailbox
                if true then
        '''
        mailbox_loop_end = """
                end if
        """

    # Build account iteration: direct access (fast) vs all accounts
    if account:
        escaped_account = escape_applescript(account)
        account_loop_start = f'''
        set anAccount to account "{escaped_account}"
        set accountName to name of anAccount
        repeat 1 times
        '''
        account_loop_end = """
        end repeat
        """
    else:
        account_loop_start = f"""
        set allAccounts to every account
        repeat with anAccount in allAccounts
            set accountName to name of anAccount
        """
        account_loop_end = f"""
            if resultCount >= {max_results} then exit repeat
        end repeat
        """

    script = f'''
    {LOWERCASE_HANDLER}

    tell application "Mail"
        set outputText to "EMAILS FROM SENDER: {escaped_sender}" & return
        set outputText to outputText & "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501" & return & return
        set resultCount to 0

        {date_filter_script}

        {account_loop_start}

            try
                {mailbox_loop_start}

                        set mailboxMessages to every message of aMailbox

                        repeat with aMessage in mailboxMessages
                            if resultCount >= {max_results} then exit repeat

                            try
                                set messageSender to sender of aMessage
                                set messageDate to date received of aMessage

                                -- Case-insensitive sender match
                                set lowerSender to my lowercase(messageSender)
                                set lowerSearch to my lowercase("{escaped_sender}")

                                if lowerSender contains lowerSearch {date_check} then
                                    set messageSubject to subject of aMessage
                                    set messageRead to read status of aMessage

                                    if messageRead then
                                        set readIndicator to "\u2713"
                                    else
                                        set readIndicator to "\u2709"
                                    end if

                                    set outputText to outputText & readIndicator & " " & messageSubject & return
                                    set outputText to outputText & "   From: " & messageSender & return
                                    set outputText to outputText & "   Date: " & (messageDate as string) & return
                                    set outputText to outputText & "   Account: " & accountName & return
                                    set outputText to outputText & "   Mailbox: " & mailboxName & return

                                    {content_script}

                                    set outputText to outputText & return
                                    set resultCount to resultCount + 1
                                end if
                            end try
                        end repeat

                {mailbox_loop_end}

            on error errMsg
                set outputText to outputText & "\u26a0 Error accessing mailboxes for " & accountName & ": " & errMsg & return
            end try

        {account_loop_end}

        set outputText to outputText & "========================================" & return
        set outputText to outputText & "FOUND: " & resultCount & " email(s) from sender" & return
        if {days_back} > 0 then
            set outputText to outputText & "Time range: Last {days_back} days" & return
        end if
        set outputText to outputText & "========================================" & return

        return outputText
    end tell
    '''

    result = run_applescript(script)
    return result


@mcp.tool()
@inject_preferences
def search_email_content(
    account: str,
    search_text: str,
    mailbox: str = "INBOX",
    search_subject: bool = True,
    search_body: bool = True,
    max_results: int = 10,
    max_content_length: int = 600,
) -> str:
    """
    Search email body content (and optionally subject).
    This is slower than subject-only search but finds more relevant results.

    Args:
        account: Account name to search in
        search_text: Text to search for in email content
        mailbox: Mailbox to search (default: "INBOX")
        search_subject: Also search in subject line (default: True)
        search_body: Search in email body (default: True)
        max_results: Maximum results to return (default: 10, keep low as this is slow)
        max_content_length: Max content preview length (default: 600)

    Returns:
        Emails where the search text appears in body and/or subject
    """
    escaped_search = escape_applescript(search_text).lower()
    escaped_account = escape_applescript(account)
    escaped_mailbox = escape_applescript(mailbox)
    search_conditions = []
    if search_subject:
        search_conditions.append(f'lowerSubject contains "{escaped_search}"')
    if search_body:
        search_conditions.append(f'lowerContent contains "{escaped_search}"')
    search_condition = " or ".join(search_conditions) if search_conditions else "false"

    script = f'''
    {LOWERCASE_HANDLER}

    tell application "Mail"
        set outputText to "\U0001f50e CONTENT SEARCH: {escaped_search}" & return
        set outputText to outputText & "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501" & return
        set outputText to outputText & "\u26a0 Note: Body search is slower - searching {max_results} results max" & return & return
        set resultCount to 0
        try
            set targetAccount to account "{escaped_account}"
            try
                set targetMailbox to mailbox "{escaped_mailbox}" of targetAccount
            on error
                if "{escaped_mailbox}" is "INBOX" then
                    try
                        set targetMailbox to mailbox "Inbox" of targetAccount
                    on error
                        set targetMailbox to missing value
                        repeat with mb in mailboxes of targetAccount
                            set mbName to name of mb
                            if mbName is "Входящие" or mbName is "Posteingang" or mbName is "Boîte de réception" or mbName is "Bandeja de entrada" or mbName is "受信トレイ" or mbName is "收件箱" then
                                set targetMailbox to mb
                                exit repeat
                            end if
                        end repeat
                        if targetMailbox is missing value then
                            error "Could not find inbox mailbox"
                        end if
                    end try
                else
                    error "Mailbox not found: {escaped_mailbox}"
                end if
            end try
            set mailboxMessages to every message of targetMailbox
            repeat with aMessage in mailboxMessages
                if resultCount >= {max_results} then exit repeat
                try
                    set messageSubject to subject of aMessage
                    set msgContent to ""
                    try
                        set msgContent to content of aMessage
                    end try
                    set lowerSubject to my lowercase(messageSubject)
                    set lowerContent to my lowercase(msgContent)
                    if {search_condition} then
                        set messageSender to sender of aMessage
                        set messageDate to date received of aMessage
                        set messageRead to read status of aMessage
                        if messageRead then
                            set readIndicator to "\u2713"
                        else
                            set readIndicator to "\u2709"
                        end if
                        set outputText to outputText & readIndicator & " " & messageSubject & return
                        set outputText to outputText & "   From: " & messageSender & return
                        set outputText to outputText & "   Date: " & (messageDate as string) & return
                        set outputText to outputText & "   Mailbox: {escaped_mailbox}" & return
                        try
                            set AppleScript's text item delimiters to {{return, linefeed}}
                            set contentParts to text items of msgContent
                            set AppleScript's text item delimiters to " "
                            set cleanText to contentParts as string
                            set AppleScript's text item delimiters to ""
                            if length of cleanText > {max_content_length} then
                                set contentPreview to text 1 thru {max_content_length} of cleanText & "..."
                            else
                                set contentPreview to cleanText
                            end if
                            set outputText to outputText & "   Content: " & contentPreview & return
                        on error
                            set outputText to outputText & "   Content: [Not available]" & return
                        end try
                        set outputText to outputText & return
                        set resultCount to resultCount + 1
                    end if
                end try
            end repeat
            set outputText to outputText & "========================================" & return
            set outputText to outputText & "FOUND: " & resultCount & " email(s) matching \\"{escaped_search}\\"" & return
            set outputText to outputText & "========================================" & return
        on error errMsg
            return "Error: " & errMsg
        end try
        return outputText
    end tell
    '''
    result = run_applescript(script)
    return result


@mcp.tool()
@inject_preferences
def get_newsletters(
    account: Optional[str] = None,
    days_back: int = 7,
    max_results: int = 25,
    include_content: bool = True,
    max_content_length: int = 500,
) -> str:
    """
    Find newsletter and digest emails by detecting common patterns.
    Automatically identifies emails from newsletter services and digest senders.

    Args:
        account: Account to search. If None, searches all accounts.
        days_back: Only search last N days (default: 7)
        max_results: Maximum newsletters to return (default: 25)
        include_content: Include content preview (default: True)
        max_content_length: Max preview length (default: 500)

    Returns:
        List of detected newsletter emails sorted by date
    """
    # Escape user inputs for AppleScript
    escaped_account = escape_applescript(account) if account else None

    content_script = ""
    if include_content:
        content_script = f"""
                                    try
                                        set msgContent to content of aMessage
                                        set AppleScript's text item delimiters to {{return, linefeed}}
                                        set contentParts to text items of msgContent
                                        set AppleScript's text item delimiters to " "
                                        set cleanText to contentParts as string
                                        set AppleScript's text item delimiters to ""
                                        if length of cleanText > {max_content_length} then
                                            set contentPreview to text 1 thru {max_content_length} of cleanText & "..."
                                        else
                                            set contentPreview to cleanText
                                        end if
                                        set outputText to outputText & "   Content: " & contentPreview & return
                                    on error
                                        set outputText to outputText & "   Content: [Not available]" & return
                                    end try
        """

    account_filter_start = ""
    account_filter_end = ""
    if account:
        account_filter_start = f'if accountName is "{escaped_account}" then'
        account_filter_end = "end if"

    date_filter = ""
    date_check = ""
    if days_back > 0:
        date_filter = f"set cutoffDate to (current date) - ({days_back} * days)"
        date_check = " and messageDate > cutoffDate"

    script = f"""
    {LOWERCASE_HANDLER}

    tell application "Mail"
        set outputText to "\U0001f4f0 NEWSLETTER DETECTION" & return
        set outputText to outputText & "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501" & return & return
        set resultCount to 0
        {date_filter}
        set allAccounts to every account
        repeat with anAccount in allAccounts
            set accountName to name of anAccount
            {account_filter_start}
            try
                set accountMailboxes to every mailbox of anAccount
                repeat with aMailbox in accountMailboxes
                    try
                        set mailboxName to name of aMailbox
                        if mailboxName is "INBOX" or mailboxName is "Inbox" then
                            set mailboxMessages to every message of aMailbox
                            repeat with aMessage in mailboxMessages
                                if resultCount >= {max_results} then exit repeat
                                try
                                    set messageSender to sender of aMessage
                                    set messageDate to date received of aMessage
                                    set lowerSender to my lowercase(messageSender)
                                    set isNewsletter to false
                                    if lowerSender contains "substack.com" or lowerSender contains "beehiiv.com" or lowerSender contains "mailchimp" or lowerSender contains "sendgrid" or lowerSender contains "convertkit" or lowerSender contains "buttondown" or lowerSender contains "ghost.io" or lowerSender contains "revue.co" or lowerSender contains "mailgun" then
                                        set isNewsletter to true
                                    end if
                                    if lowerSender contains "newsletter" or lowerSender contains "digest" or lowerSender contains "weekly" or lowerSender contains "daily" or lowerSender contains "bulletin" or lowerSender contains "briefing" or lowerSender contains "news@" or lowerSender contains "updates@" then
                                        set isNewsletter to true
                                    end if
                                    if isNewsletter{date_check} then
                                        set messageSubject to subject of aMessage
                                        set messageRead to read status of aMessage
                                        if messageRead then
                                            set readIndicator to "\u2713"
                                        else
                                            set readIndicator to "\u2709"
                                        end if
                                        set outputText to outputText & readIndicator & " " & messageSubject & return
                                        set outputText to outputText & "   From: " & messageSender & return
                                        set outputText to outputText & "   Date: " & (messageDate as string) & return
                                        set outputText to outputText & "   Account: " & accountName & return
                                        {content_script}
                                        set outputText to outputText & return
                                        set resultCount to resultCount + 1
                                    end if
                                end try
                            end repeat
                        end if
                    end try
                    if resultCount >= {max_results} then exit repeat
                end repeat
            end try
            {account_filter_end}
            if resultCount >= {max_results} then exit repeat
        end repeat
        set outputText to outputText & "========================================" & return
        set outputText to outputText & "FOUND: " & resultCount & " newsletter(s)" & return
        set outputText to outputText & "========================================" & return
        return outputText
    end tell
    """
    result = run_applescript(script)
    return result


@mcp.tool()
@inject_preferences
def get_recent_from_sender(
    sender: str,
    account: Optional[str] = None,
    time_range: str = "week",
    max_results: int = 15,
    include_content: bool = True,
    max_content_length: int = 400,
    mailbox: str = "INBOX",
) -> str:
    """
    Get recent emails from a specific sender with simple, human-friendly time filters.

    Args:
        sender: Sender name or email to search for (partial match)
        account: Optional account. If None, searches all accounts.
        time_range: Human-friendly time filter:
            - "today" = last 24 hours
            - "yesterday" = yesterday only
            - "week" = last 7 days (default)
            - "month" = last 30 days
            - "all" = no time filter
        max_results: Maximum emails to return (default: 15)
        include_content: Include content preview (default: True)
        max_content_length: Max preview length (default: 400)
        mailbox: Mailbox to search (default: "INBOX", use "All" for all mailboxes)

    Returns:
        Recent emails from the specified sender within the time range
    """
    time_ranges = {"today": 1, "yesterday": 2, "week": 7, "month": 30, "all": 0}
    days_back = time_ranges.get(time_range.lower(), 7)
    is_yesterday = time_range.lower() == "yesterday"

    content_script = ""
    if include_content:
        content_script = f"""
                                    try
                                        set msgContent to content of aMessage
                                        set AppleScript's text item delimiters to {{return, linefeed}}
                                        set contentParts to text items of msgContent
                                        set AppleScript's text item delimiters to " "
                                        set cleanText to contentParts as string
                                        set AppleScript's text item delimiters to ""
                                        if length of cleanText > {max_content_length} then
                                            set contentPreview to text 1 thru {max_content_length} of cleanText & "..."
                                        else
                                            set contentPreview to cleanText
                                        end if
                                        set outputText to outputText & "   Content: " & contentPreview & return
                                    on error
                                        set outputText to outputText & "   Content: [Not available]" & return
                                    end try
        """

    # Escape user inputs for AppleScript
    escaped_sender = escape_applescript(sender)
    escaped_mailbox = escape_applescript(mailbox)
    search_all_mailboxes = mailbox == "All"

    date_filter = ""
    date_check = ""
    if days_back > 0:
        date_filter = f"set cutoffDate to (current date) - ({days_back} * days)"
        if is_yesterday:
            date_filter += """
            set todayStart to (current date) - (time of (current date))
            set yesterdayStart to todayStart - (1 * days)
            """
            date_check = (
                " and messageDate >= yesterdayStart and messageDate < todayStart"
            )
        else:
            date_check = " and messageDate > cutoffDate"

    # Build mailbox selection: INBOX-only (fast) vs all mailboxes
    if search_all_mailboxes:
        mailbox_loop_start = """
                set accountMailboxes to every mailbox of anAccount
                repeat with aMailbox in accountMailboxes
                    try
                        set mailboxName to name of aMailbox
                        if mailboxName is not in {"Trash", "Junk", "Junk Email", "Deleted Items", "Deleted Messages", "Spam", "Drafts", "Sent", "Sent Items", "Sent Messages", "Sent Mail", "All Mail", "Bin"} then
        """
        mailbox_loop_end = f"""
                        end if
                    end try
                    if resultCount >= {max_results} then exit repeat
                end repeat
        """
    else:
        mailbox_loop_start = f'''
                -- Fast path: only search the target mailbox
                try
                    set aMailbox to mailbox "{escaped_mailbox}" of anAccount
                on error
                    if "{escaped_mailbox}" is "INBOX" then
                        try
                            set aMailbox to mailbox "Inbox" of anAccount
                        on error
                            set aMailbox to missing value
                            repeat with mb in mailboxes of anAccount
                                set mbName to name of mb
                                if mbName is "Входящие" or mbName is "Posteingang" or mbName is "Boîte de réception" or mbName is "Bandeja de entrada" or mbName is "受信トレイ" or mbName is "收件箱" then
                                    set aMailbox to mb
                                    exit repeat
                                end if
                            end repeat
                            if aMailbox is missing value then
                                error "Could not find inbox mailbox"
                            end if
                        end try
                    else
                        error "Mailbox not found: {escaped_mailbox}"
                    end if
                end try
                set mailboxName to name of aMailbox
                if true then
        '''
        mailbox_loop_end = """
                end if
        """

    # Build account iteration: direct access (fast) vs all accounts
    if account:
        escaped_account = escape_applescript(account)
        account_loop_start = f'''
        set anAccount to account "{escaped_account}"
        set accountName to name of anAccount
        repeat 1 times
        '''
        account_loop_end = """
        end repeat
        """
    else:
        account_loop_start = f"""
        set allAccounts to every account
        repeat with anAccount in allAccounts
            set accountName to name of anAccount
        """
        account_loop_end = f"""
            if resultCount >= {max_results} then exit repeat
        end repeat
        """

    script = f'''
    {LOWERCASE_HANDLER}

    tell application "Mail"
        set outputText to "\U0001f4e7 EMAILS FROM: {escaped_sender}" & return
        set outputText to outputText & "\u23f0 Time range: {time_range}" & return
        set outputText to outputText & "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501" & return & return
        set resultCount to 0
        {date_filter}

        {account_loop_start}

            try
                {mailbox_loop_start}

                            set mailboxMessages to every message of aMailbox
                            repeat with aMessage in mailboxMessages
                                if resultCount >= {max_results} then exit repeat
                                try
                                    set messageSender to sender of aMessage
                                    set messageDate to date received of aMessage
                                    set lowerSender to my lowercase(messageSender)
                                    set lowerSearch to my lowercase("{escaped_sender}")
                                    if lowerSender contains lowerSearch{date_check} then
                                        set messageSubject to subject of aMessage
                                        set messageRead to read status of aMessage
                                        if messageRead then
                                            set readIndicator to "\u2713"
                                        else
                                            set readIndicator to "\u2709"
                                        end if
                                        set outputText to outputText & readIndicator & " " & messageSubject & return
                                        set outputText to outputText & "   From: " & messageSender & return
                                        set outputText to outputText & "   Date: " & (messageDate as string) & return
                                        set outputText to outputText & "   Account: " & accountName & return
                                        {content_script}
                                        set outputText to outputText & return
                                        set resultCount to resultCount + 1
                                    end if
                                end try
                            end repeat

                {mailbox_loop_end}

            end try

        {account_loop_end}

        set outputText to outputText & "========================================" & return
        set outputText to outputText & "FOUND: " & resultCount & " email(s) from sender" & return
        set outputText to outputText & "========================================" & return
        return outputText
    end tell
    '''
    result = run_applescript(script)
    return result


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
                try
                    set searchMailbox to mailbox "Inbox" of targetAccount
                on error
                    set searchMailbox to missing value
                    repeat with mb in mailboxes of targetAccount
                        set mbName to name of mb
                        if mbName is "Входящие" or mbName is "Posteingang" or mbName is "Boîte de réception" or mbName is "Bandeja de entrada" or mbName is "受信トレイ" or mbName is "收件箱" then
                            set searchMailbox to mb
                            exit repeat
                        end if
                    end repeat
                    if searchMailbox is missing value then
                        error "Could not find inbox mailbox"
                    end if
                end try
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
                        if cleanSubject starts with "Fwd: " or cleanSubject starts with "FW: " then
                            set cleanSubject to text 6 thru -1 of cleanSubject
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
            set outputText to outputText & "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501" & return
            set outputText to outputText & "FOUND " & messageCount & " MESSAGE(S) IN THREAD" & return
            set outputText to outputText & "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501" & return & return

            repeat with aMessage in threadMessages
                try
                    set messageSubject to subject of aMessage
                    set messageSender to sender of aMessage
                    set messageDate to date received of aMessage
                    set messageRead to read status of aMessage

                    if messageRead then
                        set readIndicator to "\u2713"
                    else
                        set readIndicator to "\u2709"
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


@mcp.tool()
@inject_preferences
def search_all_accounts(
    subject_keyword: Optional[str] = None,
    sender: Optional[str] = None,
    days_back: int = 7,
    max_results: int = 30,
    include_content: bool = True,
    max_content_length: int = 400,
) -> str:
    """
    Search across ALL email accounts at once.

    Returns consolidated results sorted by date (newest first).
    Only searches INBOX mailboxes (skips Trash, Junk, Drafts, Sent).

    Args:
        subject_keyword: Optional keyword to search in subject
        sender: Optional sender email or name to filter by
        days_back: Number of days to look back (default: 7, 0 = all time)
        max_results: Maximum total results across all accounts (default: 30)
        include_content: Whether to include email content preview (default: True)
        max_content_length: Maximum content length in characters (default: 400)

    Returns:
        Formatted list of matching emails with account name for each
    """
    # Build date filter
    date_filter = ""
    if days_back > 0:
        date_filter = f"""
            set cutoffDate to (current date) - ({days_back} * days)
            if messageDate < cutoffDate then
                set skipMessage to true
            end if
        """

    # Build subject filter
    subject_filter = ""
    if subject_keyword:
        escaped_keyword = escape_applescript(subject_keyword)
        subject_filter = f'''
            set lowerSubject to my lowercase(messageSubject)
            set lowerKeyword to my lowercase("{escaped_keyword}")
            if lowerSubject does not contain lowerKeyword then
                set skipMessage to true
            end if
        '''

    # Build sender filter
    sender_filter = ""
    if sender:
        escaped_sender = escape_applescript(sender)
        sender_filter = f'''
            set lowerSender to my lowercase(messageSender)
            set lowerSenderFilter to my lowercase("{escaped_sender}")
            if lowerSender does not contain lowerSenderFilter then
                set skipMessage to true
            end if
        '''

    # Build content retrieval
    content_retrieval = ""
    if include_content:
        content_retrieval = f"""
            try
                set messageContent to content of msg
                if length of messageContent > {max_content_length} then
                    set messageContent to text 1 thru {max_content_length} of messageContent & "..."
                end if
                -- Clean up content for display
                set messageContent to my replaceText(messageContent, return, " ")
                set messageContent to my replaceText(messageContent, linefeed, " ")
            on error
                set messageContent to "(Content unavailable)"
            end try
            set emailRecord to emailRecord & "Content: " & messageContent & linefeed
        """

    script = f"""
        {LOWERCASE_HANDLER}

        on replaceText(theText, searchStr, replaceStr)
            set AppleScript\'s text item delimiters to searchStr
            set theItems to text items of theText
            set AppleScript\'s text item delimiters to replaceStr
            set theText to theItems as text
            set AppleScript\'s text item delimiters to ""
            return theText
        end replaceText

        tell application "Mail"
            set allResults to {{}}
            set allAccounts to every account

            repeat with acct in allAccounts
                set acctName to name of acct

                -- Find INBOX mailbox
                set inboxMailbox to missing value
                try
                    set inboxMailbox to mailbox "INBOX" of acct
                on error
                    -- Try to find inbox by checking mailboxes
                    repeat with mb in mailboxes of acct
                        set mbName to name of mb
                        if mbName is "INBOX" or mbName is "Inbox" then
                            set inboxMailbox to mb
                            exit repeat
                        end if
                    end repeat
                end try

                if inboxMailbox is not missing value then
                    try
                        set msgs to messages of inboxMailbox

                        repeat with msg in msgs
                            set skipMessage to false

                            try
                                set messageSubject to subject of msg
                                set messageSender to sender of msg
                                set messageDate to date received of msg
                                set messageRead to read status of msg
                            on error
                                set skipMessage to true
                            end try

                            if not skipMessage then
                                {date_filter}
                            end if

                            if not skipMessage then
                                {subject_filter}
                            end if

                            if not skipMessage then
                                {sender_filter}
                            end if

                            if not skipMessage then
                                -- Build email record
                                set emailRecord to ""
                                set emailRecord to emailRecord & "Account: " & acctName & linefeed
                                set emailRecord to emailRecord & "Subject: " & messageSubject & linefeed
                                set emailRecord to emailRecord & "From: " & messageSender & linefeed
                                set emailRecord to emailRecord & "Date: " & (messageDate as string) & linefeed
                                if messageRead then
                                    set emailRecord to emailRecord & "Status: Read" & linefeed
                                else
                                    set emailRecord to emailRecord & "Status: UNREAD" & linefeed
                                end if
                                {content_retrieval}

                                -- Store with date for sorting
                                set end of allResults to {{emailDate:messageDate, emailText:emailRecord}}
                            end if

                            -- Check if we have enough results
                            if (count of allResults) >= {max_results} then
                                exit repeat
                            end if
                        end repeat
                    on error errMsg
                        -- Skip this account if there\'s an error
                    end try
                end if

                -- Check if we have enough results
                if (count of allResults) >= {max_results} then
                    exit repeat
                end if
            end repeat

            -- Sort results by date (newest first)
            set sortedResults to my sortByDate(allResults)

            -- Build output
            set outputText to ""
            set emailCount to count of sortedResults

            if emailCount is 0 then
                return "No emails found matching your criteria across all accounts."
            end if

            set outputText to "=== Cross-Account Search Results ===" & linefeed
            set outputText to outputText & "Found " & emailCount & " email(s)" & linefeed
            set outputText to outputText & "---" & linefeed & linefeed

            repeat with emailItem in sortedResults
                set outputText to outputText & emailText of emailItem & linefeed & "---" & linefeed
            end repeat

            return outputText
        end tell

        on sortByDate(theList)
            -- Simple bubble sort by date (descending - newest first)
            set listLength to count of theList
            repeat with i from 1 to listLength - 1
                repeat with j from 1 to listLength - i
                    if emailDate of item j of theList < emailDate of item (j + 1) of theList then
                        set temp to item j of theList
                        set item j of theList to item (j + 1) of theList
                        set item (j + 1) of theList to temp
                    end if
                end repeat
            end repeat
            return theList
        end sortByDate
    """

    result = run_applescript(script)
    return result

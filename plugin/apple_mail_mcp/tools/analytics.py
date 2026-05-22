"""Analytics tools: attachments, statistics, exports, and dashboard."""

import asyncio
import os
import re
from typing import Optional, List, Dict, Any, Union

from apple_mail_mcp import server as _server
from apple_mail_mcp.server import mcp, READ_ONLY_TOOL_ANNOTATIONS, WRITE_TOOL_ANNOTATIONS
from apple_mail_mcp.core import (
    AppleScriptTimeout,
    inject_preferences,
    escape_applescript,
    run_applescript,
    inbox_mailbox_script,
    list_mail_account_names,
    validate_account_name,
    validate_save_path,
)
from apple_mail_mcp.constants import SKIP_FOLDERS
from apple_mail_mcp.tools.search import _search_mail_records_sync as _search_mail_records


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
@inject_preferences
def list_email_attachments(
    account: Optional[str] = None,
    subject_keyword: str = "",
    max_results: int = 50,
    timeout: Optional[int] = None,
) -> str:
    """
    List attachments for emails matching a subject keyword.

    Scans the most-recent inbox messages (capped at ``max_results`` via
    ``items 1 thru max_results``) and returns attachments for the messages
    whose subject contains ``subject_keyword``.

    Args:
        account: Account name (e.g., "Gmail", "Work", "Personal"). Falls back
            to ``DEFAULT_MAIL_ACCOUNT`` when None.
        subject_keyword: Keyword to search for in email subjects
        max_results: Maximum number of messages to inspect from the inbox
            (default: 50). The AppleScript only enumerates this many messages.
        timeout: Optional AppleScript timeout in seconds. Defaults to the
            ``run_applescript`` baseline (120s).

    Returns:
        List of attachments with their names and sizes
    """

    if account is None:
        account = _server.DEFAULT_MAIL_ACCOUNT
    if not account:
        return "Error: 'account' is required (no DEFAULT_MAIL_ACCOUNT configured)"

    validation_timeout = 30 if timeout is None else min(timeout, 30)
    account_err = validate_account_name(account, timeout=validation_timeout)
    if account_err:
        return account_err

    # Escape for AppleScript
    escaped_keyword = escape_applescript(subject_keyword)
    escaped_account = escape_applescript(account)

    # Fast no-hit path: use the optimized search helper first so no-match
    # attachment checks don't scan the inbox with a Python-side loop.
    try:
        preflight_records = _search_mail_records(
            account=account,
            mailbox="INBOX",
            subject_terms=[subject_keyword],
            has_attachments=True,
            include_content=False,
            offset=0,
            limit=max_results,
        )
    except AppleScriptTimeout:
        return (
            f"Error: AppleScript timed out while listing attachments for '{account}'"
        )
    if not preflight_records:
        return (
            f"ATTACHMENTS FOR: {subject_keyword}\n\n"
            "========================================\n"
            "FOUND: 0 matching email(s)\n"
            "========================================"
        )

    script = f'''
    tell application "Mail"
        set outputText to "ATTACHMENTS FOR: {escaped_keyword}" & return & return
        set resultCount to 0

        try
            set targetAccount to account "{escaped_account}"
            {inbox_mailbox_script("inboxMailbox", "targetAccount")}
            if (count of messages of inboxMailbox) > {max_results} then
                set inboxMessages to messages 1 thru {max_results} of inboxMailbox
            else
                set inboxMessages to messages of inboxMailbox
            end if

            repeat with aMessage in inboxMessages
                if resultCount >= {max_results} then exit repeat

                try
                    set messageSubject to subject of aMessage

                    -- Check if subject contains keyword
                    if messageSubject contains "{escaped_keyword}" then
                        set messageSender to sender of aMessage
                        set messageDate to date received of aMessage

                        set outputText to outputText & "✉ " & messageSubject & return
                        set outputText to outputText & "   From: " & messageSender & return
                        set outputText to outputText & "   Date: " & (messageDate as string) & return & return

                        -- Get attachments
                        set msgAttachments to mail attachments of aMessage
                        set attachmentCount to count of msgAttachments

                        if attachmentCount > 0 then
                            set outputText to outputText & "   Attachments (" & attachmentCount & "):" & return

                            repeat with anAttachment in msgAttachments
                                set attachmentName to name of anAttachment
                                try
                                    set attachmentSize to size of anAttachment
                                    set sizeInKB to (attachmentSize / 1024) as integer
                                    set outputText to outputText & "   📎 " & attachmentName & " (" & sizeInKB & " KB)" & return
                                on error
                                    set outputText to outputText & "   📎 " & attachmentName & return
                                end try
                            end repeat
                        else
                            set outputText to outputText & "   No attachments" & return
                        end if

                        set outputText to outputText & return
                        set resultCount to resultCount + 1
                    end if
                end try
            end repeat

            set outputText to outputText & "========================================" & return
            set outputText to outputText & "FOUND: " & resultCount & " matching email(s)" & return
            set outputText to outputText & "========================================" & return

        on error errMsg
            return "Error: " & errMsg
        end try

        return outputText
    end tell
    '''

    try:
        result = run_applescript(
            script, timeout=timeout if timeout is not None else 120
        )
    except AppleScriptTimeout:
        return f"Error: AppleScript timed out while listing attachments for '{account}'"
    return result


def _statistics_recent_days_applied(days_back: int, scope: str) -> float:
    if scope == "mailbox_breakdown":
        return 0.0
    return float(days_back) if days_back > 0 else 0.0


def _parse_account_overview_statistics(text: str) -> Dict[str, Any]:
    stats: Dict[str, Any] = {
        "total_emails": 0,
        "unread": 0,
        "read": 0,
        "flagged": 0,
        "with_attachments": 0,
        "top_senders": [],
        "mailbox_distribution": [],
    }

    total_match = re.search(r"Total Emails: (\d+)", text)
    if total_match:
        stats["total_emails"] = int(total_match.group(1))

    unread_match = re.search(r"Unread: (\d+)(?: \((\d+)%\))?", text)
    if unread_match:
        stats["unread"] = int(unread_match.group(1))
        if unread_match.group(2) is not None:
            stats["unread_percent"] = int(unread_match.group(2))

    read_match = re.search(r"Read: (\d+)(?: \((\d+)%\))?", text)
    if read_match:
        stats["read"] = int(read_match.group(1))
        if read_match.group(2) is not None:
            stats["read_percent"] = int(read_match.group(2))

    flagged_match = re.search(r"Flagged: (\d+)", text)
    if flagged_match:
        stats["flagged"] = int(flagged_match.group(1))

    attachments_match = re.search(
        r"With Attachments: (\d+)(?: \((\d+)%\))?", text
    )
    if attachments_match:
        stats["with_attachments"] = int(attachments_match.group(1))
        if attachments_match.group(2) is not None:
            stats["with_attachments_percent"] = int(attachments_match.group(2))

    section = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "👥 TOP SENDERS":
            section = "senders"
            continue
        if stripped == "📁 MAILBOX DISTRIBUTION":
            section = "mailboxes"
            continue
        if section == "senders" and stripped.endswith(" emails"):
            sender_match = re.match(r"(.+): (\d+) emails$", stripped)
            if sender_match:
                stats["top_senders"].append(
                    {
                        "sender": sender_match.group(1),
                        "count": int(sender_match.group(2)),
                    }
                )
        elif section == "mailboxes" and ":" in stripped and not stripped.startswith("━"):
            mailbox_match = re.match(r"(.+): (\d+)(?: \((\d+)%\))?$", stripped)
            if mailbox_match:
                entry = {
                    "mailbox": mailbox_match.group(1),
                    "count": int(mailbox_match.group(2)),
                }
                if mailbox_match.group(3) is not None:
                    entry["percent"] = int(mailbox_match.group(3))
                stats["mailbox_distribution"].append(entry)

    return stats


def _parse_sender_stats_statistics(text: str) -> Dict[str, Any]:
    stats: Dict[str, Any] = {}
    for key, pattern in (
        ("total_emails", r"Total emails: (\d+)"),
        ("unread", r"Unread: (\d+)"),
        ("with_attachments", r"With attachments: (\d+)"),
    ):
        match = re.search(pattern, text)
        if match:
            stats[key] = int(match.group(1))
    return stats


def _parse_mailbox_breakdown_statistics(text: str) -> Dict[str, Any]:
    stats: Dict[str, Any] = {}
    for key, pattern in (
        ("total_messages", r"Total messages: (\d+)"),
        ("unread", r"Unread: (\d+)"),
        ("read", r"Read: (\d+)"),
    ):
        match = re.search(pattern, text)
        if match:
            stats[key] = int(match.group(1))
    return stats


def _parse_statistics_text(scope: str, text: str) -> Dict[str, Any]:
    if scope == "account_overview":
        return _parse_account_overview_statistics(text)
    if scope == "sender_stats":
        return _parse_sender_stats_statistics(text)
    return _parse_mailbox_breakdown_statistics(text)


def _format_statistics_json(
    *,
    scope: str,
    account: str,
    days_back: int,
    statistics: Dict[str, Any],
    sender: Optional[str] = None,
    mailbox: Optional[str] = None,
    errors: Optional[List[str]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "account": account,
        "scope": scope,
        "days_back": days_back,
        "recent_days_applied": _statistics_recent_days_applied(days_back, scope),
        "statistics": statistics,
        "errors": errors or [],
    }
    if sender is not None:
        payload["sender"] = sender
    if scope == "mailbox_breakdown":
        payload["mailbox"] = mailbox or "INBOX"
    return payload


def _statistics_json_error(
    error: str,
    *,
    account: Optional[str] = None,
    days_back: Optional[int] = None,
    scope: Optional[str] = None,
    message: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"error": error, "errors": []}
    if account is not None:
        payload["account"] = account
    if days_back is not None:
        payload["days_back"] = days_back
    if scope is not None:
        payload["scope"] = scope
    if message is not None:
        payload["message"] = message
    return payload


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
@inject_preferences
def get_statistics(
    account: Optional[str] = None,
    scope: str = "account_overview",
    sender: Optional[str] = None,
    mailbox: Optional[str] = None,
    days_back: int = 30,
    output_format: str = "text",
    timeout: Optional[int] = None,
) -> Union[str, Dict[str, Any]]:
    """
    Get comprehensive email statistics and analytics.

    For ``account_overview`` and ``sender_stats``, scans the 20 largest
    mailboxes on the account, up to 500 most-recent messages each, to keep
    AppleScript wall time predictable on Exchange / Gmail accounts with deep
    history. ``mailbox_breakdown`` is bounded by Mail.app's own count APIs
    and is not capped.

    Args:
        account: Account name (e.g., "Gmail", "Work"). Falls back to
            ``DEFAULT_MAIL_ACCOUNT`` when None.
        scope: Analysis scope: "account_overview", "sender_stats", "mailbox_breakdown"
        sender: Specific sender for "sender_stats" scope
        mailbox: Specific mailbox for "mailbox_breakdown" scope
        days_back: Number of days to analyze (default: 30, 0 = all time)
        output_format: ``text`` (default, human-readable) or ``json`` (structured dict).
        timeout: Optional AppleScript timeout in seconds. Defaults to 120s.

    Returns:
        Formatted statistics report with metrics and insights, or a structured
        dict when ``output_format="json"``.
    """

    if output_format not in {"text", "json"}:
        return "Error: Invalid output_format. Use: text, json"

    if account is None:
        account = _server.DEFAULT_MAIL_ACCOUNT
    if not account:
        if output_format == "json":
            return _statistics_json_error(
                "account_required",
                days_back=days_back,
                scope=scope,
                message="account is required (no DEFAULT_MAIL_ACCOUNT configured)",
            )
        return "Error: 'account' is required (no DEFAULT_MAIL_ACCOUNT configured)"

    validation_timeout = 30 if timeout is None else min(timeout, 30)
    account_err = validate_account_name(account, timeout=validation_timeout)
    if account_err:
        if output_format == "json":
            return _statistics_json_error(
                "account_not_found",
                account=account,
                days_back=days_back,
                scope=scope,
            )
        return account_err

    # Escape user inputs for AppleScript
    escaped_account = escape_applescript(account)
    escaped_sender = escape_applescript(sender) if sender else None
    escaped_mailbox = escape_applescript(mailbox) if mailbox else None

    # Caps for the triple-nested scan. See module docstring above.
    max_mailboxes = 20
    max_messages_per_mailbox = 500

    # Calculate date threshold if days_back > 0
    date_filter = ""
    if days_back > 0:
        date_filter = f'''
            set targetDate to (current date) - ({days_back} * days)
        '''

    # Build skip folders condition from constants
    skip_folder_checks = ' and '.join(
        f'mailboxName is not "{f}"' for f in SKIP_FOLDERS
    )

    if scope == "account_overview":
        script = f'''
        tell application "Mail"
            set outputText to "╔══════════════════════════════════════════╗" & return
            set outputText to outputText & "║      EMAIL STATISTICS - {escaped_account}       ║" & return
            set outputText to outputText & "╚══════════════════════════════════════════╝" & return & return

            {date_filter}

            try
                set targetAccount to account "{escaped_account}"
                set allMailboxes to every mailbox of targetAccount
                -- Cap mailbox scan to the first {max_mailboxes} mailboxes
                if (count of allMailboxes) > {max_mailboxes} then
                    set allMailboxes to items 1 thru {max_mailboxes} of allMailboxes
                end if

                -- Initialize counters
                set totalEmails to 0
                set totalUnread to 0
                set totalRead to 0
                set totalFlagged to 0
                set totalWithAttachments to 0
                set senderCounts to {{}}
                set mailboxCounts to {{}}

                -- Analyze all mailboxes
                repeat with aMailbox in allMailboxes
                    try
                        set mailboxName to name of aMailbox

                        -- Skip system folders
                        if {skip_folder_checks} then

                            -- Bind a bounded newest-first slice. Avoid broad
                            -- `every message ... whose date ...` filters:
                            -- Mail.app may materialize remote mailboxes before
                            -- filtering and trigger large downloads.
                            try
                                set mailboxMessages to messages 1 thru {max_messages_per_mailbox} of aMailbox
                            on error
                                set mailboxMessages to messages of aMailbox
                            end try
                            set mailboxTotal to 0

                            repeat with aMessage in mailboxMessages
                                try
                                    if {days_back} > 0 then
                                        set messageDate to date received of aMessage
                                        if messageDate < targetDate then exit repeat
                                    end if

                                    set totalEmails to totalEmails + 1
                                    set mailboxTotal to mailboxTotal + 1

                                    -- Count read/unread
                                    if read status of aMessage then
                                        set totalRead to totalRead + 1
                                    else
                                        set totalUnread to totalUnread + 1
                                    end if

                                    -- Count flagged
                                    try
                                        if flagged status of aMessage then
                                            set totalFlagged to totalFlagged + 1
                                        end if
                                    end try

                                    -- Count attachments
                                    set attachmentCount to count of mail attachments of aMessage
                                    if attachmentCount > 0 then
                                        set totalWithAttachments to totalWithAttachments + 1
                                    end if

                                    -- Track senders (top 10)
                                    set messageSender to sender of aMessage
                                    set senderFound to false
                                    repeat with senderPair in senderCounts
                                        if item 1 of senderPair is messageSender then
                                            set item 2 of senderPair to (item 2 of senderPair) + 1
                                            set senderFound to true
                                            exit repeat
                                        end if
                                    end repeat
                                    if not senderFound then
                                        set end of senderCounts to {{messageSender, 1}}
                                    end if
                                end try
                            end repeat

                            -- Store mailbox counts
                            if mailboxTotal > 0 then
                                set end of mailboxCounts to {{mailboxName, mailboxTotal}}
                            end if

                        end if
                    on error
                        -- Skip mailboxes that throw errors (smart mailboxes, etc.)
                    end try
                end repeat

                -- Format output
                set outputText to outputText & "📊 VOLUME METRICS" & return
                set outputText to outputText & "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" & return
                set outputText to outputText & "Total Emails: " & totalEmails & return
                if totalEmails > 0 then
                    set outputText to outputText & "Unread: " & totalUnread & " (" & (round ((totalUnread / totalEmails) * 100)) & "%)" & return
                    set outputText to outputText & "Read: " & totalRead & " (" & (round ((totalRead / totalEmails) * 100)) & "%)" & return
                    set outputText to outputText & "Flagged: " & totalFlagged & return
                    set outputText to outputText & "With Attachments: " & totalWithAttachments & " (" & (round ((totalWithAttachments / totalEmails) * 100)) & "%)" & return
                else
                    set outputText to outputText & "Unread: 0" & return
                    set outputText to outputText & "Read: 0" & return
                    set outputText to outputText & "Flagged: 0" & return
                    set outputText to outputText & "With Attachments: 0" & return
                end if
                set outputText to outputText & return

                -- Top senders (show top 5)
                set outputText to outputText & "👥 TOP SENDERS" & return
                set outputText to outputText & "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" & return
                set topCount to 0
                repeat with senderPair in senderCounts
                    set topCount to topCount + 1
                    if topCount > 5 then exit repeat
                    set outputText to outputText & item 1 of senderPair & ": " & item 2 of senderPair & " emails" & return
                end repeat
                set outputText to outputText & return

                -- Mailbox distribution (show top 5)
                set outputText to outputText & "📁 MAILBOX DISTRIBUTION" & return
                set outputText to outputText & "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" & return
                set topCount to 0
                repeat with mailboxPair in mailboxCounts
                    set topCount to topCount + 1
                    if topCount > 5 then exit repeat
                    if totalEmails > 0 then
                        set mailboxPercent to round ((item 2 of mailboxPair / totalEmails) * 100)
                        set outputText to outputText & item 1 of mailboxPair & ": " & item 2 of mailboxPair & " (" & mailboxPercent & "%)" & return
                    else
                        set outputText to outputText & item 1 of mailboxPair & ": " & item 2 of mailboxPair & return
                    end if
                end repeat

            on error errMsg
                return "Error: " & errMsg
            end try

            return outputText
        end tell
        '''

    elif scope == "sender_stats":
        if not sender:
            if output_format == "json":
                return _statistics_json_error(
                    "sender_required",
                    account=account,
                    days_back=days_back,
                    scope=scope,
                    message="'sender' parameter required for sender_stats scope",
                )
            return "Error: 'sender' parameter required for sender_stats scope"

        script = f'''
        tell application "Mail"
            set outputText to "SENDER STATISTICS" & return & return
            set outputText to outputText & "Sender: {escaped_sender}" & return
            set outputText to outputText & "Account: {escaped_account}" & return & return

            {date_filter}

            try
                set targetAccount to account "{escaped_account}"
                set allMailboxes to every mailbox of targetAccount
                -- Cap mailbox scan to the first {max_mailboxes} mailboxes
                if (count of allMailboxes) > {max_mailboxes} then
                    set allMailboxes to items 1 thru {max_mailboxes} of allMailboxes
                end if

                set totalFromSender to 0
                set unreadFromSender to 0
                set withAttachments to 0

                repeat with aMailbox in allMailboxes
                    try
                        set mailboxName to name of aMailbox

                        -- Skip system folders
                        if {skip_folder_checks} then

                            try
                                set matchedMessages to messages 1 thru {max_messages_per_mailbox} of aMailbox
                            on error
                                set matchedMessages to messages of aMailbox
                            end try

                            repeat with aMessage in matchedMessages
                                try
                                    if {days_back} > 0 then
                                        set messageDate to date received of aMessage
                                        if messageDate < targetDate then exit repeat
                                    end if

                                    set messageSender to sender of aMessage
                                    set senderMatches to false
                                    ignoring case
                                        if messageSender contains "{escaped_sender}" then set senderMatches to true
                                    end ignoring

                                    if senderMatches then
                                        set totalFromSender to totalFromSender + 1

                                        if not (read status of aMessage) then
                                            set unreadFromSender to unreadFromSender + 1
                                        end if

                                        if (count of mail attachments of aMessage) > 0 then
                                            set withAttachments to withAttachments + 1
                                        end if
                                    end if
                                end try
                            end repeat

                        end if
                    on error
                        -- Skip mailboxes that throw errors (smart mailboxes, etc.)
                    end try
                end repeat

                set outputText to outputText & "Total emails: " & totalFromSender & return
                set outputText to outputText & "Unread: " & unreadFromSender & return
                set outputText to outputText & "With attachments: " & withAttachments & return

            on error errMsg
                return "Error: " & errMsg
            end try

            return outputText
        end tell
        '''

    elif scope == "mailbox_breakdown":
        mailbox_param = escaped_mailbox if mailbox else "INBOX"

        script = f'''
        tell application "Mail"
            set outputText to "MAILBOX STATISTICS" & return & return
            set outputText to outputText & "Mailbox: {mailbox_param}" & return
            set outputText to outputText & "Account: {escaped_account}" & return & return

            try
                set targetAccount to account "{escaped_account}"
                try
                    set targetMailbox to mailbox "{mailbox_param}" of targetAccount
                on error
                    if "{mailbox_param}" is "INBOX" then
                        set targetMailbox to mailbox "Inbox" of targetAccount
                    else
                        error "Mailbox not found"
                    end if
                end try

                -- Use Mail's own count APIs to avoid materializing the full
                -- message list on large mailboxes.
                set totalMessages to count of messages of targetMailbox
                set unreadMessages to unread count of targetMailbox

                set outputText to outputText & "Total messages: " & totalMessages & return
                set outputText to outputText & "Unread: " & unreadMessages & return
                set outputText to outputText & "Read: " & (totalMessages - unreadMessages) & return

            on error errMsg
                return "Error: " & errMsg
            end try

            return outputText
        end tell
        '''

    else:
        if output_format == "json":
            return _statistics_json_error(
                "invalid_scope",
                account=account,
                days_back=days_back,
                scope=scope,
                message=(
                    f"Invalid scope '{scope}'. "
                    "Use: account_overview, sender_stats, mailbox_breakdown"
                ),
            )
        return f"Error: Invalid scope '{scope}'. Use: account_overview, sender_stats, mailbox_breakdown"

    try:
        result = run_applescript(
            script, timeout=timeout if timeout is not None else 120
        )
    except AppleScriptTimeout:
        timeout_msg = (
            f"Error: AppleScript timed out while computing statistics for '{account}'"
        )
        if output_format == "json":
            return _statistics_json_error(
                "timeout",
                account=account,
                days_back=days_back,
                scope=scope,
                message=timeout_msg,
            )
        return timeout_msg

    if output_format == "json":
        if result.startswith("Error:"):
            return _statistics_json_error(
                "applescript_error",
                account=account,
                days_back=days_back,
                scope=scope,
                message=result,
            )
        statistics = _parse_statistics_text(scope, result)
        return _format_statistics_json(
            scope=scope,
            account=account,
            days_back=days_back,
            statistics=statistics,
            sender=sender,
            mailbox=mailbox,
        )

    return result


@mcp.tool(annotations=WRITE_TOOL_ANNOTATIONS)
@inject_preferences
def export_emails(
    account: Optional[str] = None,
    scope: str = "entire_mailbox",
    subject_keyword: Optional[str] = None,
    mailbox: str = "INBOX",
    save_directory: str = "~/Desktop",
    format: str = "txt",
    max_emails: int = 1000,
    timeout: Optional[int] = None,
) -> str:
    """
    Export emails to files for backup or analysis.

    For ``entire_mailbox`` exports, the AppleScript binds only the first
    ``max_emails`` messages (``items 1 thru max_emails``) so the full message
    list of a 24K-message Exchange mailbox is never materialized.

    Args:
        account: Account name (e.g., "Gmail", "Work"). Falls back to
            ``DEFAULT_MAIL_ACCOUNT`` when None.
        scope: Export scope: "single_email" (requires subject_keyword) or "entire_mailbox"
        subject_keyword: Keyword to find email (required for single_email)
        mailbox: Mailbox to export from (default: "INBOX")
        save_directory: Directory to save exports (default: "~/Desktop")
        format: Export format: "txt", "html" (default: "txt")
        max_emails: Maximum number of emails to export for entire_mailbox (default: 1000, safety cap)
        timeout: Optional AppleScript timeout in seconds. Defaults to 120s.

    Returns:
        Confirmation message with export location
    """

    if account is None:
        account = _server.DEFAULT_MAIL_ACCOUNT
    if not account:
        return "Error: 'account' is required (no DEFAULT_MAIL_ACCOUNT configured)"

    validation_timeout = 30 if timeout is None else min(timeout, 30)
    account_err = validate_account_name(account, timeout=validation_timeout)
    if account_err:
        return account_err

    path_err = validate_save_path(save_directory)
    if path_err:
        return path_err

    save_dir = os.path.realpath(os.path.expanduser(save_directory))

    # Escape all user inputs for AppleScript
    safe_account = escape_applescript(account)
    safe_mailbox = escape_applescript(mailbox)
    safe_format = escape_applescript(format)
    safe_save_dir = escape_applescript(save_dir)

    if scope == "single_email":
        if not subject_keyword:
            return "Error: 'subject_keyword' required for single_email scope"

        safe_subject_keyword = escape_applescript(subject_keyword)

        script = f'''
        tell application "Mail"
            set outputText to "EXPORTING EMAIL" & return & return

            try
                set targetAccount to account "{safe_account}"
                -- Try to get mailbox
                try
                    set targetMailbox to mailbox "{safe_mailbox}" of targetAccount
                on error
                    if "{safe_mailbox}" is "INBOX" then
                        set targetMailbox to mailbox "Inbox" of targetAccount
                    else
                        error "Mailbox not found: {safe_mailbox}"
                    end if
                end try

                -- Use `whose` for app-level filtering and cap to the first match
                -- so we don't enumerate a 24K-message mailbox just to find one
                -- subject hit.
                set matchedMessages to (every message of targetMailbox whose subject contains "{safe_subject_keyword}")
                set foundMessage to missing value
                if (count of matchedMessages) > 0 then
                    set foundMessage to item 1 of matchedMessages
                end if

                if foundMessage is not missing value then
                    set messageSubject to subject of foundMessage
                    set messageSender to sender of foundMessage
                    set messageDate to date received of foundMessage
                    set messageContent to content of foundMessage

                    -- Create safe filename
                    set safeSubject to messageSubject
                    set AppleScript's text item delimiters to "/"
                    set safeSubjectParts to text items of safeSubject
                    set AppleScript's text item delimiters to "-"
                    set safeSubject to safeSubjectParts as string
                    set AppleScript's text item delimiters to ""

                    set fileName to safeSubject & ".{safe_format}"
                    set filePath to "{safe_save_dir}/" & fileName

                    -- Prepare export content
                    if "{safe_format}" is "txt" then
                        set exportContent to "Subject: " & messageSubject & return
                        set exportContent to exportContent & "From: " & messageSender & return
                        set exportContent to exportContent & "Date: " & (messageDate as string) & return & return
                        set exportContent to exportContent & messageContent
                    else if "{safe_format}" is "html" then
                        set exportContent to "<html><body>"
                        set exportContent to exportContent & "<h2>" & messageSubject & "</h2>"
                        set exportContent to exportContent & "<p><strong>From:</strong> " & messageSender & "</p>"
                        set exportContent to exportContent & "<p><strong>Date:</strong> " & (messageDate as string) & "</p>"
                        set exportContent to exportContent & "<hr>" & messageContent
                        set exportContent to exportContent & "</body></html>"
                    end if

                    -- Write to file
                    set fileRef to open for access POSIX file filePath with write permission
                    set eof of fileRef to 0
                    write exportContent to fileRef as «class utf8»
                    close access fileRef

                    set outputText to outputText & "✓ Email exported successfully!" & return & return
                    set outputText to outputText & "Subject: " & messageSubject & return
                    set outputText to outputText & "Saved to: " & filePath & return

                else
                    set outputText to outputText & "⚠ No email found matching: {safe_subject_keyword}" & return
                end if

            on error errMsg
                try
                    close access file filePath
                end try
                return "Error: " & errMsg
            end try

            return outputText
        end tell
        '''

    elif scope == "entire_mailbox":
        script = f'''
        tell application "Mail"
            set outputText to "EXPORTING MAILBOX" & return & return

            try
                set targetAccount to account "{safe_account}"
                -- Try to get mailbox
                try
                    set targetMailbox to mailbox "{safe_mailbox}" of targetAccount
                on error
                    if "{safe_mailbox}" is "INBOX" then
                        set targetMailbox to mailbox "Inbox" of targetAccount
                    else
                        error "Mailbox not found: {safe_mailbox}"
                    end if
                end try

                -- Use Mail's count API for the headline total, then bind
                -- only the first max_emails messages to avoid materializing
                -- the entire mailbox on large Exchange/Gmail accounts.
                set messageCount to count of messages of targetMailbox
                if messageCount > {max_emails} then
                    set mailboxMessages to messages 1 thru {max_emails} of targetMailbox
                else
                    set mailboxMessages to messages of targetMailbox
                end if
                set exportCount to 0

                -- Create export directory
                set exportDir to "{safe_save_dir}/{safe_mailbox}_export"
                do shell script "mkdir -p " & quoted form of exportDir

                repeat with aMessage in mailboxMessages
                    if exportCount >= {max_emails} then exit repeat

                    try
                        set messageSubject to subject of aMessage
                        set messageSender to sender of aMessage
                        set messageDate to date received of aMessage
                        set messageContent to content of aMessage

                        -- Create safe filename with index
                        set exportCount to exportCount + 1
                        set fileName to exportCount & "_" & messageSubject & ".{safe_format}"

                        -- Remove unsafe characters
                        set AppleScript's text item delimiters to "/"
                        set fileNameParts to text items of fileName
                        set AppleScript's text item delimiters to "-"
                        set fileName to fileNameParts as string
                        set AppleScript's text item delimiters to ""

                        set filePath to exportDir & "/" & fileName

                        -- Prepare export content
                        if "{safe_format}" is "txt" then
                            set exportContent to "Subject: " & messageSubject & return
                            set exportContent to exportContent & "From: " & messageSender & return
                            set exportContent to exportContent & "Date: " & (messageDate as string) & return & return
                            set exportContent to exportContent & messageContent
                        else if "{safe_format}" is "html" then
                            set exportContent to "<html><body>"
                            set exportContent to exportContent & "<h2>" & messageSubject & "</h2>"
                            set exportContent to exportContent & "<p><strong>From:</strong> " & messageSender & "</p>"
                            set exportContent to exportContent & "<p><strong>Date:</strong> " & (messageDate as string) & "</p>"
                            set exportContent to exportContent & "<hr>" & messageContent
                            set exportContent to exportContent & "</body></html>"
                        end if

                        -- Write to file
                        set fileRef to open for access POSIX file filePath with write permission
                        set eof of fileRef to 0
                        write exportContent to fileRef as «class utf8»
                        close access fileRef

                    on error
                        -- Continue with next email if one fails
                    end try
                end repeat

                set outputText to outputText & "✓ Mailbox exported successfully!" & return & return
                set outputText to outputText & "Mailbox: {safe_mailbox}" & return
                set outputText to outputText & "Total emails in mailbox: " & messageCount & return
                set outputText to outputText & "Exported: " & exportCount & return
                if exportCount < messageCount then
                    set outputText to outputText & "(capped at max_emails={max_emails})" & return
                end if
                set outputText to outputText & "Location: " & exportDir & return

            on error errMsg
                return "Error: " & errMsg
            end try

            return outputText
        end tell
        '''

    else:
        return f"Error: Invalid scope '{scope}'. Use: single_email, entire_mailbox"

    try:
        result = run_applescript(
            script, timeout=timeout if timeout is not None else 120
        )
    except AppleScriptTimeout:
        return f"Error: AppleScript timed out while exporting emails for '{account}'"
    return result


def _build_recent_one_account_script(
    account: str,
    max_per_account: int,
    include_preview: bool,
) -> str:
    """Build AppleScript that returns recent inbox messages for one account."""
    escaped_account = escape_applescript(account)
    preview_block = ""
    preview_field = '""'
    if include_preview:
        preview_block = '''
                        set messagePreview to ""
                        try
                            set msgContent to content of aMessage
                            if length of msgContent > 150 then
                                set messagePreview to text 1 thru 150 of msgContent
                            else
                                set messagePreview to msgContent
                            end if
                            set AppleScript's text item delimiters to {return, linefeed}
                            set contentParts to text items of messagePreview
                            set AppleScript's text item delimiters to " "
                            set messagePreview to contentParts as string
                            set AppleScript's text item delimiters to ""
                        end try
        '''
        preview_field = "messagePreview"

    return f'''
    tell application "Mail"
        set resultLines to {{}}
        try
            set anAccount to account "{escaped_account}"
            set accountName to name of anAccount
            {inbox_mailbox_script("inboxMailbox", "anAccount")}

            if (count of messages of inboxMailbox) > {max_per_account} then
                set inboxMessages to messages 1 thru {max_per_account} of inboxMailbox
            else
                set inboxMessages to messages of inboxMailbox
            end if

            repeat with aMessage in inboxMessages
                try
                    set messageSubject to subject of aMessage
                    set messageSender to sender of aMessage
                    set messageDate to date received of aMessage
                    set messageRead to read status of aMessage
                    {preview_block}
                    set end of resultLines to messageSubject & "|||" & messageSender & "|||" & (messageDate as string) & "|||" & messageRead & "|||" & accountName & "|||" & {preview_field}
                end try
            end repeat
        end try
        set AppleScript's text item delimiters to linefeed
        return resultLines as string
    end tell
    '''


def _parse_recent_email_lines(result: str) -> List[Dict[str, Any]]:
    emails: List[Dict[str, Any]] = []
    if not result:
        return emails
    for line in result.split("\n"):
        if "|||" not in line:
            continue
        parts = line.split("|||", 5)
        if len(parts) >= 5:
            emails.append({
                "subject": parts[0].strip(),
                "sender": parts[1].strip(),
                "date": parts[2].strip(),
                "is_read": parts[3].strip().lower() == "true",
                "account": parts[4].strip(),
                "preview": parts[5].strip() if len(parts) > 5 else "",
            })
    return emails


def _get_recent_emails_structured(
    max_total: int = 20,
    max_per_account: int = 10,
    include_preview: bool = False,
    timeout: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Internal helper to get recent emails from all accounts as structured data.
    Runs one AppleScript per account sequentially (use async variant for dashboard).
    """
    accounts = list_mail_account_names(timeout=30 if timeout is None else min(timeout, 30))
    emails: List[Dict[str, Any]] = []
    for account in accounts:
        script = _build_recent_one_account_script(account, max_per_account, include_preview)
        try:
            result = run_applescript(
                script, timeout=timeout if timeout is not None else 60
            )
        except AppleScriptTimeout:
            continue
        emails.extend(_parse_recent_email_lines(result))
        if len(emails) >= max_total:
            break
    return emails[:max_total]


async def _get_recent_emails_structured_async(
    max_total: int = 20,
    max_per_account: int = 10,
    include_preview: bool = False,
    timeout: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Fetch recent emails per account in parallel."""
    try:
        accounts = await asyncio.to_thread(list_mail_account_names, timeout)
    except AppleScriptTimeout:
        return []

    per_call_timeout = timeout if timeout is not None else 60

    async def run_one(account: str):
        script = _build_recent_one_account_script(
            account, max_per_account, include_preview
        )
        try:
            raw = await asyncio.to_thread(
                run_applescript, script, per_call_timeout
            )
            return _parse_recent_email_lines(raw)
        except AppleScriptTimeout:
            return []

    batches = await asyncio.gather(*(run_one(a) for a in accounts))
    combined: List[Dict[str, Any]] = []
    for batch in batches:
        combined.extend(batch)
    return combined[:max_total]


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
@inject_preferences
async def inbox_dashboard(
    include_preview: bool = False,
    max_total: int = 20,
    max_per_account: int = 10,
    timeout: Optional[int] = None,
) -> Any:
    """
    Get an interactive dashboard view of your email inbox.

    Returns an interactive UI dashboard resource that displays:
    - Unread email counts by account (visual cards with badges)
    - Recent emails across all accounts (filterable list)
    - Quick action buttons for common operations (Mark Read, Archive, Delete)
    - Search functionality to filter emails

    This tool returns a UIResource that can be rendered by compatible
    MCP clients (like Claude Desktop with MCP Apps support) to provide
    an interactive dashboard experience.

    Args:
        include_preview: Include body previews for recent emails (slower; default False).
        max_total: Maximum recent emails across all accounts (default: 20).
        max_per_account: Maximum recent emails per account (default: 10).
        timeout: Optional per-call AppleScript timeout in seconds (default: 60).

    Note: Requires mcp-ui-server package and a compatible MCP client.

    Returns:
        UIResource with uri "ui://apple-mail/inbox-dashboard" containing
        an interactive HTML dashboard, or error message if UI is unavailable.
    """
    from apple_mail_mcp import UI_AVAILABLE
    if not UI_AVAILABLE:
        return "Error: UI module not available. Please install mcp-ui-server package."

    from apple_mail_mcp.tools.inbox import get_mailbox_unread_counts
    from ui import create_inbox_dashboard_ui

    per_call_timeout = timeout if timeout is not None else 60

    unread_task = asyncio.to_thread(
        get_mailbox_unread_counts, summary_only=True
    )
    recent_task = _get_recent_emails_structured_async(
        max_total=max_total,
        max_per_account=max_per_account,
        include_preview=include_preview,
        timeout=per_call_timeout,
    )
    accounts_data, recent_emails = await asyncio.gather(unread_task, recent_task)

    return create_inbox_dashboard_ui(
        accounts_data=accounts_data,
        recent_emails=recent_emails,
    )

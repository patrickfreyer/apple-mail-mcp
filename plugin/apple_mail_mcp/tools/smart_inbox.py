"""Smart inbox tools: follow-up tracking, actionable email detection, and sender analytics."""

import asyncio
from collections import Counter
from dataclasses import dataclass
from typing import Optional

from apple_mail_mcp import server as _server
from apple_mail_mcp.server import mcp, READ_ONLY_TOOL_ANNOTATIONS
from apple_mail_mcp.core import (
    AppleScriptTimeout,
    inject_preferences,
    escape_applescript,
    run_applescript,
    inbox_mailbox_script,
    date_cutoff_script,
    validate_account_name,
)
from apple_mail_mcp.constants import (
    NEWSLETTER_PLATFORM_PATTERNS,
    NEWSLETTER_KEYWORD_PATTERNS,
    THREAD_PREFIXES,
)


def _strip_subject_prefixes_script() -> str:
    """Return AppleScript handler to strip Re:/Fwd:/etc prefixes from a subject."""
    # Build a list of prefixes to strip
    prefix_checks = ""
    for prefix in THREAD_PREFIXES:
        escaped = escape_applescript(prefix)
        prefix_checks += f'''
                ignoring case
                    if baseSubj starts with "{escaped}" then
                        set baseSubj to text {len(prefix) + 1} thru -1 of baseSubj
                        -- trim leading space
                        repeat while baseSubj starts with " "
                            set baseSubj to text 2 thru -1 of baseSubj
                        end repeat
                        set didStrip to true
                    end if
                end ignoring
'''
    return f'''
    on stripPrefixes(subj)
        set baseSubj to subj
        set didStrip to true
        repeat while didStrip
            set didStrip to false
            {prefix_checks}
        end repeat
        return baseSubj
    end stripPrefixes
'''


def _newsletter_filter_condition(sender_var: str = "messageSender") -> str:
    """Return AppleScript condition that evaluates to true if email is a newsletter.

    Must be evaluated inside an ``ignoring case`` block — uses raw sender
    text (no longer lowercased) so case-folding is the AppleScript engine's
    job, not a per-message shell-out.
    """
    platform_checks = " or ".join(
        f'{sender_var} contains "{escape_applescript(p)}"'
        for p in NEWSLETTER_PLATFORM_PATTERNS
    )
    keyword_checks = " or ".join(
        f'{sender_var} contains "{escape_applescript(k)}"'
        for k in NEWSLETTER_KEYWORD_PATTERNS
    )
    return f"({platform_checks} or {keyword_checks})"


def _strip_subject_prefixes(subject: str) -> str:
    base = subject.strip()
    changed = True
    while changed:
        changed = False
        for prefix in THREAD_PREFIXES:
            if base.casefold().startswith(prefix.casefold()):
                base = base[len(prefix) :].lstrip()
                changed = True
                break
    return base


def _is_noreply_recipient(address: str) -> bool:
    lower = address.casefold()
    return any(
        token in lower
        for token in ("noreply", "no-reply", "do-not-reply", "donotreply")
    )


def _sent_mailbox_script(var_name: str, account_var: str) -> str:
    return f'''
            set {var_name} to missing value
            try
                set {var_name} to mailbox "Sent Messages" of {account_var}
            on error
                try
                    set {var_name} to mailbox "Sent" of {account_var}
                on error
                    try
                        set {var_name} to mailbox "Sent Items" of {account_var}
                    on error
                        return "Error: Could not find Sent mailbox"
                    end try
                end try
            end try
    '''


@dataclass(frozen=True)
class _AwaitingReplyInboxRow:
    subject: str
    sender: str


@dataclass(frozen=True)
class _AwaitingReplySentRow:
    subject: str
    recipient_address: str
    recipient_name: str
    sent_at: str


def _subjects_likely_match(sent_subject: str, inbox_subject: str) -> bool:
    sent_base = _strip_subject_prefixes(sent_subject)
    inbox_base = _strip_subject_prefixes(inbox_subject)
    sent_fold = sent_base.casefold()
    inbox_fold = inbox_base.casefold()
    return inbox_fold in sent_fold or sent_fold in inbox_fold


def _inbox_sender_matches_recipient(inbox_sender: str, recipient_address: str) -> bool:
    return recipient_address.casefold() in inbox_sender.casefold()


def _parse_awaiting_reply_inbox_rows(raw: str) -> list[_AwaitingReplyInboxRow]:
    rows: list[_AwaitingReplyInboxRow] = []
    for line in raw.splitlines():
        if not line.startswith("INBOX|||"):
            continue
        parts = line.split("|||", 2)
        if len(parts) == 3:
            rows.append(_AwaitingReplyInboxRow(subject=parts[1], sender=parts[2]))
    return rows


def _parse_awaiting_reply_sent_rows(raw: str) -> list[_AwaitingReplySentRow]:
    rows: list[_AwaitingReplySentRow] = []
    for line in raw.splitlines():
        if not line.startswith("SENT|||"):
            continue
        parts = line.split("|||", 4)
        if len(parts) == 5:
            rows.append(
                _AwaitingReplySentRow(
                    subject=parts[1],
                    recipient_address=parts[2],
                    recipient_name=parts[3],
                    sent_at=parts[4],
                )
            )
    return rows


def _has_reply_in_inbox(
    sent_row: _AwaitingReplySentRow,
    inbox_rows: list[_AwaitingReplyInboxRow],
) -> bool:
    for inbox_row in inbox_rows:
        if not _subjects_likely_match(sent_row.subject, inbox_row.subject):
            continue
        if _inbox_sender_matches_recipient(
            inbox_row.sender, sent_row.recipient_address
        ):
            return True
    return False


def _format_awaiting_reply_results(
    *,
    account: str,
    days_back: int,
    sent_rows: list[_AwaitingReplySentRow],
    inbox_rows: list[_AwaitingReplyInboxRow],
    exclude_noreply: bool,
    max_results: int,
) -> str:
    lines = [
        "EMAILS AWAITING REPLY",
        f"Account: {account} | Last {days_back} days",
        "========================================",
        "",
    ]
    awaiting: list[_AwaitingReplySentRow] = []
    for sent_row in sent_rows:
        if len(awaiting) >= max_results:
            break
        if exclude_noreply and _is_noreply_recipient(sent_row.recipient_address):
            continue
        if _has_reply_in_inbox(sent_row, inbox_rows):
            continue
        awaiting.append(sent_row)

    for index, sent_row in enumerate(awaiting, start=1):
        if sent_row.recipient_name:
            display_recip = (
                f"{sent_row.recipient_name} <{sent_row.recipient_address}>"
            )
        else:
            display_recip = sent_row.recipient_address
        lines.append(f"{index}. {sent_row.subject}")
        lines.append(f"   To: {display_recip}")
        lines.append(f"   Sent: {sent_row.sent_at}")
        lines.append("")

    lines.append("========================================")
    lines.append(f"Found {len(awaiting)} sent email(s) awaiting reply.")
    return "\n".join(lines)


def _build_awaiting_reply_inbox_script(
    *,
    escaped_account: str,
    inbox_cap: int,
    days_back: int,
) -> str:
    inbox_date_check = (
        "if messageDate < cutoffDate then exit repeat" if days_back > 0 else ""
    )
    return f'''
    tell application "Mail"
        try
            set targetAccount to account "{escaped_account}"
            {inbox_mailbox_script("inboxMailbox", "targetAccount")}
            {date_cutoff_script(days_back, "cutoffDate")}

            set inboxMessages to {{}}
            set inboxCount to count of messages of inboxMailbox
            if inboxCount > {inbox_cap} then
                set inboxUpperBound to {inbox_cap}
            else
                set inboxUpperBound to inboxCount
            end if
            if inboxUpperBound > 0 then
                set inboxMessages to messages 1 thru inboxUpperBound of inboxMailbox
            end if

            set outputLines to {{}}
            repeat with aMessage in inboxMessages
                try
                    set messageDate to date received of aMessage
                    {inbox_date_check}
                    set msgSubject to subject of aMessage
                    set msgSender to sender of aMessage
                    set end of outputLines to "INBOX|||" & msgSubject & "|||" & msgSender
                end try
            end repeat

            set AppleScript's text item delimiters to linefeed
            return outputLines as string
        on error errMsg
            return "Error: " & errMsg
        end try
    end tell
    '''


def _build_awaiting_reply_sent_script(
    *,
    escaped_account: str,
    sent_cap: int,
    days_back: int,
) -> str:
    sent_date_check = (
        "if messageDate < cutoffDate then exit repeat" if days_back > 0 else ""
    )
    return f'''
    tell application "Mail"
        try
            set targetAccount to account "{escaped_account}"
            {_sent_mailbox_script("sentMailbox", "targetAccount")}
            {date_cutoff_script(days_back, "cutoffDate")}

            set sentMessages to {{}}
            set sentCount to count of messages of sentMailbox
            if sentCount > {sent_cap} then
                set sentUpperBound to {sent_cap}
            else
                set sentUpperBound to sentCount
            end if
            if sentUpperBound > 0 then
                set sentMessages to messages 1 thru sentUpperBound of sentMailbox
            end if

            set outputLines to {{}}
            repeat with aMessage in sentMessages
                try
                    set messageDate to date sent of aMessage
                    {sent_date_check}
                    set messageSubject to subject of aMessage
                    set messageRecipients to every to recipient of aMessage
                    if (count of messageRecipients) > 0 then
                        set recipAddr to address of item 1 of messageRecipients
                        set recipName to ""
                        try
                            set recipName to name of item 1 of messageRecipients
                        end try
                        set end of outputLines to "SENT|||" & messageSubject & "|||" & recipAddr & "|||" & recipName & "|||" & (messageDate as string)
                    end if
                end try
            end repeat

            set AppleScript's text item delimiters to linefeed
            return outputLines as string
        on error errMsg
            return "Error: " & errMsg
        end try
    end tell
    '''


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
@inject_preferences
def get_awaiting_reply(
    account: Optional[str] = None,
    days_back: int = 7,
    exclude_noreply: bool = True,
    max_results: int = 20,
    timeout: Optional[int] = None,
) -> str:
    """Find sent emails that haven't received a reply yet.

    Scans the Sent mailbox for outgoing emails and cross-references with
    the Inbox to see if a reply (matching subject) was received from the
    same recipient. Useful for follow-up tracking.

    Args:
        account: Account name (e.g., "Gmail", "Work", "Personal").
            Falls back to ``DEFAULT_MAIL_ACCOUNT`` env-configured account when None.
        days_back: How many days back to check sent emails (default: 7)
        exclude_noreply: Skip emails sent to noreply/no-reply addresses (default: True)
        max_results: Maximum results to return (default: 20)
        timeout: Optional AppleScript timeout in seconds. Defaults to 120s.

    Returns:
        List of sent emails still awaiting a reply with subject, recipient, and date sent
    """
    if account is None:
        account = _server.DEFAULT_MAIL_ACCOUNT
    if not account:
        return "Error: No account specified and DEFAULT_MAIL_ACCOUNT is not set"

    validation_timeout = 30 if timeout is None else min(timeout, 30)
    account_err = validate_account_name(account, timeout=validation_timeout)
    if account_err:
        return account_err

    escaped_account = escape_applescript(account)

    sent_cap = min(max(max_results * 4, 50), 100)
    inbox_cap = 100
    inbox_script = _build_awaiting_reply_inbox_script(
        escaped_account=escaped_account,
        inbox_cap=inbox_cap,
        days_back=days_back,
    )
    sent_script = _build_awaiting_reply_sent_script(
        escaped_account=escaped_account,
        sent_cap=sent_cap,
        days_back=days_back,
    )
    effective_timeout = timeout if timeout is not None else 120

    async def _fetch_rows() -> tuple[str, str]:
        return await asyncio.gather(
            asyncio.to_thread(
                run_applescript, inbox_script, timeout=effective_timeout
            ),
            asyncio.to_thread(
                run_applescript, sent_script, timeout=effective_timeout
            ),
        )

    try:
        inbox_raw, sent_raw = asyncio.run(_fetch_rows())
    except AppleScriptTimeout:
        return (
            f"Error: get_awaiting_reply timed out on account '{account}' after "
            f"{effective_timeout}s — try increasing timeout or reducing days_back"
        )

    for raw in (inbox_raw, sent_raw):
        if raw.startswith("Error:"):
            return raw

    return _format_awaiting_reply_results(
        account=account,
        days_back=days_back,
        sent_rows=_parse_awaiting_reply_sent_rows(sent_raw),
        inbox_rows=_parse_awaiting_reply_inbox_rows(inbox_raw),
        exclude_noreply=exclude_noreply,
        max_results=max_results,
    )


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
@inject_preferences
def get_needs_response(
    account: Optional[str] = None,
    mailbox: str = "INBOX",
    days_back: int = 7,
    max_results: int = 20,
    scan_body: bool = False,
    timeout: Optional[int] = None,
) -> str:
    """Identify unread emails that likely need a response from you.

    Filters out newsletters, automated emails, and noreply senders.
    Prioritises direct emails (To: you) with question marks as likely
    needing a reply.

    Args:
        account: Account name (e.g., "Gmail", "Work", "Personal").
            Falls back to ``DEFAULT_MAIL_ACCOUNT`` env-configured account when None.
        mailbox: Mailbox to scan (default: "INBOX")
        days_back: How many days back to look (default: 7)
        max_results: Maximum results to return (default: 20)
        scan_body: When True, scan message body for question marks (slower).
            Subject-only detection is usually enough for daily triage (default: False).
        timeout: Optional AppleScript timeout in seconds. Defaults to 120s.

    Returns:
        Ranked list of emails likely needing a response, with priority hints
    """
    if account is None:
        account = _server.DEFAULT_MAIL_ACCOUNT
    if not account:
        return "Error: No account specified and DEFAULT_MAIL_ACCOUNT is not set"

    validation_timeout = 30 if timeout is None else min(timeout, 30)
    account_err = validate_account_name(account, timeout=validation_timeout)
    if account_err:
        return account_err

    escaped_account = escape_applescript(account)
    escaped_mailbox = escape_applescript(mailbox)

    newsletter_condition = _newsletter_filter_condition("messageSender")

    # Cap message collection. Tighter caps keep daily triage under agent budgets.
    inbox_cap = min(max(max_results * 5, 50), 100)
    sent_cap = 100

    body_scan_block = (
        """
                                try
                                    set msgContent to content of aMessage
                                    if length of msgContent > 500 then
                                        set msgContent to text 1 thru 500 of msgContent
                                    end if
                                    if msgContent contains "?" then set hasQuestion to true
                                end try
"""
        if scan_body
        else ""
    )

    script = f'''
    tell application "Mail"
        set outputText to "EMAILS NEEDING RESPONSE" & return
        set outputText to outputText & "Account: {escaped_account} | Mailbox: {escaped_mailbox} | Last {days_back} days" & return
        set outputText to outputText & "========================================" & return & return

        {date_cutoff_script(days_back, "cutoffDate")}

        try
            set targetAccount to account "{escaped_account}"

            -- Get target mailbox
            try
                set targetMailbox to mailbox "{escaped_mailbox}" of targetAccount
            on error
                if "{escaped_mailbox}" is "INBOX" then
                    set targetMailbox to mailbox "Inbox" of targetAccount
                else
                    error "Mailbox not found: {escaped_mailbox}"
                end if
            end try

            -- Collect sent subjects for "already replied" detection. A1: cap
            -- at {sent_cap} so we don't drag the whole Sent mailbox in.
            set sentSubjects to {{}}
            set sentMailbox to missing value
            try
                set sentMailbox to mailbox "Sent Messages" of targetAccount
            on error
                try
                    set sentMailbox to mailbox "Sent" of targetAccount
                on error
                    try
                        set sentMailbox to mailbox "Sent Items" of targetAccount
                    end try
                end try
            end try

            if sentMailbox is not missing value then
                set sentMessages to {{}}
                set sentCount to count of messages of sentMailbox
                if sentCount > {sent_cap} then
                    set sentUpperBound to {sent_cap}
                else
                    set sentUpperBound to sentCount
                end if
                if sentUpperBound > 0 then
                    set sentMessages to messages 1 thru sentUpperBound of sentMailbox
                end if
                repeat with aMessage in sentMessages
                    try
                        set sentSubj to subject of aMessage
                        set baseSent to my stripPrefixes(sentSubj)
                        set end of sentSubjects to baseSent
                    end try
                end repeat
            end if

            -- Scan a bounded newest-first slice. Do not use a broad `whose`
            -- filter here; Mail.app can materialize deep remote mailboxes
            -- before filtering and start large background downloads.
            set mailboxMessages to {{}}
            set mailboxCount to count of messages of targetMailbox
            if mailboxCount > {inbox_cap} then
                set mailboxUpperBound to {inbox_cap}
            else
                set mailboxUpperBound to mailboxCount
            end if
            if mailboxUpperBound > 0 then
                set mailboxMessages to messages 1 thru mailboxUpperBound of targetMailbox
            end if

            set highPriority to {{}}
            set normalPriority to {{}}
            set totalChecked to 0

            repeat with aMessage in mailboxMessages
                if (count of highPriority) + (count of normalPriority) >= {max_results} then exit repeat

                try
                    set messageDate to date received of aMessage
                    {"if messageDate < cutoffDate then exit repeat" if days_back > 0 else ""}

                    -- The whose-filter already restricted to unread, but keep
                    -- a defensive check for the fallback path.
                    if not (read status of aMessage) then
                        set messageSender to sender of aMessage
                        set messageSubject to subject of aMessage

                        -- Filter out newsletters and automated senders.
                        -- A4c: `ignoring case` covers both checks at once
                        -- without a per-message shell-out.
                        set isNewsletter to false
                        set isAutomated to false
                        ignoring case
                            set isNewsletter to {newsletter_condition}
                            set isAutomated to (messageSender contains "noreply" or messageSender contains "no-reply" or messageSender contains "donotreply" or messageSender contains "do-not-reply" or messageSender contains "notifications@" or messageSender contains "mailer-daemon" or messageSender contains "postmaster@")
                        end ignoring

                        if not isNewsletter and not isAutomated then
                            -- Check if user already replied
                            set baseSubject to my stripPrefixes(messageSubject)
                            set alreadyReplied to false
                            ignoring case
                                repeat with sentSubj in sentSubjects
                                    set sentSubjText to sentSubj as string
                                    if sentSubjText contains baseSubject or baseSubject contains sentSubjText then
                                        set alreadyReplied to true
                                        exit repeat
                                    end if
                                end repeat
                            end ignoring

                            if not alreadyReplied then
                                -- Determine priority
                                set hasQuestion to (messageSubject contains "?")
                                {body_scan_block}

                                set isFlagged to false
                                try
                                    set isFlagged to flagged status of aMessage
                                end try

                                set emailEntry to messageSubject & "|||" & messageSender & "|||" & (messageDate as string) & "|||"
                                if hasQuestion or isFlagged then
                                    if hasQuestion and isFlagged then
                                        set emailEntry to emailEntry & "HIGH (flagged + question)"
                                    else if isFlagged then
                                        set emailEntry to emailEntry & "HIGH (flagged)"
                                    else
                                        set emailEntry to emailEntry & "MEDIUM (contains question)"
                                    end if
                                    set end of highPriority to emailEntry
                                else
                                    set emailEntry to emailEntry & "NORMAL"
                                    set end of normalPriority to emailEntry
                                end if
                            end if
                        end if
                    end if
                end try
            end repeat

            -- Format output: high priority first, then normal
            set resultCount to 0
            repeat with entry in highPriority
                set resultCount to resultCount + 1
                set AppleScript's text item delimiters to "|||"
                set parts to text items of entry
                set AppleScript's text item delimiters to ""
                set outputText to outputText & resultCount & ". [" & item 4 of parts & "] " & item 1 of parts & return
                set outputText to outputText & "   From: " & item 2 of parts & return
                set outputText to outputText & "   Date: " & item 3 of parts & return & return
            end repeat

            repeat with entry in normalPriority
                set resultCount to resultCount + 1
                set AppleScript's text item delimiters to "|||"
                set parts to text items of entry
                set AppleScript's text item delimiters to ""
                set outputText to outputText & resultCount & ". [" & item 4 of parts & "] " & item 1 of parts & return
                set outputText to outputText & "   From: " & item 2 of parts & return
                set outputText to outputText & "   Date: " & item 3 of parts & return & return
            end repeat

            set outputText to outputText & "========================================" & return
            set outputText to outputText & "Found " & resultCount & " email(s) needing response." & return

        on error errMsg
            return "Error: " & errMsg
        end try

        return outputText
    end tell

    {_strip_subject_prefixes_script()}
    '''

    try:
        return run_applescript(script, timeout=timeout)
    except AppleScriptTimeout:
        wait_s = timeout if timeout is not None else 120
        return (
            f"Error: get_needs_response timed out on account '{account}' after "
            f"{wait_s}s — try increasing timeout or reducing days_back"
        )


@mcp.tool(annotations=READ_ONLY_TOOL_ANNOTATIONS)
@inject_preferences
def get_top_senders(
    account: Optional[str] = None,
    mailbox: str = "INBOX",
    days_back: int = 30,
    top_n: int = 10,
    group_by_domain: bool = False,
    timeout: Optional[int] = None,
) -> str:
    """Analyse a mailbox to find the most frequent senders.

    Useful for identifying key contacts, high-volume senders to filter,
    or newsletter sources to unsubscribe from.

    Args:
        account: Account name (e.g., "Gmail", "Work", "Personal").
            Falls back to ``DEFAULT_MAIL_ACCOUNT`` env-configured account when None.
        mailbox: Mailbox to analyse (default: "INBOX")
        days_back: How many days back to look (default: 30, 0 = all time)
        top_n: Number of top senders to return (default: 10)
        group_by_domain: Group results by domain instead of individual sender (default: False)
        timeout: Optional AppleScript timeout in seconds. Defaults to 120s.

    Returns:
        Ranked list of senders (or domains) with email counts
    """
    if account is None:
        account = _server.DEFAULT_MAIL_ACCOUNT
    if not account:
        return "Error: No account specified and DEFAULT_MAIL_ACCOUNT is not set"

    validation_timeout = 30 if timeout is None else min(timeout, 30)
    account_err = validate_account_name(account, timeout=validation_timeout)
    if account_err:
        return account_err

    escaped_account = escape_applescript(account)
    escaped_mailbox = escape_applescript(mailbox)

    date_cutoff = date_cutoff_script(days_back, "cutoffDate")
    date_check = "if messageDate < cutoffDate then exit repeat" if days_back > 0 else ""

    # Cap message scan. Prefer a bounded newest-first slice + Python aggregation
    # over `whose` filters that materialize huge inboxes.
    scan_cap = min(500, max(top_n * 15, 75))
    if days_back > 14:
        scan_cap = min(scan_cap, 300)
    if days_back >= 30:
        scan_cap = min(scan_cap, 100)

    # Build the extraction key: either full sender or domain.
    if group_by_domain:
        # Extract domain from email address
        extract_key = '''
                            -- Extract domain from sender address
                            set senderKey to ""
                            set atPos to 0
                            set senderLen to length of messageSender
                            repeat with i from 1 to senderLen
                                if character i of messageSender is "@" then
                                    set atPos to i
                                end if
                            end repeat
                            if atPos > 0 then
                                -- Find the closing > if present
                                set endPos to senderLen
                                repeat with i from atPos to senderLen
                                    if character i of messageSender is ">" then
                                        set endPos to i - 1
                                        exit repeat
                                    end if
                                end repeat
                                set senderKey to text (atPos + 1) thru endPos of messageSender
                            else
                                set senderKey to messageSender
                            end if
'''
        title_label = "TOP SENDER DOMAINS"
    else:
        extract_key = '''
                            set senderKey to messageSender
'''
        title_label = "TOP SENDERS"

    # Return one ROW|||sender per message; Python aggregates with Counter.
    script = f'''
    tell application "Mail"
        try
            set targetAccount to account "{escaped_account}"

            -- Get target mailbox
            try
                set targetMailbox to mailbox "{escaped_mailbox}" of targetAccount
            on error
                if "{escaped_mailbox}" is "INBOX" then
                    set targetMailbox to mailbox "Inbox" of targetAccount
                else
                    error "Mailbox not found: {escaped_mailbox}"
                end if
            end try

            {date_cutoff}

            try
                set mailboxMessages to messages 1 thru {scan_cap} of targetMailbox
            on error
                set mailboxMessages to {{}}
            end try

            set outputLines to {{}}
            set totalAnalysed to 0

            repeat with aMessage in mailboxMessages
                try
                    set messageDate to date received of aMessage
                    {date_check}

                    set messageSender to sender of aMessage
                    set totalAnalysed to totalAnalysed + 1

                    {extract_key}

                    set end of outputLines to "ROW|||" & senderKey
                end try
            end repeat

            set end of outputLines to "TOTAL|||" & (totalAnalysed as string)

            set AppleScript's text item delimiters to linefeed
            set outputText to outputLines as string
            set AppleScript's text item delimiters to ""
            return outputText

        on error errMsg
            return "ERROR|||" & errMsg
        end try
    end tell
    '''

    try:
        raw = run_applescript(script, timeout=timeout)
    except AppleScriptTimeout:
        wait_s = timeout if timeout is not None else 120
        return (
            f"Error: get_top_senders timed out on account '{account}' after "
            f"{wait_s}s — try increasing timeout or reducing days_back"
        )

    if raw.startswith("ERROR|||"):
        return f"Error: {raw.split('|||', 1)[1]}"

    # Parse ROW lines and aggregate in Python (fast Counter vs AppleScript O(n^2)).
    total_analysed = 0
    sender_counts: Counter[str] = Counter()
    for line in raw.splitlines():
        if line.startswith("TOTAL|||"):
            try:
                total_analysed = int(line.split("|||", 1)[1].strip())
            except ValueError:
                total_analysed = 0
        elif line.startswith("ROW|||"):
            key = line.split("|||", 1)[1].strip()
            if key:
                sender_counts[key] += 1

    unique_count = len(sender_counts)
    entries = sender_counts.most_common(top_n)
    top_entries = entries

    # Reproduce the original output format exactly.
    lines = [
        title_label,
        f"Account: {account} | Mailbox: {mailbox} | Last {days_back} days",
        "========================================",
        "",
    ]
    for i, (key, cnt) in enumerate(top_entries, start=1):
        if total_analysed > 0:
            pct = round((cnt / total_analysed) * 100)
            pct_text = f" ({pct}%)"
        else:
            pct_text = ""
        lines.append(f"{i}. {key}: {cnt} emails{pct_text}")

    lines.append("")
    lines.append("========================================")
    lines.append(f"Total emails analysed: {total_analysed}")
    lines.append(f"Unique senders: {unique_count}")

    return "\n".join(lines) + "\n"

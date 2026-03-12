"""Search tools: finding and filtering emails."""

import json
from typing import Optional, List, Dict, Any

from apple_mail_mcp.server import mcp
from apple_mail_mcp.core import (
    inject_preferences,
    escape_applescript,
    run_applescript,
    LOWERCASE_HANDLER,
    build_mailbox_ref,
    skip_folders_condition,
)
from apple_mail_mcp.constants import (
    SKIP_FOLDERS,
    NEWSLETTER_PLATFORM_PATTERNS,
    NEWSLETTER_KEYWORD_PATTERNS,
    THREAD_PREFIXES,
)


# ---------------------------------------------------------------------------
# Internal helpers for building AppleScript fragments
# ---------------------------------------------------------------------------

def _build_whose_clause(
    subject: Optional[str],
    sender: Optional[str],
    body: Optional[str],
    is_read: Optional[bool],
    date_from: Optional[str],
    date_to: Optional[str],
) -> tuple[str, list[str]]:
    """Build a `whose` clause for fast Mail.app-level filtering.

    Returns (date_setup_script, list_of_conditions).
    The caller joins conditions with ' and ' and wraps in `whose ...`.

    Note: AppleScript's `contains` is case-insensitive by default,
    so body/subject/sender filters don't need a lowercase handler.
    """
    conditions: list[str] = []
    date_setup = ""

    if subject:
        conditions.append(f'subject contains "{escape_applescript(subject)}"')
    if sender:
        conditions.append(f'sender contains "{escape_applescript(sender)}"')
    if body:
        conditions.append(f'content contains "{escape_applescript(body)}"')
    if is_read is True:
        conditions.append("read status is true")
    elif is_read is False:
        conditions.append("read status is false")

    if date_from:
        y, m, d = date_from.split("-")
        date_setup += f"""
            set dateFrom to current date
            set year of dateFrom to {int(y)}
            set month of dateFrom to {int(m)}
            set day of dateFrom to {int(d)}
            set time of dateFrom to 0
        """
        conditions.append("date received >= dateFrom")

    if date_to:
        y, m, d = date_to.split("-")
        date_setup += f"""
            set dateTo to current date
            set year of dateTo to {int(y)}
            set month of dateTo to {int(m)}
            set day of dateTo to {int(d)}
            set time of dateTo to 86399
        """
        conditions.append("date received <= dateTo")

    return date_setup, conditions


def _build_post_filters(
    has_attachments: Optional[bool],
    is_flagged: Optional[bool],
    is_newsletter: bool,
) -> tuple[bool, str]:
    """Build loop-level post-filter checks (things `whose` can't handle).

    Returns (needs_lowercase_handler, applescript_filter_block).
    The block sets `skipMsg` to true when the message should be excluded.

    Note: body search is handled by the `whose` clause (native Mail.app
    filtering) for much better performance — not done here.
    """
    lines: list[str] = []
    needs_lowercase = False

    if has_attachments is True:
        lines.append("if (count of mail attachments of aMessage) = 0 then set skipMsg to true")
    elif has_attachments is False:
        lines.append("if (count of mail attachments of aMessage) > 0 then set skipMsg to true")

    if is_flagged is True:
        lines.append("if not (flagged status of aMessage) then set skipMsg to true")
    elif is_flagged is False:
        lines.append("if (flagged status of aMessage) then set skipMsg to true")

    if is_newsletter:
        needs_lowercase = True
        # Build the newsletter sender check
        platform_checks = " or ".join(
            f'lowerSender contains "{p}"' for p in NEWSLETTER_PLATFORM_PATTERNS
        )
        keyword_checks = " or ".join(
            f'lowerSender contains "{p}"' for p in NEWSLETTER_KEYWORD_PATTERNS
        )
        lines.append(f"""
                                set lowerSender to my lowercase(messageSender)
                                set isNL to false
                                if {platform_checks} then set isNL to true
                                if {keyword_checks} then set isNL to true
                                if not isNL then set skipMsg to true
        """)

    block = "\n                                ".join(lines)
    return needs_lowercase, block


def _build_content_script(max_content_length: int) -> str:
    """AppleScript snippet to extract content preview into outputText."""
    return f"""
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
                                on error
                                    set contentPreview to "[Not available]"
                                end try
    """


def _parse_pipe_output(raw: str) -> list[dict[str, Any]]:
    """Parse pipe-delimited AppleScript output into list of dicts."""
    emails: list[dict[str, Any]] = []
    if not raw:
        return emails
    for line in raw.split("\n"):
        if "|||" not in line:
            continue
        parts = line.split("|||")
        if len(parts) >= 6:
            emails.append({
                "subject": parts[0].strip(),
                "sender": parts[1].strip(),
                "date": parts[2].strip(),
                "is_read": parts[3].strip().lower() == "true",
                "account": parts[4].strip(),
                "mailbox": parts[5].strip(),
                "content": parts[6].strip() if len(parts) > 6 else "",
            })
    return emails


# ---------------------------------------------------------------------------
# The single consolidated search tool
# ---------------------------------------------------------------------------

@mcp.tool()
@inject_preferences
def search_emails(
    account: Optional[str] = None,
    mailbox: str = "INBOX",
    subject: Optional[str] = None,
    sender: Optional[str] = None,
    body: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    is_read: Optional[bool] = None,
    has_attachments: Optional[bool] = None,
    is_flagged: Optional[bool] = None,
    is_newsletter: bool = False,
    is_thread: bool = False,
    include_content: bool = False,
    max_content_length: int = 500,
    max_results: int = 25,
    output_format: str = "text",
) -> str:
    """
    Search emails with flexible filters across accounts and mailboxes.

    Replaces all previous search tools with one unified interface.
    Uses fast native Mail.app filtering for subject, sender, date, and read status.
    Falls back to slower loop filtering only for body, attachments, flagged, and newsletter detection.

    Args:
        account: Account name (e.g. "Gmail", "Work"). None = search all accounts.
        mailbox: Mailbox to search (default "INBOX", "All" = all mailboxes, or specific folder name like "Archive")
        subject: Filter by subject keyword (case-insensitive, fast native filter)
        sender: Filter by sender name or email (case-insensitive, fast native filter)
        body: Filter by body text content (case-insensitive, slower — requires reading each email body)
        date_from: Start date inclusive, format "YYYY-MM-DD" (fast native filter)
        date_to: End date inclusive, format "YYYY-MM-DD" (fast native filter)
        is_read: Filter by read status: True = read only, False = unread only, None = any
        has_attachments: True = with attachments only, False = without, None = any
        is_flagged: True = flagged only, False = unflagged, None = any
        is_newsletter: When True, only return emails from known newsletter senders (Substack, Beehiiv, Mailchimp, etc.)
        is_thread: When True, treat 'subject' as a thread topic — strips Re:/Fwd: prefixes and returns full content for conversation view
        include_content: Include email body preview in results (default False, auto-enabled when is_thread=True)
        max_content_length: Maximum body preview length in characters (default 500)
        max_results: Maximum results to return (default 25)
        output_format: "text" for human-readable output, "json" for structured data

    Returns:
        Matching emails formatted as text or JSON
    """

    # Thread mode: clean subject and force content on
    if is_thread and subject:
        for prefix in THREAD_PREFIXES:
            subject = subject.replace(prefix, "").strip()
        include_content = True

    # Newsletter mode: default to INBOX only, last 7 days if no date set
    if is_newsletter and not date_from and not date_to:
        # Default to last 7 days for newsletter detection performance
        import datetime
        week_ago = datetime.date.today() - datetime.timedelta(days=7)
        date_from = week_ago.isoformat()

    # Build the fast `whose` clause (includes body search for native filtering)
    date_setup, whose_conditions = _build_whose_clause(
        subject=subject,
        sender=sender,
        body=body,
        is_read=is_read,
        date_from=date_from,
        date_to=date_to,
    )

    if whose_conditions:
        whose_clause = "whose " + " and ".join(whose_conditions)
    else:
        whose_clause = ""

    fetch_script = f"set matchedMessages to (every message of aMailbox {whose_clause})"

    # Build post-filters (slower, loop-level — only for things whose can't handle)
    needs_lowercase, post_filter_block = _build_post_filters(
        has_attachments=has_attachments,
        is_flagged=is_flagged,
        is_newsletter=is_newsletter,
    )

    # Content preview script
    content_script = ""
    content_pipe_field = ""
    if include_content:
        content_script = _build_content_script(max_content_length)
        content_pipe_field = ' & "|||" & contentPreview'

    # --- Account loop ---
    if account:
        escaped_account = escape_applescript(account)
        acct_start = f"""
        set anAccount to account "{escaped_account}"
        set accountName to name of anAccount
        repeat 1 times
        """
        acct_end = """
        end repeat
        """
    else:
        acct_start = """
        set allAccounts to every account
        repeat with anAccount in allAccounts
            set accountName to name of anAccount
        """
        acct_end = f"""
            if resultCount >= {max_results} then exit repeat
        end repeat
        """

    # --- Mailbox loop ---
    skip_cond = skip_folders_condition("mailboxName")
    if mailbox == "All":
        mbox_start = f"""
                set accountMailboxes to every mailbox of anAccount
                repeat with aMailbox in accountMailboxes
                    try
                        set mailboxName to name of aMailbox
                        if {skip_cond} then
        """
        mbox_end = f"""
                        end if
                    end try
                    if resultCount >= {max_results} then exit repeat
                end repeat
        """
    else:
        mbox_ref = build_mailbox_ref(mailbox, account_var="anAccount", var_name="aMailbox")
        mbox_start = f"""
                {mbox_ref}
                set mailboxName to name of aMailbox
                if true then
        """
        mbox_end = """
                end if
        """

    # --- Output record (per matching message) ---
    if output_format == "json":
        record_script = f"""
                                    set end of resultLines to messageSubject & "|||" & messageSender & "|||" & (messageDate as string) & "|||" & messageRead & "|||" & accountName & "|||" & mailboxName{content_pipe_field}
        """
        output_setup = "set resultLines to {}"
        output_return = """
        set AppleScript's text item delimiters to linefeed
        return resultLines as string
        """
    else:
        content_text_line = ""
        if include_content:
            content_text_line = """
                                    set outputText to outputText & "   Content: " & contentPreview & return
            """
        record_script = f"""
                                    if messageRead then
                                        set ri to "Read"
                                    else
                                        set ri to "UNREAD"
                                    end if
                                    set outputText to outputText & "[" & ri & "] " & messageSubject & return
                                    set outputText to outputText & "   From: " & messageSender & return
                                    set outputText to outputText & "   Date: " & (messageDate as string) & return
                                    set outputText to outputText & "   Account: " & accountName & return
                                    set outputText to outputText & "   Mailbox: " & mailboxName & return
                                    {content_text_line}
                                    set outputText to outputText & return
        """
        output_setup = 'set outputText to "SEARCH RESULTS" & return & return'
        output_return = f"""
        set outputText to outputText & "========================================" & return
        set outputText to outputText & "FOUND: " & resultCount & " email(s)" & return
        set outputText to outputText & "========================================" & return
        return outputText
        """

    # --- Post-filter wrapper ---
    if post_filter_block:
        post_filter_start = f"""
                                set skipMsg to false
                                {post_filter_block}
                                if not skipMsg then
        """
        post_filter_end = """
                                end if
        """
    else:
        post_filter_start = ""
        post_filter_end = ""

    # --- Assemble the full script ---
    lowercase_handler = LOWERCASE_HANDLER if needs_lowercase else ""

    script = f"""
    {lowercase_handler}

    tell application "Mail"
        {output_setup}
        set resultCount to 0
        {date_setup}

        {acct_start}

            try
                {mbox_start}

                        {fetch_script}

                        repeat with aMessage in matchedMessages
                            if resultCount >= {max_results} then exit repeat
                            try
                                set messageSubject to subject of aMessage
                                set messageSender to sender of aMessage
                                set messageDate to date received of aMessage
                                set messageRead to read status of aMessage

                                {post_filter_start}
                                    {content_script}
                                    {record_script}
                                    set resultCount to resultCount + 1
                                {post_filter_end}
                            end try
                        end repeat

                {mbox_end}

            on error errMsg
                -- Skip account/mailbox on error
            end try

        {acct_end}

        {output_return}
    end tell
    """

    raw = run_applescript(script)

    if output_format == "json":
        emails = _parse_pipe_output(raw)
        return json.dumps(emails, indent=2)

    return raw

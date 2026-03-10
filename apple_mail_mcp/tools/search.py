"""Search tools: finding and filtering emails."""

import json
from typing import Optional, List, Dict, Any

from apple_mail_mcp.server import mcp
from apple_mail_mcp.core import inject_preferences, escape_applescript, run_applescript, LOWERCASE_HANDLER
from apple_mail_mcp.constants import SKIP_FOLDERS


@mcp.tool()
@inject_preferences
def get_email_with_content(
    account: str,
    subject_keyword: str,
    max_results: int = 5,
    max_content_length: int = 300,
    mailbox: str = "INBOX"
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

    # Escape user inputs for AppleScript
    escaped_keyword = escape_applescript(subject_keyword)
    escaped_account = escape_applescript(account)
    escaped_mailbox = escape_applescript(mailbox)

    # Build mailbox selection logic
    if mailbox == "All":
        mailbox_script = '''
            set allMailboxes to every mailbox of targetAccount
            set searchMailboxes to allMailboxes
        '''
        search_location = "all mailboxes"
    else:
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
        search_location = mailbox

    script = f'''
    {LOWERCASE_HANDLER}

    tell application "Mail"
        set outputText to "SEARCH RESULTS FOR: {escaped_keyword}" & return
        set outputText to outputText & "Searching in: {search_location}" & return & return
        set resultCount to 0

        try
            set targetAccount to account "{escaped_account}"
            {mailbox_script}

            repeat with currentMailbox in searchMailboxes
                set mailboxMessages to every message of currentMailbox
                set mailboxName to name of currentMailbox

                repeat with aMessage in mailboxMessages
                    if resultCount >= {max_results} then exit repeat

                    try
                        set messageSubject to subject of aMessage

                        -- Convert to lowercase for case-insensitive matching
                        set lowerSubject to my lowercase(messageSubject)
                        set lowerKeyword to my lowercase("{escaped_keyword}")

                        -- Check if subject contains keyword (case insensitive)
                        if lowerSubject contains lowerKeyword then
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
                            set outputText to outputText & "   Mailbox: " & mailboxName & return

                            -- Get content preview
                            try
                                set msgContent to content of aMessage
                                set AppleScript's text item delimiters to {{return, linefeed}}
                                set contentParts to text items of msgContent
                                set AppleScript's text item delimiters to " "
                                set cleanText to contentParts as string
                                set AppleScript's text item delimiters to ""

                                -- Handle content length limit (0 = unlimited)
                                if {max_content_length} > 0 and length of cleanText > {max_content_length} then
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

    result = run_applescript(script)
    return result


@mcp.tool()
@inject_preferences
def search_emails(
    account: str,
    mailbox: str = "INBOX",
    subject_keyword: Optional[str] = None,
    sender: Optional[str] = None,
    has_attachments: Optional[bool] = None,
    read_status: str = "all",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    include_content: bool = False,
    max_results: int = 20,
    output_format: str = "text",
) -> str:
    """
    Unified search tool - search emails with advanced filtering across any mailbox.

    Args:
        account: Account name to search in (e.g., "Gmail", "Work")
        mailbox: Mailbox to search (default: "INBOX", use "All" for all mailboxes, or specific folder name)
        subject_keyword: Optional keyword to search in subject
        sender: Optional sender email or name to filter by
        has_attachments: Optional filter for emails with attachments (True/False/None)
        read_status: Filter by read status: "all", "read", "unread" (default: "all")
        date_from: Optional start date filter (format: "YYYY-MM-DD")
        date_to: Optional end date filter (format: "YYYY-MM-DD")
        include_content: Whether to include email content preview (slower)
        max_results: Maximum number of results to return (default: 20)
        output_format: "text" (default, human-readable) or "json" (structured list of email dicts)

    Returns:
        Formatted list of matching emails with all requested details
    """

    # Escape user inputs for AppleScript
    escaped_account = escape_applescript(account)
    escaped_mailbox = escape_applescript(mailbox)
    escaped_subject = escape_applescript(subject_keyword) if subject_keyword else None
    escaped_sender = escape_applescript(sender) if sender else None

    # Build 'whose' clause conditions for fast app-level filtering
    whose_conditions = []

    if subject_keyword:
        whose_conditions.append(f'subject contains "{escaped_subject}"')

    if sender:
        whose_conditions.append(f'sender contains "{escaped_sender}"')

    if read_status == "read":
        whose_conditions.append('read status is true')
    elif read_status == "unread":
        whose_conditions.append('read status is false')

    # Build date objects programmatically (locale-independent)
    date_setup_script = ""
    if date_from:
        y, m, d = date_from.split('-')
        date_setup_script += f'''
            set dateFrom to current date
            set year of dateFrom to {int(y)}
            set month of dateFrom to {int(m)}
            set day of dateFrom to {int(d)}
            set time of dateFrom to 0
        '''
        whose_conditions.append('date received >= dateFrom')
    if date_to:
        y, m, d = date_to.split('-')
        date_setup_script += f'''
            set dateTo to current date
            set year of dateTo to {int(y)}
            set month of dateTo to {int(m)}
            set day of dateTo to {int(d)}
            set time of dateTo to 86399
        '''
        whose_conditions.append('date received <= dateTo')

    # Build the whose clause
    if whose_conditions:
        whose_clause = ' and '.join(whose_conditions)
        fetch_script = f'set matchedMessages to (every message of currentMailbox whose {whose_clause})'
    else:
        fetch_script = 'set matchedMessages to every message of currentMailbox'

    # has_attachments requires post-filter (can't use in whose clause)
    attachment_check_start = ""
    attachment_check_end = ""
    if has_attachments is not None:
        if has_attachments:
            attachment_check_start = "if (count of mail attachments of aMessage) > 0 then"
        else:
            attachment_check_start = "if (count of mail attachments of aMessage) = 0 then"
        attachment_check_end = "end if"

    # Handle content preview
    content_script = '''
        try
            set msgContent to content of aMessage
            set AppleScript's text item delimiters to {{return, linefeed}}
            set contentParts to text items of msgContent
            set AppleScript's text item delimiters to " "
            set cleanText to contentParts as string
            set AppleScript's text item delimiters to ""

            if length of cleanText > 300 then
                set contentPreview to text 1 thru 300 of cleanText & "..."
            else
                set contentPreview to cleanText
            end if

            set outputText to outputText & "   Content: " & contentPreview & return
        on error
            set outputText to outputText & "   Content: [Not available]" & return
        end try
    ''' if include_content else ''

    # Build skip folders list from constants
    skip_folders_list = ', '.join(f'"{f}"' for f in SKIP_FOLDERS)

    # Build mailbox selection logic
    if mailbox == "All":
        mailbox_script = '''
            set allMailboxes to every mailbox of targetAccount
            set searchMailboxes to allMailboxes
        '''
    else:
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

    script = f'''
    tell application "Mail"
        set outputText to "SEARCH RESULTS" & return & return
        set outputText to outputText & "Searching in: {escaped_mailbox}" & return
        set outputText to outputText & "Account: {escaped_account}" & return & return
        set resultCount to 0

        try
            set targetAccount to account "{escaped_account}"
            {date_setup_script}
            {mailbox_script}

            repeat with currentMailbox in searchMailboxes
                try
                    set mailboxName to name of currentMailbox

                    -- Skip system folders
                    set skipFolders to {{{skip_folders_list}}}
                    set shouldSkip to false
                    repeat with skipFolder in skipFolders
                        if mailboxName is skipFolder then
                            set shouldSkip to true
                            exit repeat
                        end if
                    end repeat

                    if not shouldSkip then
                        -- Use whose clause for fast app-level filtering
                        {fetch_script}

                        repeat with aMessage in matchedMessages
                            if resultCount >= {max_results} then exit repeat

                            try
                                {attachment_check_start}
                                    set messageSubject to subject of aMessage
                                    set messageSender to sender of aMessage
                                    set messageDate to date received of aMessage
                                    set messageRead to read status of aMessage

                                    set readIndicator to "\u2709"
                                    if messageRead then
                                        set readIndicator to "\u2713"
                                    end if

                                    set outputText to outputText & readIndicator & " " & messageSubject & return
                                    set outputText to outputText & "   From: " & messageSender & return
                                    set outputText to outputText & "   Date: " & (messageDate as string) & return
                                    set outputText to outputText & "   Mailbox: " & mailboxName & return

                                    {content_script}

                                    set outputText to outputText & return
                                    set resultCount to resultCount + 1
                                {attachment_check_end}
                            end try
                        end repeat
                    end if
                on error
                    -- Skip mailboxes that throw errors (smart mailboxes, missing values, etc.)
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

    result = run_applescript(script)

    if output_format == "json":
        # Re-run with pipe-delimited output for structured parsing
        return _search_emails_json(
            account, mailbox, subject_keyword, sender,
            has_attachments, read_status, max_results,
        )

    return result


def _search_emails_json(
    account: str,
    mailbox: str,
    subject_keyword: Optional[str],
    sender: Optional[str],
    has_attachments: Optional[bool],
    read_status: str,
    max_results: int,
) -> str:
    """Return search results as JSON."""
    escaped_account = escape_applescript(account)
    escaped_mailbox = escape_applescript(mailbox)
    escaped_subject = escape_applescript(subject_keyword) if subject_keyword else None
    escaped_sender = escape_applescript(sender) if sender else None

    conditions = []
    if subject_keyword:
        conditions.append(f'messageSubject contains "{escaped_subject}"')
    if sender:
        conditions.append(f'messageSender contains "{escaped_sender}"')
    if has_attachments is not None:
        if has_attachments:
            conditions.append('(count of mail attachments of aMessage) > 0')
        else:
            conditions.append('(count of mail attachments of aMessage) = 0')
    if read_status == "read":
        conditions.append('messageRead is true')
    elif read_status == "unread":
        conditions.append('messageRead is false')
    condition_str = ' and '.join(conditions) if conditions else 'true'

    if mailbox == "All":
        mailbox_script = '''
            set allMailboxes to every mailbox of targetAccount
            set searchMailboxes to allMailboxes
        '''
    else:
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

    script = f'''
    tell application "Mail"
        set resultLines to {{}}
        set resultCount to 0
        try
            set targetAccount to account "{escaped_account}"
            {mailbox_script}
            repeat with currentMailbox in searchMailboxes
                try
                    set mailboxName to name of currentMailbox
                    set skipFolders to {{"Trash", "Junk", "Junk Email", "Deleted Items", "Sent", "Sent Items", "Sent Messages", "Drafts", "Spam", "Deleted Messages"}}
                    set shouldSkip to false
                    repeat with skipFolder in skipFolders
                        if mailboxName is skipFolder then
                            set shouldSkip to true
                            exit repeat
                        end if
                    end repeat
                    if not shouldSkip then
                        set mailboxMessages to every message of currentMailbox
                        repeat with aMessage in mailboxMessages
                            if resultCount >= {max_results} then exit repeat
                            try
                                set messageSubject to subject of aMessage
                                set messageSender to sender of aMessage
                                set messageDate to date received of aMessage
                                set messageRead to read status of aMessage
                                if {condition_str} then
                                    set end of resultLines to messageSubject & "|||" & messageSender & "|||" & (messageDate as string) & "|||" & messageRead & "|||" & "{escaped_account}" & "|||" & mailboxName
                                    set resultCount to resultCount + 1
                                end if
                            end try
                        end repeat
                    end if
                end try
            end repeat
        on error errMsg
            return "Error: " & errMsg
        end try
        set AppleScript's text item delimiters to linefeed
        return resultLines as string
    end tell
    '''
    raw = run_applescript(script)
    emails = []
    if raw:
        for line in raw.split('\n'):
            if '|||' not in line:
                continue
            parts = line.split('|||')
            if len(parts) >= 5:
                emails.append({
                    'subject': parts[0].strip(),
                    'sender': parts[1].strip(),
                    'date': parts[2].strip(),
                    'is_read': parts[3].strip().lower() == 'true',
                    'account': parts[4].strip(),
                    'mailbox': parts[5].strip() if len(parts) > 5 else '',
                })
    return json.dumps(emails, indent=2)


@mcp.tool()
@inject_preferences
def search_by_sender(
    sender: str,
    account: Optional[str] = None,
    days_back: int = 30,
    max_results: int = 20,
    include_content: bool = True,
    max_content_length: int = 500,
    mailbox: str = "INBOX"
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

    # Escape user inputs for AppleScript
    escaped_sender = escape_applescript(sender)
    escaped_mailbox = escape_applescript(mailbox)
    search_all_mailboxes = mailbox == "All"

    # Build 'whose' clause for fast app-level filtering
    whose_parts = [f'sender contains "{escaped_sender}"']
    if days_back > 0:
        date_setup = f'set targetDate to (current date) - ({days_back} * days)'
        whose_parts.append('date received > targetDate')
    else:
        date_setup = ""

    whose_clause = ' and '.join(whose_parts)

    # Build content preview script
    content_script = ""
    if include_content:
        content_script = f'''
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
        '''

    # Build mailbox selection: INBOX-only (fast) vs all mailboxes
    if search_all_mailboxes:
        mailbox_loop_start = '''
                set accountMailboxes to every mailbox of anAccount
                repeat with aMailbox in accountMailboxes
                    try
                        set mailboxName to name of aMailbox
                        -- Skip system and aggregate folders to avoid scanning huge mailboxes
                        if mailboxName is not in {"Trash", "Junk", "Junk Email", "Deleted Items", "Deleted Messages", "Spam", "Drafts", "Sent", "Sent Items", "Sent Messages", "Sent Mail", "All Mail", "Bin"} then
        '''
        mailbox_loop_end = f'''
                            if resultCount >= {max_results} then exit repeat
                        end if
                    on error
                        -- Skip individual mailboxes that throw errors (smart mailboxes, missing values, etc.)
                    end try
                end repeat
        '''
    else:
        mailbox_loop_start = f'''
                -- Fast path: only search the target mailbox
                try
                    set aMailbox to mailbox "{escaped_mailbox}" of anAccount
                on error
                    if "{escaped_mailbox}" is "INBOX" then
                        set aMailbox to mailbox "Inbox" of anAccount
                    else
                        error "Mailbox not found: {escaped_mailbox}"
                    end if
                end try
                set mailboxName to name of aMailbox
                if true then
        '''
        mailbox_loop_end = '''
                end if
        '''

    # Build account iteration: direct access (fast) vs all accounts
    if account:
        escaped_account = escape_applescript(account)
        account_loop_start = f'''
        set anAccount to account "{escaped_account}"
        set accountName to name of anAccount
        repeat 1 times
        '''
        account_loop_end = '''
        end repeat
        '''
    else:
        account_loop_start = f'''
        set allAccounts to every account
        repeat with anAccount in allAccounts
            set accountName to name of anAccount
        '''
        account_loop_end = f'''
            if resultCount >= {max_results} then exit repeat
        end repeat
        '''

    script = f'''
    tell application "Mail"
        set outputText to "EMAILS FROM SENDER: {escaped_sender}" & return
        set outputText to outputText & "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501" & return & return
        set resultCount to 0

        {date_setup}

        {account_loop_start}

            try
                {mailbox_loop_start}

                        -- Use whose clause for fast app-level filtering
                        set matchedMessages to (every message of aMailbox whose {whose_clause})

                        repeat with aMessage in matchedMessages
                            if resultCount >= {max_results} then exit repeat

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
                                    set outputText to outputText & "   Account: " & accountName & return
                                    set outputText to outputText & "   Mailbox: " & mailboxName & return

                                    {content_script}

                                    set outputText to outputText & return
                                    set resultCount to resultCount + 1
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
    max_content_length: int = 600
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
    search_condition = ' or '.join(search_conditions) if search_conditions else 'false'

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
                    set targetMailbox to mailbox "Inbox" of targetAccount
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
    max_content_length: int = 500
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
        content_script = f'''
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
        '''

    account_filter_start = ""
    account_filter_end = ""
    if account:
        account_filter_start = f'if accountName is "{escaped_account}" then'
        account_filter_end = "end if"

    date_setup = ""
    whose_date_clause = ""
    if days_back > 0:
        date_setup = f'set cutoffDate to (current date) - ({days_back} * days)'
        whose_date_clause = "whose date received > cutoffDate"

    script = f'''
    tell application "Mail"
        set outputText to "\U0001f4f0 NEWSLETTER DETECTION" & return
        set outputText to outputText & "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501" & return & return
        set resultCount to 0
        {date_setup}
        set allAccounts to every account
        repeat with anAccount in allAccounts
            set accountName to name of anAccount
            {account_filter_start}
            try
                set accountMailboxes to every mailbox of anAccount
            on error
                set accountMailboxes to {{}}
            end try

                repeat with aMailbox in accountMailboxes
                    try
                        set mailboxName to name of aMailbox
                        if mailboxName is "INBOX" or mailboxName is "Inbox" then
                            -- Use whose clause for date pre-filtering when available
                            if "{whose_date_clause}" is not "" then
                                set mailboxMessages to (every message of aMailbox {whose_date_clause})
                            else
                                set mailboxMessages to every message of aMailbox
                            end if
                            repeat with aMessage in mailboxMessages
                                if resultCount >= {max_results} then exit repeat
                                try
                                    set messageSender to sender of aMessage
                                    set isNewsletter to false
                                    -- AppleScript contains is case-insensitive
                                    if messageSender contains "substack.com" or messageSender contains "beehiiv.com" or messageSender contains "mailchimp" or messageSender contains "sendgrid" or messageSender contains "convertkit" or messageSender contains "buttondown" or messageSender contains "ghost.io" or messageSender contains "revue.co" or messageSender contains "mailgun" then
                                        set isNewsletter to true
                                    end if
                                    if messageSender contains "newsletter" or messageSender contains "digest" or messageSender contains "weekly" or messageSender contains "daily" or messageSender contains "bulletin" or messageSender contains "briefing" or messageSender contains "news@" or messageSender contains "updates@" then
                                        set isNewsletter to true
                                    end if
                                    if isNewsletter then
                                        set messageSubject to subject of aMessage
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
                                        set outputText to outputText & "   Account: " & accountName & return
                                        {content_script}
                                        set outputText to outputText & return
                                        set resultCount to resultCount + 1
                                    end if
                                end try
                            end repeat
                        end if
                    on error
                        -- Skip mailboxes that throw errors (smart mailboxes, etc.)
                    end try
                    if resultCount >= {max_results} then exit repeat
                end repeat

            {account_filter_end}
            if resultCount >= {max_results} then exit repeat
        end repeat
        set outputText to outputText & "========================================" & return
        set outputText to outputText & "FOUND: " & resultCount & " newsletter(s)" & return
        set outputText to outputText & "========================================" & return
        return outputText
    end tell
    '''
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
    mailbox: str = "INBOX"
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

    # Escape user inputs for AppleScript
    escaped_sender = escape_applescript(sender)
    escaped_mailbox = escape_applescript(mailbox)
    search_all_mailboxes = mailbox == "All"

    # Build 'whose' clause for fast app-level filtering
    whose_parts = [f'sender contains "{escaped_sender}"']
    if days_back > 0:
        if is_yesterday:
            date_setup = '''
            set todayStart to (current date) - (time of (current date))
            set yesterdayStart to todayStart - (1 * days)
            '''
            whose_parts.append('date received >= yesterdayStart')
            whose_parts.append('date received < todayStart')
        else:
            date_setup = f'set cutoffDate to (current date) - ({days_back} * days)'
            whose_parts.append('date received > cutoffDate')
    else:
        date_setup = ""

    whose_clause = ' and '.join(whose_parts)

    content_script = ""
    if include_content:
        content_script = f'''
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
        '''

    # Build mailbox selection: INBOX-only (fast) vs all mailboxes
    if search_all_mailboxes:
        mailbox_loop_start = '''
                set accountMailboxes to every mailbox of anAccount
                repeat with aMailbox in accountMailboxes
                    try
                        set mailboxName to name of aMailbox
                        if mailboxName is not in {"Trash", "Junk", "Junk Email", "Deleted Items", "Deleted Messages", "Spam", "Drafts", "Sent", "Sent Items", "Sent Messages", "Sent Mail", "All Mail", "Bin"} then
        '''
        mailbox_loop_end = f'''
                            if resultCount >= {max_results} then exit repeat
                        end if
                    on error
                        -- Skip individual mailboxes that throw errors (smart mailboxes, missing values, etc.)
                    end try
                end repeat
        '''
    else:
        mailbox_loop_start = f'''
                -- Fast path: only search the target mailbox
                try
                    set aMailbox to mailbox "{escaped_mailbox}" of anAccount
                on error
                    if "{escaped_mailbox}" is "INBOX" then
                        set aMailbox to mailbox "Inbox" of anAccount
                    else
                        error "Mailbox not found: {escaped_mailbox}"
                    end if
                end try
                set mailboxName to name of aMailbox
                if true then
        '''
        mailbox_loop_end = '''
                end if
        '''

    # Build account iteration: direct access (fast) vs all accounts
    if account:
        escaped_account = escape_applescript(account)
        account_loop_start = f'''
        set anAccount to account "{escaped_account}"
        set accountName to name of anAccount
        repeat 1 times
        '''
        account_loop_end = '''
        end repeat
        '''
    else:
        account_loop_start = f'''
        set allAccounts to every account
        repeat with anAccount in allAccounts
            set accountName to name of anAccount
        '''
        account_loop_end = f'''
            if resultCount >= {max_results} then exit repeat
        end repeat
        '''

    script = f'''
    tell application "Mail"
        set outputText to "\U0001f4e7 EMAILS FROM: {escaped_sender}" & return
        set outputText to outputText & "\u23f0 Time range: {time_range}" & return
        set outputText to outputText & "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501" & return & return
        set resultCount to 0
        {date_setup}

        {account_loop_start}

            try
                {mailbox_loop_start}

                            -- Use whose clause for fast app-level filtering
                            set matchedMessages to (every message of aMailbox whose {whose_clause})

                            repeat with aMessage in matchedMessages
                                if resultCount >= {max_results} then exit repeat
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
                                    set outputText to outputText & "   Account: " & accountName & return
                                    {content_script}
                                    set outputText to outputText & return
                                    set resultCount to resultCount + 1
                                end try
                            end repeat

                            if resultCount >= {max_results} then exit repeat

                {mailbox_loop_end}

            on error errMsg
                set outputText to outputText & "\u26a0 Error listing mailboxes for " & accountName & ": " & errMsg & return
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
    account: str,
    subject_keyword: str,
    mailbox: str = "INBOX",
    max_messages: int = 50
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
    thread_keywords = ['Re:', 'Fwd:', 'FW:', 'RE:', 'Fw:']
    cleaned_keyword = subject_keyword
    for prefix in thread_keywords:
        cleaned_keyword = cleaned_keyword.replace(prefix, '').strip()
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
    max_content_length: int = 400
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
        date_filter = f'''
            set cutoffDate to (current date) - ({days_back} * days)
            if messageDate < cutoffDate then
                set skipMessage to true
            end if
        '''

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
        content_retrieval = f'''
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
        '''

    script = f'''
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
    '''

    result = run_applescript(script)
    return result


@mcp.tool()
@inject_preferences
def search_emails_advanced(
    account: Optional[str] = None,
    mailbox: str = "INBOX",
    subject_contains: Optional[str] = None,
    body_contains: Optional[str] = None,
    sender_contains: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    is_read: Optional[bool] = None,
    has_attachments: Optional[bool] = None,
    is_flagged: Optional[bool] = None,
    max_results: int = 50,
    output_format: str = "text",
) -> str:
    """
    Powerful unified search across accounts and mailboxes with flexible filters.

    Combines the capabilities of search_emails, search_by_sender,
    search_email_content, and search_all_accounts into one tool.
    When *account* is None, all accounts are searched.

    Args:
        account: Account to search (None = all accounts)
        mailbox: Mailbox name (default "INBOX", "All" for all mailboxes)
        subject_contains: Filter by subject keyword (case-insensitive)
        body_contains: Filter by body text (slower, case-insensitive)
        sender_contains: Filter by sender name/email (case-insensitive)
        date_from: Start date "YYYY-MM-DD" (inclusive)
        date_to: End date "YYYY-MM-DD" (inclusive)
        is_read: Filter by read status (True/False/None for any)
        has_attachments: Filter by attachment presence (True/False/None)
        is_flagged: Filter by flagged status (True/False/None)
        max_results: Maximum results (default 50)
        output_format: "text" (human-readable) or "json" (structured)

    Returns:
        Matching emails across the specified scope
    """
    from apple_mail_mcp.core import build_mailbox_ref, skip_folders_condition

    # Escape inputs
    escaped_account = escape_applescript(account) if account else None
    escaped_mailbox = escape_applescript(mailbox)

    # --- Build filter conditions applied inside the message loop ---
    filter_lines: list[str] = []
    if subject_contains:
        esc = escape_applescript(subject_contains)
        filter_lines.append(
            f'if lowerSubject does not contain my lowercase("{esc}") then set skipMsg to true'
        )
    if sender_contains:
        esc = escape_applescript(sender_contains)
        filter_lines.append(
            f'if lowerSender does not contain my lowercase("{esc}") then set skipMsg to true'
        )
    if body_contains:
        esc = escape_applescript(body_contains)
        filter_lines.append(
            f'if lowerBody does not contain my lowercase("{esc}") then set skipMsg to true'
        )
    if is_read is True:
        filter_lines.append('if not messageRead then set skipMsg to true')
    elif is_read is False:
        filter_lines.append('if messageRead then set skipMsg to true')
    if has_attachments is True:
        filter_lines.append('if (count of mail attachments of aMessage) = 0 then set skipMsg to true')
    elif has_attachments is False:
        filter_lines.append('if (count of mail attachments of aMessage) > 0 then set skipMsg to true')
    if is_flagged is True:
        filter_lines.append('if not (flagged status of aMessage) then set skipMsg to true')
    elif is_flagged is False:
        filter_lines.append('if (flagged status of aMessage) then set skipMsg to true')

    filter_block = '\n                                    '.join(filter_lines)

    # Date filters
    date_setup = ""
    date_checks = ""
    if date_from:
        esc_from = escape_applescript(date_from)
        date_setup += f'''
        set fromDateStr to "{esc_from}"
        set fromDate to date fromDateStr
'''
        date_checks += '''
                                    if messageDate < fromDate then set skipMsg to true
'''
    if date_to:
        esc_to = escape_applescript(date_to)
        date_setup += f'''
        set toDateStr to "{esc_to}"
        set toDate to (date toDateStr) + (1 * days)
'''
        date_checks += '''
                                    if messageDate > toDate then set skipMsg to true
'''

    # Body retrieval (only if needed)
    if body_contains:
        body_script = '''
                                    set msgBody to ""
                                    try
                                        set msgBody to content of aMessage
                                    end try
                                    set lowerBody to my lowercase(msgBody)
'''
    else:
        body_script = '                                    set lowerBody to ""'

    # Account loop
    if account:
        acct_start = f'''
        set anAccount to account "{escaped_account}"
        set accountName to name of anAccount
        repeat 1 times
'''
        acct_end = '''
        end repeat
'''
    else:
        acct_start = f'''
        set allAccounts to every account
        repeat with anAccount in allAccounts
            set accountName to name of anAccount
'''
        acct_end = f'''
            if resultCount >= {max_results} then exit repeat
        end repeat
'''

    # Mailbox loop
    skip_cond = skip_folders_condition("mailboxName")
    if mailbox == "All":
        mbox_start = f'''
                set accountMailboxes to every mailbox of anAccount
                repeat with aMailbox in accountMailboxes
                    try
                        set mailboxName to name of aMailbox
                        if {skip_cond} then
'''
        mbox_end = f'''
                        end if
                    end try
                    if resultCount >= {max_results} then exit repeat
                end repeat
'''
    else:
        mbox_start = f'''
                {build_mailbox_ref(mailbox, account_var="anAccount", var_name="aMailbox")}
                set mailboxName to name of aMailbox
                if true then
'''
        mbox_end = '''
                end if
'''

    # Output format
    if output_format == "json":
        record_script = '''
                                    set end of resultLines to messageSubject & "|||" & messageSender & "|||" & (messageDate as string) & "|||" & messageRead & "|||" & accountName & "|||" & mailboxName
'''
        output_setup = 'set resultLines to {}'
        output_return = '''
        set AppleScript's text item delimiters to linefeed
        return resultLines as string
'''
    else:
        record_script = '''
                                    if messageRead then
                                        set ri to "\\u2713"
                                    else
                                        set ri to "\\u2709"
                                    end if
                                    set outputText to outputText & ri & " " & messageSubject & return
                                    set outputText to outputText & "   From: " & messageSender & return
                                    set outputText to outputText & "   Date: " & (messageDate as string) & return
                                    set outputText to outputText & "   Account: " & accountName & return
                                    set outputText to outputText & "   Mailbox: " & mailboxName & return
                                    set outputText to outputText & return
'''
        output_setup = 'set outputText to "ADVANCED SEARCH RESULTS" & return & return'
        output_return = '''
        set outputText to outputText & "========================================" & return
        set outputText to outputText & "FOUND: " & resultCount & " email(s)" & return
        set outputText to outputText & "========================================" & return
        return outputText
'''

    script = f'''
    {LOWERCASE_HANDLER}

    tell application "Mail"
        {output_setup}
        set resultCount to 0
        {date_setup}

        {acct_start}

            try
                {mbox_start}

                        set mailboxMessages to every message of aMailbox
                        repeat with aMessage in mailboxMessages
                            if resultCount >= {max_results} then exit repeat
                            try
                                set messageSubject to subject of aMessage
                                set messageSender to sender of aMessage
                                set messageDate to date received of aMessage
                                set messageRead to read status of aMessage

                                set lowerSubject to my lowercase(messageSubject)
                                set lowerSender to my lowercase(messageSender)
                                {body_script}

                                set skipMsg to false
                                    {filter_block}
                                    {date_checks}
                                if not skipMsg then
                                    {record_script}
                                    set resultCount to resultCount + 1
                                end if
                            end try
                        end repeat

                {mbox_end}

            on error errMsg
                -- Skip account on error
            end try

        {acct_end}

        {output_return}
    end tell
    '''

    raw = run_applescript(script)

    if output_format == "json":
        emails: list[dict[str, Any]] = []
        if raw:
            for line in raw.split('\n'):
                if '|||' not in line:
                    continue
                parts = line.split('|||')
                if len(parts) >= 5:
                    emails.append({
                        'subject': parts[0].strip(),
                        'sender': parts[1].strip(),
                        'date': parts[2].strip(),
                        'is_read': parts[3].strip().lower() == 'true',
                        'account': parts[4].strip(),
                        'mailbox': parts[5].strip() if len(parts) > 5 else '',
                    })
        return json.dumps(emails, indent=2)

    return raw

#!/usr/bin/env python3
"""
Apple Mail MCP Server - FastMCP implementation
Provides tools to query and interact with Apple Mail inboxes
"""

import subprocess
import json
import os
import tempfile
from datetime import datetime
from typing import Optional, List, Dict, Any
from mcp.server.fastmcp import FastMCP

# Import UI module for dashboard
try:
    from ui import create_inbox_dashboard_ui
    UI_AVAILABLE = True
except ImportError:
    UI_AVAILABLE = False

# Load user preferences from environment
USER_PREFERENCES = os.environ.get("USER_EMAIL_PREFERENCES", "")

# Initialize FastMCP server
mcp = FastMCP("Apple Mail MCP")

# Decorator to inject user preferences into tool docstrings
def inject_preferences(func):
    """Decorator that appends user preferences to tool docstrings"""
    if USER_PREFERENCES:
        if func.__doc__:
            func.__doc__ = func.__doc__.rstrip() + f"\n\nUser Preferences: {USER_PREFERENCES}"
        else:
            func.__doc__ = f"User Preferences: {USER_PREFERENCES}"
    return func


def escape_applescript(value: str) -> str:
    """Escape a string for safe injection into AppleScript double-quoted strings.

    Handles backslashes first, then double quotes, to prevent injection.
    """
    return value.replace('\\', '\\\\').replace('"', '\\"')


def run_applescript(script: str) -> str:
    """Execute AppleScript via stdin pipe for reliable multi-line handling"""
    try:
        result = subprocess.run(
            ['osascript', '-'],
            input=script,
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode != 0 and result.stderr.strip():
            raise Exception(f"AppleScript error: {result.stderr.strip()}")
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        raise Exception("AppleScript execution timed out")
    except Exception as e:
        raise Exception(f"AppleScript execution failed: {str(e)}")


def parse_email_list(output: str) -> List[Dict[str, Any]]:
    """Parse the structured email output from AppleScript"""
    emails = []
    lines = output.split('\n')

    current_email = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith('=') or line.startswith('━') or line.startswith('📧') or line.startswith('⚠'):
            continue

        if line.startswith('✉') or line.startswith('✓'):
            # New email entry
            if current_email:
                emails.append(current_email)

            is_read = line.startswith('✓')
            subject = line[2:].strip()  # Remove indicator
            current_email = {
                'subject': subject,
                'is_read': is_read
            }
        elif line.startswith('From:'):
            current_email['sender'] = line[5:].strip()
        elif line.startswith('Date:'):
            current_email['date'] = line[5:].strip()
        elif line.startswith('Preview:'):
            current_email['preview'] = line[8:].strip()
        elif line.startswith('TOTAL EMAILS'):
            # End of email list
            if current_email:
                emails.append(current_email)
            break

    if current_email and current_email not in emails:
        emails.append(current_email)

    return emails


@mcp.tool()
@inject_preferences
def list_inbox_emails(
    account: Optional[str] = None,
    max_emails: int = 0,
    include_read: bool = True
) -> str:
    """
    List all emails from inbox across all accounts or a specific account.

    Args:
        account: Optional account name to filter (e.g., "Gmail", "Work"). If None, shows all accounts.
        max_emails: Maximum number of emails to return per account (0 = all)
        include_read: Whether to include read emails (default: True)

    Returns:
        Formatted list of emails with subject, sender, date, and read status
    """

    script = f'''
    tell application "Mail"
        set outputText to "INBOX EMAILS - ALL ACCOUNTS" & return & return
        set totalCount to 0
        set allAccounts to every account

        repeat with anAccount in allAccounts
            set accountName to name of anAccount

            try
                -- Try to get inbox (handle both "INBOX" and "Inbox")
                try
                    set inboxMailbox to mailbox "INBOX" of anAccount
                on error
                    set inboxMailbox to mailbox "Inbox" of anAccount
                end try
                set inboxMessages to every message of inboxMailbox
                set messageCount to count of inboxMessages

                if messageCount > 0 then
                    set outputText to outputText & "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" & return
                    set outputText to outputText & "📧 ACCOUNT: " & accountName & " (" & messageCount & " messages)" & return
                    set outputText to outputText & "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" & return & return

                    set currentIndex to 0
                    repeat with aMessage in inboxMessages
                        set currentIndex to currentIndex + 1
                        if {max_emails} > 0 and currentIndex > {max_emails} then exit repeat

                        try
                            set messageSubject to subject of aMessage
                            set messageSender to sender of aMessage
                            set messageDate to date received of aMessage
                            set messageRead to read status of aMessage

                            set shouldInclude to true
                            if not {str(include_read).lower()} and messageRead then
                                set shouldInclude to false
                            end if

                            if shouldInclude then
                                if messageRead then
                                    set readIndicator to "✓"
                                else
                                    set readIndicator to "✉"
                                end if

                                set outputText to outputText & readIndicator & " " & messageSubject & return
                                set outputText to outputText & "   From: " & messageSender & return
                                set outputText to outputText & "   Date: " & (messageDate as string) & return
                                set outputText to outputText & return

                                set totalCount to totalCount + 1
                            end if
                        end try
                    end repeat
                end if
            on error errMsg
                set outputText to outputText & "⚠ Error accessing inbox for account " & accountName & return
                set outputText to outputText & "   " & errMsg & return & return
            end try
        end repeat

        set outputText to outputText & "========================================" & return
        set outputText to outputText & "TOTAL EMAILS: " & totalCount & return
        set outputText to outputText & "========================================" & return

        return outputText
    end tell
    '''

    result = run_applescript(script)
    return result


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
    escaped_keyword = subject_keyword.replace('\\', '\\\\').replace('"', '\\"')
    escaped_account = account.replace('\\', '\\\\').replace('"', '\\"')
    escaped_mailbox = mailbox.replace('\\', '\\\\').replace('"', '\\"')

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
    on lowercase(str)
        set lowerStr to do shell script "echo " & quoted form of str & " | tr '[:upper:]' '[:lower:]'"
        return lowerStr
    end lowercase

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
                                set readIndicator to "✓"
                            else
                                set readIndicator to "✉"
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
def get_unread_count() -> Dict[str, int]:
    """
    Get the count of unread emails for each account.

    Returns:
        Dictionary mapping account names to unread email counts
    """

    script = '''
    tell application "Mail"
        set resultList to {}
        set allAccounts to every account

        repeat with anAccount in allAccounts
            set accountName to name of anAccount

            try
                -- Try to get inbox (handle both "INBOX" and "Inbox")
                try
                    set inboxMailbox to mailbox "INBOX" of anAccount
                on error
                    set inboxMailbox to mailbox "Inbox" of anAccount
                end try
                set unreadCount to unread count of inboxMailbox
                set end of resultList to accountName & ":" & unreadCount
            on error
                set end of resultList to accountName & ":ERROR"
            end try
        end repeat

        set AppleScript's text item delimiters to "|"
        return resultList as string
    end tell
    '''

    result = run_applescript(script)

    # Parse the result
    counts = {}
    for item in result.split('|'):
        if ':' in item:
            account, count = item.split(':', 1)
            if count != "ERROR":
                counts[account] = int(count)
            else:
                counts[account] = -1  # Error indicator

    return counts


@mcp.tool()
@inject_preferences
def list_accounts() -> List[str]:
    """
    List all available Mail accounts.

    Returns:
        List of account names
    """

    script = '''
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
    '''

    result = run_applescript(script)
    return result.split('|') if result else []


@mcp.tool()
@inject_preferences
def get_recent_emails(
    account: str,
    count: int = 10,
    include_content: bool = False
) -> str:
    """
    Get the most recent emails from a specific account.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        count: Number of recent emails to retrieve (default: 10)
        include_content: Whether to include content preview (slower, default: False)

    Returns:
        Formatted list of recent emails
    """

    # Escape user inputs for AppleScript
    escaped_account = account.replace('\\', '\\\\').replace('"', '\\"')

    content_script = '''
        try
            set msgContent to content of aMessage
            set AppleScript's text item delimiters to {{return, linefeed}}
            set contentParts to text items of msgContent
            set AppleScript's text item delimiters to " "
            set cleanText to contentParts as string
            set AppleScript's text item delimiters to ""

            if length of cleanText > 200 then
                set contentPreview to text 1 thru 200 of cleanText & "..."
            else
                set contentPreview to cleanText
            end if

            set outputText to outputText & "   Preview: " & contentPreview & return
        on error
            set outputText to outputText & "   Preview: [Not available]" & return
        end try
    ''' if include_content else ''

    script = f'''
    tell application "Mail"
        set outputText to "RECENT EMAILS - {escaped_account}" & return & return

        try
            set targetAccount to account "{escaped_account}"
            -- Try to get inbox (handle both "INBOX" and "Inbox")
            try
                set inboxMailbox to mailbox "INBOX" of targetAccount
            on error
                set inboxMailbox to mailbox "Inbox" of targetAccount
            end try
            set inboxMessages to every message of inboxMailbox

            set currentIndex to 0
            repeat with aMessage in inboxMessages
                set currentIndex to currentIndex + 1
                if currentIndex > {count} then exit repeat

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

                    {content_script}

                    set outputText to outputText & return
                end try
            end repeat

            set outputText to outputText & "========================================" & return
            set outputText to outputText & "Showing " & (currentIndex - 1) & " email(s)" & return
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
def list_mailboxes(
    account: Optional[str] = None,
    include_counts: bool = True
) -> str:
    """
    List all mailboxes (folders) for a specific account or all accounts.

    Args:
        account: Optional account name to filter (e.g., "Gmail", "Work"). If None, shows all accounts.
        include_counts: Whether to include message counts for each mailbox (default: True)

    Returns:
        Formatted list of mailboxes with optional message counts.
        For nested mailboxes, shows both indented format and path format (e.g., "Projects/Amplify Impact")
    """

    count_script = '''
        try
            set msgCount to count of messages of aMailbox
            set unreadCount to unread count of aMailbox
            set outputText to outputText & " (" & msgCount & " total, " & unreadCount & " unread)"
        on error
            set outputText to outputText & " (count unavailable)"
        end try
    ''' if include_counts else ''

    # Escape user inputs for AppleScript
    escaped_account = account.replace('\\', '\\\\').replace('"', '\\"') if account else None

    account_filter = f'''
        if accountName is "{escaped_account}" then
    ''' if account else ''

    account_filter_end = 'end if' if account else ''

    script = f'''
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

                                {count_script.replace('aMailbox', 'subBox') if include_counts else ''}

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
    '''

    result = run_applescript(script)
    return result


@mcp.tool()
@inject_preferences
def move_email(
    account: str,
    subject_keyword: str,
    to_mailbox: str,
    from_mailbox: str = "INBOX",
    max_moves: int = 1
) -> str:
    """
    Move email(s) matching a subject keyword from one mailbox to another.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        subject_keyword: Keyword to search for in email subjects
        to_mailbox: Destination mailbox name. For nested mailboxes, use "/" separator (e.g., "Projects/Amplify Impact")
        from_mailbox: Source mailbox name (default: "INBOX")
        max_moves: Maximum number of emails to move (default: 1, safety limit)

    Returns:
        Confirmation message with details of moved emails
    """

    # Escape all user inputs for AppleScript
    safe_account = escape_applescript(account)
    safe_subject_keyword = escape_applescript(subject_keyword)
    safe_from_mailbox = escape_applescript(from_mailbox)
    safe_to_mailbox = escape_applescript(to_mailbox)

    # Parse nested mailbox path
    mailbox_parts = to_mailbox.split('/')

    # Build the nested mailbox reference
    if len(mailbox_parts) > 1:
        # Nested mailbox
        dest_mailbox_script = f'mailbox "{escape_applescript(mailbox_parts[-1])}" of '
        for i in range(len(mailbox_parts) - 2, -1, -1):
            dest_mailbox_script += f'mailbox "{escape_applescript(mailbox_parts[i])}" of '
        dest_mailbox_script += 'targetAccount'
    else:
        dest_mailbox_script = f'mailbox "{safe_to_mailbox}" of targetAccount'

    script = f'''
    tell application "Mail"
        set outputText to "MOVING EMAILS" & return & return
        set movedCount to 0

        try
            set targetAccount to account "{safe_account}"
            -- Try to get source mailbox (handle both "INBOX"/"Inbox" variations)
            try
                set sourceMailbox to mailbox "{safe_from_mailbox}" of targetAccount
            on error
                if "{safe_from_mailbox}" is "INBOX" then
                    set sourceMailbox to mailbox "Inbox" of targetAccount
                else
                    error "Source mailbox not found"
                end if
            end try

            -- Get destination mailbox (handles nested mailboxes)
            set destMailbox to {dest_mailbox_script}
            set sourceMessages to every message of sourceMailbox

            repeat with aMessage in sourceMessages
                if movedCount >= {max_moves} then exit repeat

                try
                    set messageSubject to subject of aMessage

                    -- Check if subject contains keyword (case insensitive)
                    if messageSubject contains "{safe_subject_keyword}" then
                        set messageSender to sender of aMessage
                        set messageDate to date received of aMessage

                        -- Move the message
                        move aMessage to destMailbox

                        set outputText to outputText & "✓ Moved: " & messageSubject & return
                        set outputText to outputText & "  From: " & messageSender & return
                        set outputText to outputText & "  Date: " & (messageDate as string) & return
                        set outputText to outputText & "  {safe_from_mailbox} → {safe_to_mailbox}" & return & return

                        set movedCount to movedCount + 1
                    end if
                end try
            end repeat

            set outputText to outputText & "========================================" & return
            set outputText to outputText & "TOTAL MOVED: " & movedCount & " email(s)" & return
            set outputText to outputText & "========================================" & return

        on error errMsg
            return "Error: " & errMsg & return & "Please check that account and mailbox names are correct. For nested mailboxes, use '/' separator (e.g., 'Projects/Amplify Impact')."
        end try

        return outputText
    end tell
    '''

    result = run_applescript(script)
    return result


@mcp.tool()
@inject_preferences
def reply_to_email(
    account: str,
    subject_keyword: str,
    reply_body: str,
    reply_to_all: bool = False,
    cc: Optional[str] = None,
    bcc: Optional[str] = None
) -> str:
    """
    Reply to an email matching a subject keyword.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        subject_keyword: Keyword to search for in email subjects
        reply_body: The body text of the reply
        reply_to_all: If True, reply to all recipients; if False, reply only to sender (default: False)
        cc: Optional CC recipients, comma-separated for multiple
        bcc: Optional BCC recipients, comma-separated for multiple

    Returns:
        Confirmation message with details of the reply sent
    """

    # Escape all user inputs for AppleScript
    safe_account = escape_applescript(account)
    safe_subject_keyword = escape_applescript(subject_keyword)
    escaped_body = escape_applescript(reply_body)

    # Build the reply command based on reply_to_all flag
    if reply_to_all:
        reply_command = 'set replyMessage to reply foundMessage with opening window reply to all'
    else:
        reply_command = 'set replyMessage to reply foundMessage with opening window'

    # Build CC recipients if provided
    cc_script = ''
    if cc:
        cc_addresses = [addr.strip() for addr in cc.split(',')]
        for addr in cc_addresses:
            safe_addr = escape_applescript(addr)
            cc_script += f'''
            make new cc recipient at end of cc recipients of replyMessage with properties {{address:"{safe_addr}"}}
            '''

    # Build BCC recipients if provided
    bcc_script = ''
    if bcc:
        bcc_addresses = [addr.strip() for addr in bcc.split(',')]
        for addr in bcc_addresses:
            safe_addr = escape_applescript(addr)
            bcc_script += f'''
            make new bcc recipient at end of bcc recipients of replyMessage with properties {{address:"{safe_addr}"}}
            '''

    safe_cc = escape_applescript(cc) if cc else ""
    safe_bcc = escape_applescript(bcc) if bcc else ""

    script = f'''
    tell application "Mail"
        set outputText to "SENDING REPLY" & return & return

        try
            set targetAccount to account "{safe_account}"
            -- Try to get inbox (handle both "INBOX" and "Inbox")
            try
                set inboxMailbox to mailbox "INBOX" of targetAccount
            on error
                set inboxMailbox to mailbox "Inbox" of targetAccount
            end try
            set inboxMessages to every message of inboxMailbox
            set foundMessage to missing value

            -- Find the first matching message
            repeat with aMessage in inboxMessages
                try
                    set messageSubject to subject of aMessage

                    if messageSubject contains "{safe_subject_keyword}" then
                        set foundMessage to aMessage
                        exit repeat
                    end if
                end try
            end repeat

            if foundMessage is not missing value then
                set messageSubject to subject of foundMessage
                set messageSender to sender of foundMessage
                set messageDate to date received of foundMessage

                -- Create reply
                {reply_command}

                -- Ensure the reply is from the correct account
                set emailAddrs to email addresses of targetAccount
                set senderAddress to item 1 of emailAddrs
                set sender of replyMessage to senderAddress

                -- Set reply content
                set content of replyMessage to "{escaped_body}"

                -- Add CC/BCC recipients
                {cc_script}
                {bcc_script}

                -- Send the reply
                send replyMessage

                set outputText to outputText & "✓ Reply sent successfully!" & return & return
                set outputText to outputText & "Original email:" & return
                set outputText to outputText & "  Subject: " & messageSubject & return
                set outputText to outputText & "  From: " & messageSender & return
                set outputText to outputText & "  Date: " & (messageDate as string) & return & return
                set outputText to outputText & "Reply body:" & return
                set outputText to outputText & "  " & "{escaped_body}" & return
    '''

    if cc:
        script += f'''
                set outputText to outputText & "CC: {safe_cc}" & return
    '''

    if bcc:
        script += f'''
                set outputText to outputText & "BCC: {safe_bcc}" & return
    '''

    script += f'''
            else
                set outputText to outputText & "⚠ No email found matching: {safe_subject_keyword}" & return
            end if

        on error errMsg
            return "Error: " & errMsg & return & "Please check that the account name is correct and the email exists."
        end try

        return outputText
    end tell
    '''

    result = run_applescript(script)
    return result


@mcp.tool()
@inject_preferences
def compose_email(
    account: str,
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
    bcc: Optional[str] = None
) -> str:
    """
    Compose and send a new email from a specific account.

    Args:
        account: Account name to send from (e.g., "Gmail", "Work", "Personal")
        to: Recipient email address(es), comma-separated for multiple
        subject: Email subject line
        body: Email body text
        cc: Optional CC recipients, comma-separated for multiple
        bcc: Optional BCC recipients, comma-separated for multiple

    Returns:
        Confirmation message with details of the sent email
    """

    # Escape all user inputs for AppleScript
    safe_account = escape_applescript(account)
    escaped_subject = escape_applescript(subject)
    escaped_body = escape_applescript(body)

    # Build TO recipients (split comma-separated addresses)
    to_script = ''
    to_addresses = [addr.strip() for addr in to.split(',')]
    for addr in to_addresses:
        safe_addr = escape_applescript(addr)
        to_script += f'''
                make new to recipient at end of to recipients with properties {{address:"{safe_addr}"}}
        '''

    # Build CC recipients if provided
    cc_script = ''
    if cc:
        cc_addresses = [addr.strip() for addr in cc.split(',')]
        for addr in cc_addresses:
            safe_addr = escape_applescript(addr)
            cc_script += f'''
                make new cc recipient at end of cc recipients with properties {{address:"{safe_addr}"}}
            '''

    # Build BCC recipients if provided
    bcc_script = ''
    if bcc:
        bcc_addresses = [addr.strip() for addr in bcc.split(',')]
        for addr in bcc_addresses:
            safe_addr = escape_applescript(addr)
            bcc_script += f'''
                make new bcc recipient at end of bcc recipients with properties {{address:"{safe_addr}"}}
            '''

    safe_to = escape_applescript(to)
    safe_cc = escape_applescript(cc) if cc else ""
    safe_bcc = escape_applescript(bcc) if bcc else ""

    script = f'''
    tell application "Mail"
        set outputText to "COMPOSING EMAIL" & return & return

        try
            set targetAccount to account "{safe_account}"

            -- Create new outgoing message
            set newMessage to make new outgoing message with properties {{subject:"{escaped_subject}", content:"{escaped_body}", visible:false}}

            -- Set the sender account
            set emailAddrs to email addresses of targetAccount
            set senderAddress to item 1 of emailAddrs
            set sender of newMessage to senderAddress

            -- Add TO/CC/BCC recipients
            tell newMessage
                {to_script}
                {cc_script}
                {bcc_script}
            end tell

            -- Send the message
            send newMessage

            set outputText to outputText & "✓ Email sent successfully!" & return & return
            set outputText to outputText & "From: " & name of targetAccount & return
            set outputText to outputText & "To: {safe_to}" & return
    '''

    if cc:
        script += f'''
            set outputText to outputText & "CC: {safe_cc}" & return
    '''

    if bcc:
        script += f'''
            set outputText to outputText & "BCC: {safe_bcc}" & return
    '''

    script += f'''
            set outputText to outputText & "Subject: {escaped_subject}" & return
            set outputText to outputText & "Body: " & "{escaped_body}" & return

        on error errMsg
            return "Error: " & errMsg & return & "Please check that the account name and email addresses are correct."
        end try

        return outputText
    end tell
    '''

    result = run_applescript(script)
    return result


@mcp.tool()
@inject_preferences
def list_email_attachments(
    account: str,
    subject_keyword: str,
    max_results: int = 1
) -> str:
    """
    List attachments for emails matching a subject keyword.

    Args:
        account: Account name (e.g., "Gmail", "Work", "Personal")
        subject_keyword: Keyword to search for in email subjects
        max_results: Maximum number of matching emails to check (default: 1)

    Returns:
        List of attachments with their names and sizes
    """

    # Escape for AppleScript
    escaped_keyword = escape_applescript(subject_keyword)
    escaped_account = escape_applescript(account)

    script = f'''
    tell application "Mail"
        set outputText to "ATTACHMENTS FOR: {escaped_keyword}" & return & return
        set resultCount to 0

        try
            set targetAccount to account "{escaped_account}"
            -- Try to get inbox (handle both "INBOX" and "Inbox")
            try
                set inboxMailbox to mailbox "INBOX" of targetAccount
            on error
                set inboxMailbox to mailbox "Inbox" of targetAccount
            end try
            set inboxMessages to every message of inboxMailbox

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

    result = run_applescript(script)
    return result


@mcp.tool()
@inject_preferences
def save_email_attachment(
    account: str,
    subject_keyword: str,
    attachment_name: str,
    save_path: str
) -> str:
    """
    Save a specific attachment from an email to disk.

    Args:
        account: Account name (e.g., "Gmail", "Work", "Personal")
        subject_keyword: Keyword to search for in email subjects
        attachment_name: Name of the attachment to save
        save_path: Full path where to save the attachment

    Returns:
        Confirmation message with save location
    """

    # Expand tilde in save_path (POSIX file in AppleScript does not expand ~)
    expanded_path = os.path.expanduser(save_path)

    # Escape for AppleScript
    escaped_account = escape_applescript(account)
    escaped_keyword = escape_applescript(subject_keyword)
    escaped_attachment = escape_applescript(attachment_name)
    escaped_path = escape_applescript(expanded_path)

    script = f'''
    tell application "Mail"
        set outputText to ""

        try
            set targetAccount to account "{escaped_account}"
            -- Try to get inbox (handle both "INBOX" and "Inbox")
            try
                set inboxMailbox to mailbox "INBOX" of targetAccount
            on error
                set inboxMailbox to mailbox "Inbox" of targetAccount
            end try
            set inboxMessages to every message of inboxMailbox
            set foundAttachment to false

            repeat with aMessage in inboxMessages
                try
                    set messageSubject to subject of aMessage

                    -- Check if subject contains keyword
                    if messageSubject contains "{escaped_keyword}" then
                        set msgAttachments to mail attachments of aMessage

                        repeat with anAttachment in msgAttachments
                            set attachmentFileName to name of anAttachment

                            if attachmentFileName contains "{escaped_attachment}" then
                                -- Save the attachment
                                save anAttachment in POSIX file "{escaped_path}"

                                set outputText to "✓ Attachment saved successfully!" & return & return
                                set outputText to outputText & "Email: " & messageSubject & return
                                set outputText to outputText & "Attachment: " & attachmentFileName & return
                                set outputText to outputText & "Saved to: {escaped_path}" & return

                                set foundAttachment to true
                                exit repeat
                            end if
                        end repeat

                        if foundAttachment then exit repeat
                    end if
                end try
            end repeat

            if not foundAttachment then
                set outputText to "⚠ Attachment not found" & return
                set outputText to outputText & "Email keyword: {escaped_keyword}" & return
                set outputText to outputText & "Attachment name: {escaped_attachment}" & return
            end if

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
def get_inbox_overview() -> str:
    """
    Get a comprehensive overview of your email inbox status across all accounts.

    Returns:
        Comprehensive overview including:
        - Unread email counts by account
        - List of available mailboxes/folders
        - AI suggestions for actions (move emails, respond to messages, highlight action items, etc.)

    This tool is designed to give you a complete picture of your inbox and prompt the assistant
    to suggest relevant actions based on the current state.
    """

    script = '''
    tell application "Mail"
        set outputText to "╔══════════════════════════════════════════╗" & return
        set outputText to outputText & "║      EMAIL INBOX OVERVIEW                ║" & return
        set outputText to outputText & "╚══════════════════════════════════════════╝" & return & return

        -- Section 1: Unread Counts by Account
        set outputText to outputText & "📊 UNREAD EMAILS BY ACCOUNT" & return
        set outputText to outputText & "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" & return
        set allAccounts to every account
        set totalUnread to 0

        repeat with anAccount in allAccounts
            set accountName to name of anAccount

            try
                -- Try to get inbox (handle both "INBOX" and "Inbox")
                try
                    set inboxMailbox to mailbox "INBOX" of anAccount
                on error
                    set inboxMailbox to mailbox "Inbox" of anAccount
                end try

                set unreadCount to unread count of inboxMailbox
                set totalMessages to count of messages of inboxMailbox
                set totalUnread to totalUnread + unreadCount

                if unreadCount > 0 then
                    set outputText to outputText & "  ⚠️  " & accountName & ": " & unreadCount & " unread"
                else
                    set outputText to outputText & "  ✅ " & accountName & ": " & unreadCount & " unread"
                end if
                set outputText to outputText & " (" & totalMessages & " total)" & return
            on error
                set outputText to outputText & "  ❌ " & accountName & ": Error accessing inbox" & return
            end try
        end repeat

        set outputText to outputText & return
        set outputText to outputText & "📈 TOTAL UNREAD: " & totalUnread & " across all accounts" & return
        set outputText to outputText & return & return

        -- Section 2: Mailboxes/Folders Overview
        set outputText to outputText & "📁 MAILBOX STRUCTURE" & return
        set outputText to outputText & "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" & return

        repeat with anAccount in allAccounts
            set accountName to name of anAccount
            set outputText to outputText & return & "Account: " & accountName & return

            try
                set accountMailboxes to every mailbox of anAccount

                repeat with aMailbox in accountMailboxes
                    set mailboxName to name of aMailbox

                    try
                        set unreadCount to unread count of aMailbox
                        if unreadCount > 0 then
                            set outputText to outputText & "  📂 " & mailboxName & " (" & unreadCount & " unread)" & return
                        else
                            set outputText to outputText & "  📂 " & mailboxName & return
                        end if

                        -- Show nested mailboxes if they have unread messages
                        try
                            set subMailboxes to every mailbox of aMailbox
                            repeat with subBox in subMailboxes
                                set subName to name of subBox
                                set subUnread to unread count of subBox

                                if subUnread > 0 then
                                    set outputText to outputText & "     └─ " & subName & " (" & subUnread & " unread)" & return
                                end if
                            end repeat
                        end try
                    on error
                        set outputText to outputText & "  📂 " & mailboxName & return
                    end try
                end repeat
            on error
                set outputText to outputText & "  ⚠️  Error accessing mailboxes" & return
            end try
        end repeat

        set outputText to outputText & return & return

        -- Section 3: Recent Emails Preview (10 most recent across all accounts)
        set outputText to outputText & "📬 RECENT EMAILS PREVIEW (10 Most Recent)" & return
        set outputText to outputText & "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" & return

        -- Collect all recent messages from all accounts
        set allRecentMessages to {}

        repeat with anAccount in allAccounts
            set accountName to name of anAccount

            try
                -- Try to get inbox (handle both "INBOX" and "Inbox")
                try
                    set inboxMailbox to mailbox "INBOX" of anAccount
                on error
                    set inboxMailbox to mailbox "Inbox" of anAccount
                end try

                set inboxMessages to every message of inboxMailbox

                -- Get up to 10 messages from each account
                set messageIndex to 0
                repeat with aMessage in inboxMessages
                    set messageIndex to messageIndex + 1
                    if messageIndex > 10 then exit repeat

                    try
                        set messageSubject to subject of aMessage
                        set messageSender to sender of aMessage
                        set messageDate to date received of aMessage
                        set messageRead to read status of aMessage

                        -- Create message record
                        set messageRecord to {accountName:accountName, msgSubject:messageSubject, msgSender:messageSender, msgDate:messageDate, msgRead:messageRead}
                        set end of allRecentMessages to messageRecord
                    end try
                end repeat
            end try
        end repeat

        -- Display up to 10 most recent messages
        set displayCount to 0
        repeat with msgRecord in allRecentMessages
            set displayCount to displayCount + 1
            if displayCount > 10 then exit repeat

            set readIndicator to "✉"
            if msgRead of msgRecord then
                set readIndicator to "✓"
            end if

            set outputText to outputText & return & readIndicator & " " & msgSubject of msgRecord & return
            set outputText to outputText & "   Account: " & accountName of msgRecord & return
            set outputText to outputText & "   From: " & msgSender of msgRecord & return
            set outputText to outputText & "   Date: " & (msgDate of msgRecord as string) & return
        end repeat

        if displayCount = 0 then
            set outputText to outputText & return & "No recent emails found." & return
        end if

        set outputText to outputText & return & return

        -- Section 4: Action Suggestions (for the AI assistant)
        set outputText to outputText & "💡 SUGGESTED ACTIONS FOR ASSISTANT" & return
        set outputText to outputText & "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" & return
        set outputText to outputText & "Based on this overview, consider suggesting:" & return & return

        if totalUnread > 0 then
            set outputText to outputText & "1. 📧 Review unread emails - Use get_recent_emails() to show recent unread messages" & return
            set outputText to outputText & "2. 🔍 Search for action items - Look for keywords like 'urgent', 'action required', 'deadline'" & return
            set outputText to outputText & "3. 📤 Move processed emails - Suggest moving read emails to appropriate folders" & return
        else
            set outputText to outputText & "1. ✅ Inbox is clear! No unread emails." & return
        end if

        set outputText to outputText & "4. 📋 Organize by topic - Suggest moving emails to project-specific folders" & return
        set outputText to outputText & "5. ✉️  Draft replies - Identify emails that need responses" & return
        set outputText to outputText & "6. 🗂️  Archive old emails - Move older read emails to archive folders" & return
        set outputText to outputText & "7. 🔔 Highlight priority items - Identify emails from important senders or with urgent keywords" & return

        set outputText to outputText & return
        set outputText to outputText & "═══════════════════════════════════════════════════" & return
        set outputText to outputText & "💬 Ask me to drill down into any account or take specific actions!" & return
        set outputText to outputText & "═══════════════════════════════════════════════════" & return

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
    max_results: int = 20
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

    Returns:
        Formatted list of matching emails with all requested details
    """

    # Escape user inputs for AppleScript
    escaped_account = account.replace('\\', '\\\\').replace('"', '\\"')
    escaped_mailbox = mailbox.replace('\\', '\\\\').replace('"', '\\"')
    escaped_subject = subject_keyword.replace('\\', '\\\\').replace('"', '\\"') if subject_keyword else None
    escaped_sender = sender.replace('\\', '\\\\').replace('"', '\\"') if sender else None

    # Build AppleScript search conditions
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

    # Combine conditions with AND logic
    condition_str = ' and '.join(conditions) if conditions else 'true'

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
            {mailbox_script}

            repeat with currentMailbox in searchMailboxes
                -- Wrap in try block to handle mailboxes that throw errors (smart mailboxes, etc.)
                try
                    set mailboxName to name of currentMailbox

                    -- Skip system folders when searching to reduce noise and avoid errors
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

                                -- Apply search conditions
                                if {condition_str} then
                                    set readIndicator to "✉"
                                    if messageRead then
                                        set readIndicator to "✓"
                                    end if

                                    set outputText to outputText & readIndicator & " " & messageSubject & return
                                    set outputText to outputText & "   From: " & messageSender & return
                                    set outputText to outputText & "   Date: " & (messageDate as string) & return
                                    set outputText to outputText & "   Mailbox: " & mailboxName & return

                                    {content_script}

                                    set outputText to outputText & return
                                    set resultCount to resultCount + 1
                                end if
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
    return result


@mcp.tool()
@inject_preferences
def search_by_sender(
    sender: str,
    account: Optional[str] = None,
    days_back: int = 30,
    max_results: int = 20,
    include_content: bool = True,
    max_content_length: int = 500
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

    Returns:
        Formatted list of emails from the sender, sorted by date (newest first)
    """

    # Build date filter if days_back > 0
    date_filter_script = ""
    date_check = ""
    if days_back > 0:
        date_filter_script = f'''
            set targetDate to (current date) - ({days_back} * days)
        '''
        date_check = "and messageDate > targetDate"

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

    # Escape user inputs for AppleScript
    escaped_account = account.replace('\\', '\\\\').replace('"', '\\"') if account else None

    # Build account filter script
    if account:
        account_filter_start = f'if accountName is "{escaped_account}" then'
        account_filter_end = "end if"
    else:
        account_filter_start = ""
        account_filter_end = ""

    # Escape the sender parameter for AppleScript
    escaped_sender = sender.replace('\\', '\\\\').replace('"', '\\"')

    script = f'''
    on lowercase(str)
        set lowerStr to do shell script "echo " & quoted form of str & " | tr '[:upper:]' '[:lower:]'"
        return lowerStr
    end lowercase

    tell application "Mail"
        set outputText to "EMAILS FROM SENDER: {escaped_sender}" & return
        set outputText to outputText & "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" & return & return
        set resultCount to 0

        {date_filter_script}

        set allAccounts to every account

        repeat with anAccount in allAccounts
            set accountName to name of anAccount

            {account_filter_start}

            try
                -- Get all mailboxes except Trash, Junk, Deleted
                set accountMailboxes to every mailbox of anAccount

                repeat with aMailbox in accountMailboxes
                    set mailboxName to name of aMailbox

                    -- Skip Trash, Junk, Deleted, Spam folders
                    if mailboxName is not "Trash" and mailboxName is not "Junk" and mailboxName is not "Deleted Messages" and mailboxName is not "Deleted Items" and mailboxName is not "Spam" then

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
                                        set readIndicator to "✓"
                                    else
                                        set readIndicator to "✉"
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

                        if resultCount >= {max_results} then exit repeat
                    end if
                end repeat

            on error errMsg
                set outputText to outputText & "⚠ Error accessing mailboxes for " & accountName & ": " & errMsg & return
            end try

            {account_filter_end}

            if resultCount >= {max_results} then exit repeat
        end repeat

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
    escaped_search = search_text.replace('\\', '\\\\').replace('"', '\\"').lower()
    escaped_account = account.replace('\\', '\\\\').replace('"', '\\"')
    escaped_mailbox = mailbox.replace('\\', '\\\\').replace('"', '\\"')
    search_conditions = []
    if search_subject:
        search_conditions.append(f'lowerSubject contains "{escaped_search}"')
    if search_body:
        search_conditions.append(f'lowerContent contains "{escaped_search}"')
    search_condition = ' or '.join(search_conditions) if search_conditions else 'false'

    script = f'''
    on lowercase(str)
        set lowerStr to do shell script "echo " & quoted form of str & " | tr '[:upper:]' '[:lower:]'"
        return lowerStr
    end lowercase

    tell application "Mail"
        set outputText to "🔎 CONTENT SEARCH: {escaped_search}" & return
        set outputText to outputText & "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" & return
        set outputText to outputText & "⚠ Note: Body search is slower - searching {max_results} results max" & return & return
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
                            set readIndicator to "✓"
                        else
                            set readIndicator to "✉"
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
    escaped_account = account.replace('\\', '\\\\').replace('"', '\\"') if account else None

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

    date_filter = ""
    date_check = ""
    if days_back > 0:
        date_filter = f'set cutoffDate to (current date) - ({days_back} * days)'
        date_check = " and messageDate > cutoffDate"

    script = f'''
    on lowercase(str)
        set lowerStr to do shell script "echo " & quoted form of str & " | tr '[:upper:]' '[:lower:]'"
        return lowerStr
    end lowercase

    tell application "Mail"
        set outputText to "📰 NEWSLETTER DETECTION" & return
        set outputText to outputText & "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" & return & return
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
                                            set readIndicator to "✓"
                                        else
                                            set readIndicator to "✉"
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
    max_content_length: int = 400
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

    Returns:
        Recent emails from the specified sender within the time range
    """
    time_ranges = {"today": 1, "yesterday": 2, "week": 7, "month": 30, "all": 0}
    days_back = time_ranges.get(time_range.lower(), 7)
    is_yesterday = time_range.lower() == "yesterday"

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

    # Escape user inputs for AppleScript
    escaped_account = account.replace('\\', '\\\\').replace('"', '\\"') if account else None

    account_filter_start = ""
    account_filter_end = ""
    if account:
        account_filter_start = f'if accountName is "{escaped_account}" then'
        account_filter_end = "end if"

    date_filter = ""
    date_check = ""
    if days_back > 0:
        date_filter = f'set cutoffDate to (current date) - ({days_back} * days)'
        if is_yesterday:
            date_filter += '''
            set todayStart to (current date) - (time of (current date))
            set yesterdayStart to todayStart - (1 * days)
            '''
            date_check = " and messageDate >= yesterdayStart and messageDate < todayStart"
        else:
            date_check = " and messageDate > cutoffDate"

    escaped_sender = sender.replace('\\', '\\\\').replace('"', '\\"')

    script = f'''
    on lowercase(str)
        set lowerStr to do shell script "echo " & quoted form of str & " | tr '[:upper:]' '[:lower:]'"
        return lowerStr
    end lowercase

    tell application "Mail"
        set outputText to "📧 EMAILS FROM: {escaped_sender}" & return
        set outputText to outputText & "⏰ Time range: {time_range}" & return
        set outputText to outputText & "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" & return & return
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
                        if mailboxName is not in {{"Trash", "Junk", "Junk Email", "Deleted Items", "Sent", "Sent Items", "Sent Messages", "Drafts", "Spam", "Deleted Messages"}} then
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
                                            set readIndicator to "✓"
                                        else
                                            set readIndicator to "✉"
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
        set outputText to outputText & "FOUND: " & resultCount & " email(s) from sender" & return
        set outputText to outputText & "========================================" & return
        return outputText
    end tell
    '''
    result = run_applescript(script)
    return result


@mcp.tool()
@inject_preferences
def update_email_status(
    account: str,
    action: str,
    subject_keyword: Optional[str] = None,
    sender: Optional[str] = None,
    mailbox: str = "INBOX",
    max_updates: int = 10
) -> str:
    """
    Update email status - mark as read/unread or flag/unflag emails.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        action: Action to perform: "mark_read", "mark_unread", "flag", "unflag"
        subject_keyword: Optional keyword to filter emails by subject
        sender: Optional sender to filter emails by
        mailbox: Mailbox to search in (default: "INBOX")
        max_updates: Maximum number of emails to update (safety limit, default: 10)

    Returns:
        Confirmation message with details of updated emails
    """

    # Escape all user inputs for AppleScript
    safe_account = escape_applescript(account)
    safe_mailbox = escape_applescript(mailbox)

    # Build search condition
    conditions = []
    if subject_keyword:
        conditions.append(f'messageSubject contains "{escape_applescript(subject_keyword)}"')
    if sender:
        conditions.append(f'messageSender contains "{escape_applescript(sender)}"')

    condition_str = ' and '.join(conditions) if conditions else 'true'

    # Build action script
    if action == "mark_read":
        action_script = 'set read status of aMessage to true'
        action_label = "Marked as read"
    elif action == "mark_unread":
        action_script = 'set read status of aMessage to false'
        action_label = "Marked as unread"
    elif action == "flag":
        action_script = 'set flagged status of aMessage to true'
        action_label = "Flagged"
    elif action == "unflag":
        action_script = 'set flagged status of aMessage to false'
        action_label = "Unflagged"
    else:
        return f"Error: Invalid action '{action}'. Use: mark_read, mark_unread, flag, unflag"

    script = f'''
    tell application "Mail"
        set outputText to "UPDATING EMAIL STATUS: {action_label}" & return & return
        set updateCount to 0

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

            set mailboxMessages to every message of targetMailbox

            repeat with aMessage in mailboxMessages
                if updateCount >= {max_updates} then exit repeat

                try
                    set messageSubject to subject of aMessage
                    set messageSender to sender of aMessage
                    set messageDate to date received of aMessage

                    -- Apply filter conditions
                    if {condition_str} then
                        {action_script}

                        set outputText to outputText & "✓ {action_label}: " & messageSubject & return
                        set outputText to outputText & "   From: " & messageSender & return
                        set outputText to outputText & "   Date: " & (messageDate as string) & return & return

                        set updateCount to updateCount + 1
                    end if
                end try
            end repeat

            set outputText to outputText & "========================================" & return
            set outputText to outputText & "TOTAL UPDATED: " & updateCount & " email(s)" & return
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
def manage_trash(
    account: str,
    action: str,
    subject_keyword: Optional[str] = None,
    sender: Optional[str] = None,
    mailbox: str = "INBOX",
    max_deletes: int = 5
) -> str:
    """
    Manage trash operations - delete emails or empty trash.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        action: Action to perform: "move_to_trash", "delete_permanent", "empty_trash"
        subject_keyword: Optional keyword to filter emails (not used for empty_trash)
        sender: Optional sender to filter emails (not used for empty_trash)
        mailbox: Source mailbox (default: "INBOX", not used for empty_trash or delete_permanent)
        max_deletes: Maximum number of emails to delete (safety limit, default: 5)

    Returns:
        Confirmation message with details of deleted emails
    """

    # Escape all user inputs for AppleScript
    safe_account = escape_applescript(account)
    safe_mailbox = escape_applescript(mailbox)

    if action == "empty_trash":
        script = f'''
        tell application "Mail"
            set outputText to "EMPTYING TRASH" & return & return

            try
                set targetAccount to account "{safe_account}"
                set trashMailbox to mailbox "Trash" of targetAccount
                set trashMessages to every message of trashMailbox
                set messageCount to count of trashMessages

                -- Delete all messages in trash
                repeat with aMessage in trashMessages
                    delete aMessage
                end repeat

                set outputText to outputText & "✓ Emptied trash for account: {safe_account}" & return
                set outputText to outputText & "   Deleted " & messageCount & " message(s)" & return

            on error errMsg
                return "Error: " & errMsg
            end try

            return outputText
        end tell
        '''
    elif action == "delete_permanent":
        # Build search condition with escaped inputs
        conditions = []
        if subject_keyword:
            conditions.append(f'messageSubject contains "{escape_applescript(subject_keyword)}"')
        if sender:
            conditions.append(f'messageSender contains "{escape_applescript(sender)}"')

        condition_str = ' and '.join(conditions) if conditions else 'true'

        script = f'''
        tell application "Mail"
            set outputText to "PERMANENTLY DELETING EMAILS" & return & return
            set deleteCount to 0

            try
                set targetAccount to account "{safe_account}"
                set trashMailbox to mailbox "Trash" of targetAccount
                set trashMessages to every message of trashMailbox

                repeat with aMessage in trashMessages
                    if deleteCount >= {max_deletes} then exit repeat

                    try
                        set messageSubject to subject of aMessage
                        set messageSender to sender of aMessage

                        -- Apply filter conditions
                        if {condition_str} then
                            set outputText to outputText & "✓ Permanently deleted: " & messageSubject & return
                            set outputText to outputText & "   From: " & messageSender & return & return

                            delete aMessage
                            set deleteCount to deleteCount + 1
                        end if
                    end try
                end repeat

                set outputText to outputText & "========================================" & return
                set outputText to outputText & "TOTAL DELETED: " & deleteCount & " email(s)" & return
                set outputText to outputText & "========================================" & return

            on error errMsg
                return "Error: " & errMsg
            end try

            return outputText
        end tell
        '''
    else:  # move_to_trash
        # Build search condition with escaped inputs
        conditions = []
        if subject_keyword:
            conditions.append(f'messageSubject contains "{escape_applescript(subject_keyword)}"')
        if sender:
            conditions.append(f'messageSender contains "{escape_applescript(sender)}"')

        condition_str = ' and '.join(conditions) if conditions else 'true'

        script = f'''
        tell application "Mail"
            set outputText to "MOVING EMAILS TO TRASH" & return & return
            set deleteCount to 0

            try
                set targetAccount to account "{safe_account}"
                -- Get source mailbox
                try
                    set sourceMailbox to mailbox "{safe_mailbox}" of targetAccount
                on error
                    if "{safe_mailbox}" is "INBOX" then
                        set sourceMailbox to mailbox "Inbox" of targetAccount
                    else
                        error "Mailbox not found: {safe_mailbox}"
                    end if
                end try

                -- Get trash mailbox
                set trashMailbox to mailbox "Trash" of targetAccount
                set sourceMessages to every message of sourceMailbox

                repeat with aMessage in sourceMessages
                    if deleteCount >= {max_deletes} then exit repeat

                    try
                        set messageSubject to subject of aMessage
                        set messageSender to sender of aMessage
                        set messageDate to date received of aMessage

                        -- Apply filter conditions
                        if {condition_str} then
                            move aMessage to trashMailbox

                            set outputText to outputText & "✓ Moved to trash: " & messageSubject & return
                            set outputText to outputText & "   From: " & messageSender & return
                            set outputText to outputText & "   Date: " & (messageDate as string) & return & return

                            set deleteCount to deleteCount + 1
                        end if
                    end try
                end repeat

                set outputText to outputText & "========================================" & return
                set outputText to outputText & "TOTAL MOVED TO TRASH: " & deleteCount & " email(s)" & return
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
def forward_email(
    account: str,
    subject_keyword: str,
    to: str,
    message: Optional[str] = None,
    mailbox: str = "INBOX",
    cc: Optional[str] = None,
    bcc: Optional[str] = None
) -> str:
    """
    Forward an email to one or more recipients.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        subject_keyword: Keyword to search for in email subjects
        to: Recipient email address(es), comma-separated for multiple
        message: Optional message to add before forwarded content
        mailbox: Mailbox to search in (default: "INBOX")
        cc: Optional CC recipients, comma-separated for multiple
        bcc: Optional BCC recipients, comma-separated for multiple

    Returns:
        Confirmation message with details of forwarded email
    """

    # Escape all user inputs for AppleScript
    safe_account = escape_applescript(account)
    safe_subject_keyword = escape_applescript(subject_keyword)
    safe_to = escape_applescript(to)
    safe_mailbox = escape_applescript(mailbox)
    escaped_message = escape_applescript(message) if message else ""

    # Build CC recipients if provided
    cc_script = ''
    if cc:
        cc_addresses = [addr.strip() for addr in cc.split(',')]
        for addr in cc_addresses:
            safe_addr = escape_applescript(addr)
            cc_script += f'''
            make new cc recipient at end of cc recipients of forwardMessage with properties {{address:"{safe_addr}"}}
            '''

    # Build BCC recipients if provided
    bcc_script = ''
    if bcc:
        bcc_addresses = [addr.strip() for addr in bcc.split(',')]
        for addr in bcc_addresses:
            safe_addr = escape_applescript(addr)
            bcc_script += f'''
            make new bcc recipient at end of bcc recipients of forwardMessage with properties {{address:"{safe_addr}"}}
            '''

    safe_cc = escape_applescript(cc) if cc else ""
    safe_bcc = escape_applescript(bcc) if bcc else ""

    # Build TO recipients (split comma-separated)
    to_script = ''
    to_addresses = [addr.strip() for addr in to.split(',')]
    for addr in to_addresses:
        safe_addr = escape_applescript(addr)
        to_script += f'''
                make new to recipient at end of to recipients of forwardMessage with properties {{address:"{safe_addr}"}}
        '''

    script = f'''
    tell application "Mail"
        set outputText to "FORWARDING EMAIL" & return & return

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

            set mailboxMessages to every message of targetMailbox
            set foundMessage to missing value

            -- Find the first matching message
            repeat with aMessage in mailboxMessages
                try
                    set messageSubject to subject of aMessage

                    if messageSubject contains "{safe_subject_keyword}" then
                        set foundMessage to aMessage
                        exit repeat
                    end if
                end try
            end repeat

            if foundMessage is not missing value then
                set messageSubject to subject of foundMessage
                set messageSender to sender of foundMessage
                set messageDate to date received of foundMessage

                -- Create forward
                set forwardMessage to forward foundMessage with opening window

                -- Set sender account
                set emailAddrs to email addresses of targetAccount
                set senderAddress to item 1 of emailAddrs
                set sender of forwardMessage to senderAddress

                -- Add recipients
                {to_script}

                -- Add CC/BCC recipients
                {cc_script}
                {bcc_script}

                -- Add optional message
                if "{escaped_message}" is not "" then
                    set content of forwardMessage to "{escaped_message}" & return & return & content of forwardMessage
                end if

                -- Send the forward
                send forwardMessage

                set outputText to outputText & "✓ Email forwarded successfully!" & return & return
                set outputText to outputText & "Original email:" & return
                set outputText to outputText & "  Subject: " & messageSubject & return
                set outputText to outputText & "  From: " & messageSender & return
                set outputText to outputText & "  Date: " & (messageDate as string) & return & return
                set outputText to outputText & "Forwarded to: {safe_to}" & return
    '''

    if cc:
        script += f'''
                set outputText to outputText & "CC: {safe_cc}" & return
    '''

    if bcc:
        script += f'''
                set outputText to outputText & "BCC: {safe_bcc}" & return
    '''

    script += f'''
            else
                set outputText to outputText & "⚠ No email found matching: {safe_subject_keyword}" & return
            end if

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
    escaped_account = account.replace('\\', '\\\\').replace('"', '\\"')
    escaped_mailbox = mailbox.replace('\\', '\\\\').replace('"', '\\"')

    # For thread detection, we'll strip common prefixes
    thread_keywords = ['Re:', 'Fwd:', 'FW:', 'RE:', 'Fw:']
    cleaned_keyword = subject_keyword
    for prefix in thread_keywords:
        cleaned_keyword = cleaned_keyword.replace(prefix, '').strip()
    escaped_keyword = cleaned_keyword.replace('\\', '\\\\').replace('"', '\\"')

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


@mcp.tool()
@inject_preferences
def manage_drafts(
    account: str,
    action: str,
    subject: Optional[str] = None,
    to: Optional[str] = None,
    body: Optional[str] = None,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    draft_subject: Optional[str] = None
) -> str:
    """
    Manage draft emails - list, create, send, or delete drafts.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        action: Action to perform: "list", "create", "send", "delete"
        subject: Email subject (required for create)
        to: Recipient email(s) for create (comma-separated)
        body: Email body (required for create)
        cc: Optional CC recipients for create
        bcc: Optional BCC recipients for create
        draft_subject: Subject keyword to find draft (required for send/delete)

    Returns:
        Formatted output based on action
    """

    # Escape account for all paths
    safe_account = escape_applescript(account)

    if action == "list":
        script = f'''
        tell application "Mail"
            set outputText to "DRAFT EMAILS - {safe_account}" & return & return

            try
                set targetAccount to account "{safe_account}"
                set draftsMailbox to mailbox "Drafts" of targetAccount
                set draftMessages to every message of draftsMailbox
                set draftCount to count of draftMessages

                set outputText to outputText & "Found " & draftCount & " draft(s)" & return & return

                repeat with aDraft in draftMessages
                    try
                        set draftSubject to subject of aDraft
                        set draftDate to date sent of aDraft

                        set outputText to outputText & "✉ " & draftSubject & return
                        set outputText to outputText & "   Created: " & (draftDate as string) & return & return
                    end try
                end repeat

            on error errMsg
                return "Error: " & errMsg
            end try

            return outputText
        end tell
        '''

    elif action == "create":
        if not subject or not to or not body:
            return "Error: 'subject', 'to', and 'body' are required for creating drafts"

        escaped_subject = escape_applescript(subject)
        escaped_body = escape_applescript(body)
        safe_to = escape_applescript(to)

        # Build TO recipients (split comma-separated)
        to_script = ''
        to_addresses = [addr.strip() for addr in to.split(',')]
        for addr in to_addresses:
            safe_addr = escape_applescript(addr)
            to_script += f'''
                    make new to recipient at end of to recipients with properties {{address:"{safe_addr}"}}
            '''

        # Build CC recipients if provided
        cc_script = ''
        if cc:
            cc_addresses = [addr.strip() for addr in cc.split(',')]
            for addr in cc_addresses:
                safe_addr = escape_applescript(addr)
                cc_script += f'''
                    make new cc recipient at end of cc recipients with properties {{address:"{safe_addr}"}}
                '''

        # Build BCC recipients if provided
        bcc_script = ''
        if bcc:
            bcc_addresses = [addr.strip() for addr in bcc.split(',')]
            for addr in bcc_addresses:
                safe_addr = escape_applescript(addr)
                bcc_script += f'''
                    make new bcc recipient at end of bcc recipients with properties {{address:"{safe_addr}"}}
                '''

        script = f'''
        tell application "Mail"
            set outputText to "CREATING DRAFT" & return & return

            try
                set targetAccount to account "{safe_account}"

                -- Create new outgoing message (draft)
                set newDraft to make new outgoing message with properties {{subject:"{escaped_subject}", content:"{escaped_body}", visible:false}}

                -- Set the sender account
                set emailAddrs to email addresses of targetAccount
                set senderAddress to item 1 of emailAddrs
                set sender of newDraft to senderAddress

                -- Add recipients
                tell newDraft
                    {to_script}
                    {cc_script}
                    {bcc_script}
                end tell

                -- Save to drafts (don't send)
                -- The draft is automatically saved to Drafts folder

                set outputText to outputText & "✓ Draft created successfully!" & return & return
                set outputText to outputText & "Subject: {escaped_subject}" & return
                set outputText to outputText & "To: {safe_to}" & return

            on error errMsg
                return "Error: " & errMsg
            end try

            return outputText
        end tell
        '''

    elif action == "send":
        if not draft_subject:
            return "Error: 'draft_subject' is required for sending drafts"

        safe_draft_subject = escape_applescript(draft_subject)

        script = f'''
        tell application "Mail"
            set outputText to "SENDING DRAFT" & return & return

            try
                set targetAccount to account "{safe_account}"
                set draftsMailbox to mailbox "Drafts" of targetAccount
                set draftMessages to every message of draftsMailbox
                set foundDraft to missing value

                -- Find the draft
                repeat with aDraft in draftMessages
                    try
                        set draftSubject to subject of aDraft

                        if draftSubject contains "{safe_draft_subject}" then
                            set foundDraft to aDraft
                            exit repeat
                        end if
                    end try
                end repeat

                if foundDraft is not missing value then
                    set draftSubject to subject of foundDraft

                    -- Send the draft
                    send foundDraft

                    set outputText to outputText & "✓ Draft sent successfully!" & return
                    set outputText to outputText & "Subject: " & draftSubject & return

                else
                    set outputText to outputText & "⚠ No draft found matching: {safe_draft_subject}" & return
                end if

            on error errMsg
                return "Error: " & errMsg
            end try

            return outputText
        end tell
        '''

    elif action == "delete":
        if not draft_subject:
            return "Error: 'draft_subject' is required for deleting drafts"

        safe_draft_subject = escape_applescript(draft_subject)

        script = f'''
        tell application "Mail"
            set outputText to "DELETING DRAFT" & return & return

            try
                set targetAccount to account "{safe_account}"
                set draftsMailbox to mailbox "Drafts" of targetAccount
                set draftMessages to every message of draftsMailbox
                set foundDraft to missing value

                -- Find the draft
                repeat with aDraft in draftMessages
                    try
                        set draftSubject to subject of aDraft

                        if draftSubject contains "{safe_draft_subject}" then
                            set foundDraft to aDraft
                            exit repeat
                        end if
                    end try
                end repeat

                if foundDraft is not missing value then
                    set draftSubject to subject of foundDraft

                    -- Delete the draft
                    delete foundDraft

                    set outputText to outputText & "✓ Draft deleted successfully!" & return
                    set outputText to outputText & "Subject: " & draftSubject & return

                else
                    set outputText to outputText & "⚠ No draft found matching: {safe_draft_subject}" & return
                end if

            on error errMsg
                return "Error: " & errMsg
            end try

            return outputText
        end tell
        '''

    else:
        return f"Error: Invalid action '{action}'. Use: list, create, send, delete"

    result = run_applescript(script)
    return result


@mcp.tool()
@inject_preferences
def get_statistics(
    account: str,
    scope: str = "account_overview",
    sender: Optional[str] = None,
    mailbox: Optional[str] = None,
    days_back: int = 30
) -> str:
    """
    Get comprehensive email statistics and analytics.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        scope: Analysis scope: "account_overview", "sender_stats", "mailbox_breakdown"
        sender: Specific sender for "sender_stats" scope
        mailbox: Specific mailbox for "mailbox_breakdown" scope
        days_back: Number of days to analyze (default: 30, 0 = all time)

    Returns:
        Formatted statistics report with metrics and insights
    """

    # Escape user inputs for AppleScript
    escaped_account = account.replace('\\', '\\\\').replace('"', '\\"')
    escaped_sender = sender.replace('\\', '\\\\').replace('"', '\\"') if sender else None
    escaped_mailbox = mailbox.replace('\\', '\\\\').replace('"', '\\"') if mailbox else None

    # Calculate date threshold if days_back > 0
    date_filter = ""
    if days_back > 0:
        date_filter = f'''
            set targetDate to (current date) - ({days_back} * days)
        '''
        date_check = 'and messageDate > targetDate'
    else:
        date_filter = ""
        date_check = ""

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
                    set mailboxName to name of aMailbox
                    set mailboxMessages to every message of aMailbox
                    set mailboxTotal to 0

                    repeat with aMessage in mailboxMessages
                        try
                            set messageDate to date received of aMessage

                            -- Apply date filter if specified
                            if true {date_check} then
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
                            end if
                        end try
                    end repeat

                    -- Store mailbox counts
                    if mailboxTotal > 0 then
                        set end of mailboxCounts to {{mailboxName, mailboxTotal}}
                    end if
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

                set totalFromSender to 0
                set unreadFromSender to 0
                set withAttachments to 0

                repeat with aMailbox in allMailboxes
                    set mailboxMessages to every message of aMailbox

                    repeat with aMessage in mailboxMessages
                        try
                            set messageSender to sender of aMessage
                            set messageDate to date received of aMessage

                            if messageSender contains "{escaped_sender}" {date_check} then
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

                set mailboxMessages to every message of targetMailbox
                set totalMessages to count of mailboxMessages
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
        return f"Error: Invalid scope '{scope}'. Use: account_overview, sender_stats, mailbox_breakdown"

    result = run_applescript(script)
    return result


@mcp.tool()
@inject_preferences
def export_emails(
    account: str,
    scope: str,
    subject_keyword: Optional[str] = None,
    mailbox: str = "INBOX",
    save_directory: str = "~/Desktop",
    format: str = "txt"
) -> str:
    """
    Export emails to files for backup or analysis.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        scope: Export scope: "single_email" (requires subject_keyword) or "entire_mailbox"
        subject_keyword: Keyword to find email (required for single_email)
        mailbox: Mailbox to export from (default: "INBOX")
        save_directory: Directory to save exports (default: "~/Desktop")
        format: Export format: "txt", "html" (default: "txt")

    Returns:
        Confirmation message with export location
    """

    # Expand home directory
    import os
    save_dir = os.path.expanduser(save_directory)

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

                set mailboxMessages to every message of targetMailbox
                set foundMessage to missing value

                -- Find the email
                repeat with aMessage in mailboxMessages
                    try
                        set messageSubject to subject of aMessage

                        if messageSubject contains "{safe_subject_keyword}" then
                            set foundMessage to aMessage
                            exit repeat
                        end if
                    end try
                end repeat

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

                set mailboxMessages to every message of targetMailbox
                set messageCount to count of mailboxMessages
                set exportCount to 0

                -- Create export directory
                set exportDir to "{safe_save_dir}/{safe_mailbox}_export"
                do shell script "mkdir -p " & quoted form of exportDir

                repeat with aMessage in mailboxMessages
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
                set outputText to outputText & "Total emails: " & messageCount & return
                set outputText to outputText & "Exported: " & exportCount & return
                set outputText to outputText & "Location: " & exportDir & return

            on error errMsg
                return "Error: " & errMsg
            end try

            return outputText
        end tell
        '''

    else:
        return f"Error: Invalid scope '{scope}'. Use: single_email, entire_mailbox"

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
        on lowercase(str)
            try
                set lowerStr to do shell script "echo " & quoted form of str & " | tr \'[:upper:]\' \'[:lower:]\'"
                return lowerStr
            on error
                return str
            end try
        end lowercase

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


def _get_recent_emails_structured(
    max_total: int = 20,
    max_per_account: int = 10
) -> List[Dict[str, Any]]:
    """
    Internal helper to get recent emails from all accounts as structured data.

    Returns list of dicts with keys:
    - subject: str
    - sender: str
    - date: str
    - is_read: bool
    - account: str
    - preview: str
    """
    script = f'''
    tell application "Mail"
        set allEmails to {{}}
        set allAccounts to every account

        repeat with anAccount in allAccounts
            set accountName to name of anAccount
            set emailCount to 0

            try
                -- Try to get inbox
                try
                    set inboxMailbox to mailbox "INBOX" of anAccount
                on error
                    set inboxMailbox to mailbox "Inbox" of anAccount
                end try

                set inboxMessages to every message of inboxMailbox

                repeat with aMessage in inboxMessages
                    if emailCount >= {max_per_account} then exit repeat

                    try
                        set messageSubject to subject of aMessage
                        set messageSender to sender of aMessage
                        set messageDate to date received of aMessage
                        set messageRead to read status of aMessage

                        -- Get preview
                        set messagePreview to ""
                        try
                            set msgContent to content of aMessage
                            if length of msgContent > 150 then
                                set messagePreview to text 1 thru 150 of msgContent
                            else
                                set messagePreview to msgContent
                            end if
                            -- Clean up preview
                            set AppleScript's text item delimiters to {{return, linefeed}}
                            set contentParts to text items of messagePreview
                            set AppleScript's text item delimiters to " "
                            set messagePreview to contentParts as string
                            set AppleScript's text item delimiters to ""
                        end try

                        -- Format as parseable string: SUBJECT|||SENDER|||DATE|||READ|||ACCOUNT|||PREVIEW
                        set emailRecord to messageSubject & "|||" & messageSender & "|||" & (messageDate as string) & "|||" & messageRead & "|||" & accountName & "|||" & messagePreview
                        set end of allEmails to emailRecord
                        set emailCount to emailCount + 1
                    end try
                end repeat
            end try
        end repeat

        -- Join all emails with newline
        set AppleScript's text item delimiters to linefeed
        set emailOutput to allEmails as string
        set AppleScript's text item delimiters to ""
        return emailOutput
    end tell
    '''

    result = run_applescript(script)

    # Parse the result into structured data
    emails = []
    if result:
        for line in result.split('\n'):
            if '|||' in line:
                # Use maxsplit=5 so preview field (last) can contain '|||'
                parts = line.split('|||', 5)
                if len(parts) >= 5:
                    emails.append({
                        'subject': parts[0].strip(),
                        'sender': parts[1].strip(),
                        'date': parts[2].strip(),
                        'is_read': parts[3].strip().lower() == 'true',
                        'account': parts[4].strip(),
                        'preview': parts[5].strip() if len(parts) > 5 else ''
                    })

    # Emails arrive in inbox order (newest first per account)
    # Limit to max_total
    return emails[:max_total]


@mcp.tool()
@inject_preferences
def inbox_dashboard() -> Any:
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

    Note: Requires mcp-ui-server package and a compatible MCP client.

    Returns:
        UIResource with uri "ui://apple-mail/inbox-dashboard" containing
        an interactive HTML dashboard, or error message if UI is unavailable.
    """
    if not UI_AVAILABLE:
        return "Error: UI module not available. Please install mcp-ui-server package."

    # Get unread counts per account
    accounts_data = get_unread_count()

    # Get recent emails across all accounts as structured data
    recent_emails = _get_recent_emails_structured(
        max_total=20,
        max_per_account=10
    )

    # Create and return the UI resource
    return create_inbox_dashboard_ui(
        accounts_data=accounts_data,
        recent_emails=recent_emails
    )


if __name__ == "__main__":
    # Run the MCP server
    mcp.run()

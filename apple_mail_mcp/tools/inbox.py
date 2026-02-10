"""Inbox tools: listing, counting, and overview."""

from typing import Optional, List, Dict, Any

from apple_mail_mcp.server import mcp
from apple_mail_mcp.core import inject_preferences, escape_applescript, run_applescript, inbox_mailbox_script


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
                {inbox_mailbox_script("inboxMailbox", "anAccount")}
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
    escaped_account = escape_applescript(account)

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
            {inbox_mailbox_script("inboxMailbox", "targetAccount")}
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
    escaped_account = escape_applescript(account) if account else None

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

    script = f'''
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
                {inbox_mailbox_script("inboxMailbox", "anAccount")}

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
        set allRecentMessages to {{}}

        repeat with anAccount in allAccounts
            set accountName to name of anAccount

            try
                {inbox_mailbox_script("inboxMailbox", "anAccount")}

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
                        set messageRecord to {{accountName:accountName, msgSubject:messageSubject, msgSender:messageSender, msgDate:messageDate, msgRead:messageRead}}
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

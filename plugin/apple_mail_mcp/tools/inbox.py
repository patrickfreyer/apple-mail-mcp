"""Inbox tools: listing, counting, and overview."""

import json
from typing import Optional, List, Dict, Any

from apple_mail_mcp.server import mcp
from apple_mail_mcp.core import (
    inject_preferences,
    escape_applescript,
    run_applescript,
    inbox_mailbox_script,
    content_preview_script,
)


def _parse_pipe_delimited_emails(raw: str) -> List[Dict[str, Any]]:
    """Parse '|||'-delimited AppleScript output into a list of email dicts."""
    emails = []
    if not raw:
        return emails
    for line in raw.split("\n"):
        if "|||" not in line:
            continue
        parts = line.split("|||")
        if len(parts) >= 5:
            emails.append(
                {
                    "subject": parts[0].strip(),
                    "sender": parts[1].strip(),
                    "date": parts[2].strip(),
                    "is_read": parts[3].strip().lower() == "true",
                    "account": parts[4].strip(),
                }
            )
    return emails


@mcp.tool()
@inject_preferences
def list_inbox_emails(
    account: Optional[str] = None,
    max_emails: int = 0,
    include_read: bool = True,
    include_content: bool = False,
    output_format: str = "text",
) -> str:
    """
    List all emails from inbox across all accounts or a specific account.

    Replaces the former get_recent_emails tool — use account + max_emails to
    get recent emails from a single account.

    Args:
        account: Optional account name to filter (e.g., "Gmail", "Work"). If None, shows all accounts.
        max_emails: Maximum number of emails to return per account (0 = all)
        include_read: Whether to include read emails (default: True)
        include_content: Whether to include a content preview for each email (slower, default: False)
        output_format: "text" (default, human-readable) or "json" (structured list of email dicts)

    Returns:
        Formatted list of emails with subject, sender, date, and read status
    """

    if output_format == "json":
        return _list_inbox_emails_json(account, max_emails, include_read, include_content)

    script = f"""
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

                                {content_preview_script(200) if include_content else ""}

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
    """

    result = run_applescript(script)
    return result


def _list_inbox_emails_json(
    account: Optional[str],
    max_emails: int,
    include_read: bool,
    include_content: bool = False,
) -> str:
    """Return inbox emails as a JSON string."""
    escaped_account = escape_applescript(account) if account else None
    account_filter = f'if accountName is "{escaped_account}" then' if account else ""
    account_filter_end = "end if" if account else ""

    script = f"""
    tell application "Mail"
        set resultLines to {{}}
        set allAccounts to every account
        repeat with anAccount in allAccounts
            set accountName to name of anAccount
            {account_filter}
            try
                {inbox_mailbox_script("inboxMailbox", "anAccount")}
                set inboxMessages to every message of inboxMailbox
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
                            set end of resultLines to messageSubject & "|||" & messageSender & "|||" & (messageDate as string) & "|||" & messageRead & "|||" & accountName
                        end if
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
    emails = _parse_pipe_delimited_emails(raw)
    return json.dumps(emails, indent=2)


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
def list_mailboxes(account: Optional[str] = None, include_counts: bool = True) -> str:
    """
    List all mailboxes (folders) for a specific account or all accounts.

    Args:
        account: Optional account name to filter (e.g., "Gmail", "Work"). If None, shows all accounts.
        include_counts: Whether to include message counts for each mailbox (default: True)

    Returns:
        Formatted list of mailboxes with optional message counts.
        For nested mailboxes, shows both indented format and path format (e.g., "Projects/Amplify Impact")
    """

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

    script = f"""
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
    """

    result = run_applescript(script)
    return result

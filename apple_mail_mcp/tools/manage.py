"""Management tools: moving, status updates, trash, and attachments."""

import os
from typing import Optional

from apple_mail_mcp.server import mcp
from apple_mail_mcp.core import inject_preferences, escape_applescript, run_applescript, inbox_mailbox_script


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
            {inbox_mailbox_script("inboxMailbox", "targetAccount")}
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

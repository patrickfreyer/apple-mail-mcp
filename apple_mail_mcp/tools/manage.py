"""Management tools: moving, status updates, trash, and attachments."""

import os
from typing import Optional, List

from apple_mail_mcp.server import mcp
from apple_mail_mcp.core import (
    contains_any_condition,
    equals_any_numeric_condition,
    inject_preferences,
    escape_applescript,
    normalize_message_ids,
    normalize_search_terms,
    run_applescript,
    inbox_mailbox_script,
    build_mailbox_ref,
    build_filter_condition,
)


@mcp.tool()
@inject_preferences
def move_email(
    account: str,
    subject_keyword: Optional[str],
    to_mailbox: str,
    from_mailbox: str = "INBOX",
    max_moves: int = 1,
    subject_keywords: Optional[List[str]] = None,
) -> str:
    """
    Move email(s) matching a subject keyword from one mailbox to another.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        subject_keyword: Optional keyword to search for in email subjects
        to_mailbox: Destination mailbox name. For nested mailboxes, use "/" separator (e.g., "Projects/Amplify Impact")
        from_mailbox: Source mailbox name (default: "INBOX")
        max_moves: Maximum number of emails to move (default: 1, safety limit)
        subject_keywords: Optional list of keywords to match in subjects; matches any keyword

    Returns:
        Confirmation message with details of moved emails
    """

    subject_terms = normalize_search_terms(subject_keyword, subject_keywords)
    if not subject_terms:
        return "Error: 'subject_keyword' or 'subject_keywords' is required"

    # Escape all user inputs for AppleScript
    safe_account = escape_applescript(account)
    safe_from_mailbox = escape_applescript(from_mailbox)
    safe_to_mailbox = escape_applescript(to_mailbox)
    subject_condition = contains_any_condition("subject", subject_terms)

    # Parse nested mailbox path
    mailbox_parts = to_mailbox.split("/")

    # Build the nested mailbox reference
    if len(mailbox_parts) > 1:
        # Nested mailbox
        dest_mailbox_script = f'mailbox "{escape_applescript(mailbox_parts[-1])}" of '
        for i in range(len(mailbox_parts) - 2, -1, -1):
            dest_mailbox_script += (
                f'mailbox "{escape_applescript(mailbox_parts[i])}" of '
            )
        dest_mailbox_script += "targetAccount"
    else:
        dest_mailbox_script = f'mailbox "{safe_to_mailbox}" of targetAccount'

    script = f'''
    tell application "Mail"
        with timeout of 300 seconds
            set outputText to "MOVING EMAILS" & return & return
            set movedCount to 0

            try
                set targetAccount to account "{safe_account}"
                -- Try to get source mailbox (handle both "INBOX"/"Inbox" variations)
                try
                    set sourceMailbox to mailbox "{safe_from_mailbox}" of targetAccount
                on error
                    if "{safe_from_mailbox}" is "INBOX" then
                        try
                            set sourceMailbox to mailbox "Inbox" of targetAccount
                        on error
                            set sourceMailbox to missing value
                            repeat with mb in mailboxes of targetAccount
                                set mbName to name of mb
                                if mbName is "Входящие" or mbName is "Posteingang" or mbName is "Boîte de réception" or mbName is "Bandeja de entrada" or mbName is "受信トレイ" or mbName is "收件箱" then
                                    set sourceMailbox to mb
                                    exit repeat
                                end if
                            end repeat
                            if sourceMailbox is missing value then
                                error "Could not find inbox mailbox"
                            end if
                        end try
                    else
                        error "Source mailbox not found"
                    end if
                end try

                -- Get destination mailbox (handles nested mailboxes)
                set destMailbox to {dest_mailbox_script}
                set matchingMessages to every message of sourceMailbox whose {subject_condition}
                set matchingCount to count of matchingMessages

                if matchingCount is 0 then
                    set targetMessages to {{}}
                else if matchingCount > {max_moves} then
                    set targetMessages to items 1 thru {max_moves} of matchingMessages
                else
                    set targetMessages to matchingMessages
                end if

                repeat with aMessage in targetMessages
                    try
                        set messageSubject to subject of aMessage
                        set messageSender to sender of aMessage
                        set messageDate to date received of aMessage

                        move aMessage to destMailbox
                        set movedCount to movedCount + 1

                        set outputText to outputText & "✓ Moved: " & messageSubject & return
                        set outputText to outputText & "  From: " & messageSender & return
                        set outputText to outputText & "  Date: " & (messageDate as string) & return
                        set outputText to outputText & "  {safe_from_mailbox} → {safe_to_mailbox}" & return & return
                    end try
                end repeat

                set outputText to outputText & "========================================" & return
                set outputText to outputText & "TOTAL MOVED: " & movedCount & " email(s)" & return
                set outputText to outputText & "========================================" & return

            on error errMsg
                return "Error: " & errMsg & return & "Please check that account and mailbox names are correct. For nested mailboxes, use '/' separator (e.g., 'Projects/Amplify Impact')."
            end try

            return outputText
        end timeout
    end tell
    '''

    result = run_applescript(script, timeout=300)
    return result


@mcp.tool()
@inject_preferences
def save_email_attachment(
    account: str, subject_keyword: str, attachment_name: str, save_path: str
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

    # Path validation: resolve to absolute path and enforce safety constraints
    resolved_path = os.path.realpath(expanded_path)
    home_dir = os.path.expanduser("~")

    # Must be under the user's home directory
    if not resolved_path.startswith(home_dir + os.sep) and resolved_path != home_dir:
        return f"Error: Save path must be under your home directory ({home_dir}). Got: {resolved_path}"

    # Block sensitive directories
    sensitive_dirs = [
        os.path.join(home_dir, ".ssh"),
        os.path.join(home_dir, ".gnupg"),
        os.path.join(home_dir, ".config"),
        os.path.join(home_dir, ".aws"),
        os.path.join(home_dir, ".claude"),
        os.path.join(home_dir, "Library", "LaunchAgents"),
        os.path.join(home_dir, "Library", "LaunchDaemons"),
        os.path.join(home_dir, "Library", "Keychains"),
    ]
    for sensitive_dir in sensitive_dirs:
        if (
            resolved_path.startswith(sensitive_dir + os.sep)
            or resolved_path == sensitive_dir
        ):
            return f"Error: Cannot save attachments to sensitive directory: {sensitive_dir}"

    expanded_path = resolved_path

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
    subject_keywords: Optional[List[str]] = None,
    sender: Optional[str] = None,
    mailbox: str = "INBOX",
    max_updates: int = 10,
    apply_to_all: bool = False,
) -> str:
    """
    Update email status - mark as read/unread or flag/unflag emails.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        action: Action to perform: "mark_read", "mark_unread", "flag", "unflag"
        subject_keyword: Optional keyword to filter emails by subject
        subject_keywords: Optional list of subject keywords; matches any keyword
        sender: Optional sender to filter emails by
        mailbox: Mailbox to search in (default: "INBOX")
        max_updates: Maximum number of emails to update (safety limit, default: 10)
        apply_to_all: Must be True to allow updates without subject_keyword or sender filter

    Returns:
        Confirmation message with details of updated emails
    """

    subject_terms = normalize_search_terms(subject_keyword, subject_keywords)

    # Safety check: require at least one filter or explicit apply_to_all
    if not subject_terms and not sender and not apply_to_all:
        return (
            "Error: No filter provided. Provide subject_keyword or sender to filter emails, "
            "or set apply_to_all=True to update all messages in the mailbox."
        )

    # Escape all user inputs for AppleScript
    safe_account = escape_applescript(account)

    # Build action and pre-filter so we skip no-op updates.
    if action == "mark_read":
        bulk_action_script = "set read status of targetMessages to true"
        single_action_script = "set read status of aMessage to true"
        conditions = ["read status is false"]
        action_label = "Marked as read"
    elif action == "mark_unread":
        bulk_action_script = "set read status of targetMessages to false"
        single_action_script = "set read status of aMessage to false"
        conditions = ["read status is true"]
        action_label = "Marked as unread"
    elif action == "flag":
        bulk_action_script = "set flagged status of targetMessages to true"
        single_action_script = "set flagged status of aMessage to true"
        conditions = ["flagged status is false"]
        action_label = "Flagged"
    elif action == "unflag":
        bulk_action_script = "set flagged status of targetMessages to false"
        single_action_script = "set flagged status of aMessage to false"
        conditions = ["flagged status is true"]
        action_label = "Unflagged"
    else:
        return f"Error: Invalid action '{action}'. Use: mark_read, mark_unread, flag, unflag"

    if subject_terms:
        conditions.append(contains_any_condition("subject", subject_terms))
    if sender:
        conditions.append(f'sender contains "{escape_applescript(sender)}"')

    search_condition = " and ".join(conditions)

    script = f'''
    tell application "Mail"
        with timeout of 300 seconds
            set outputText to "UPDATING EMAIL STATUS: {action_label}" & return & return
            set updateCount to 0

            try
                set targetAccount to account "{safe_account}"
                {build_mailbox_ref(mailbox, var_name="targetMailbox")}

                set matchingMessages to every message of targetMailbox whose {search_condition}
                set matchingCount to count of matchingMessages

                if matchingCount is 0 then
                    set targetMessages to {{}}
                else if matchingCount > {max_updates} then
                    set targetMessages to items 1 thru {max_updates} of matchingMessages
                else
                    set targetMessages to matchingMessages
                end if

                set updateCount to count of targetMessages

                if updateCount > 0 then
                    try
                        {bulk_action_script}
                    on error
                        repeat with aMessage in targetMessages
                            {single_action_script}
                        end repeat
                    end try

                    repeat with aMessage in targetMessages
                        try
                            set messageSubject to subject of aMessage
                            set messageSender to sender of aMessage
                            set messageDate to date received of aMessage

                            set outputText to outputText & "✓ {action_label}: " & messageSubject & return
                            set outputText to outputText & "   From: " & messageSender & return
                            set outputText to outputText & "   Date: " & (messageDate as string) & return & return
                        end try
                    end repeat
                end if

                set outputText to outputText & "========================================" & return
                set outputText to outputText & "TOTAL UPDATED: " & updateCount & " email(s)" & return
                set outputText to outputText & "========================================" & return

            on error errMsg
                return "Error: " & errMsg
            end try

            return outputText
        end timeout
    end tell
    '''

    result = run_applescript(script, timeout=300)
    return result


@mcp.tool()
@inject_preferences
def update_email_status_by_ids(
    account: str,
    mailbox: str,
    message_ids: List[str],
    action: str,
) -> str:
    """
    Update email status using explicit Mail message ids.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        mailbox: Mailbox containing the target messages
        message_ids: Exact Mail message ids returned by JSON search tools
        action: Action to perform: "mark_read", "mark_unread", "flag", "unflag"

    Returns:
        Confirmation message with details of updated emails
    """
    normalized_ids = normalize_message_ids(message_ids)
    if not normalized_ids:
        return "Error: 'message_ids' must contain one or more numeric Mail ids"

    safe_account = escape_applescript(account)
    safe_mailbox = escape_applescript(mailbox)

    if action == "mark_read":
        bulk_action_script = "set read status of targetMessages to true"
        single_action_script = "set read status of aMessage to true"
        action_label = "Marked as read"
    elif action == "mark_unread":
        bulk_action_script = "set read status of targetMessages to false"
        single_action_script = "set read status of aMessage to false"
        action_label = "Marked as unread"
    elif action == "flag":
        bulk_action_script = "set flagged status of targetMessages to true"
        single_action_script = "set flagged status of aMessage to true"
        action_label = "Flagged"
    elif action == "unflag":
        bulk_action_script = "set flagged status of targetMessages to false"
        single_action_script = "set flagged status of aMessage to false"
        action_label = "Unflagged"
    else:
        return f"Error: Invalid action '{action}'. Use: mark_read, mark_unread, flag, unflag"

    id_condition = equals_any_numeric_condition("id", normalized_ids)

    script = f'''
    tell application "Mail"
        with timeout of 300 seconds
            set outputText to "UPDATING EMAIL STATUS BY IDS: {action_label}" & return & return
            set updateCount to 0

            try
                set targetAccount to account "{safe_account}"
                try
                    set targetMailbox to mailbox "{safe_mailbox}" of targetAccount
                on error
                    if "{safe_mailbox}" is "INBOX" then
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
                        error "Mailbox not found: {safe_mailbox}"
                    end if
                end try

                set targetMessages to every message of targetMailbox whose {id_condition}
                set requestedCount to {len(normalized_ids)}

                if (count of targetMessages) > 0 then
                    try
                        {bulk_action_script}
                    on error
                        repeat with aMessage in targetMessages
                            {single_action_script}
                        end repeat
                    end try

                    repeat with aMessage in targetMessages
                        try
                            set messageSubject to subject of aMessage
                            set messageSender to sender of aMessage
                            set messageDate to date received of aMessage

                            set outputText to outputText & "✓ {action_label}: " & messageSubject & return
                            set outputText to outputText & "   From: " & messageSender & return
                            set outputText to outputText & "   Date: " & (messageDate as string) & return & return
                            set updateCount to updateCount + 1
                        end try
                    end repeat
                end if

                set outputText to outputText & "========================================" & return
                set outputText to outputText & "REQUESTED IDS: " & requestedCount & return
                set outputText to outputText & "TOTAL UPDATED: " & updateCount & " email(s)" & return
                set outputText to outputText & "========================================" & return

            on error errMsg
                return "Error: " & errMsg
            end try

            return outputText
        end timeout
    end tell
    '''

    result = run_applescript(script, timeout=300)
    return result


@mcp.tool()
@inject_preferences
def manage_trash(
    account: str,
    action: str,
    subject_keyword: Optional[str] = None,
    subject_keywords: Optional[List[str]] = None,
    sender: Optional[str] = None,
    mailbox: str = "INBOX",
    max_deletes: int = 5,
    confirm_empty: bool = False,
    apply_to_all: bool = False,
) -> str:
    """
    Manage trash operations - delete emails or empty trash.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        action: Action to perform: "move_to_trash", "delete_permanent", "empty_trash"
        subject_keyword: Optional keyword to filter emails (not used for empty_trash)
        subject_keywords: Optional list of subject keywords; matches any keyword
        sender: Optional sender to filter emails (not used for empty_trash)
        mailbox: Source mailbox (default: "INBOX", not used for empty_trash or delete_permanent)
        max_deletes: Maximum number of emails to delete (safety limit, default: 5)
        confirm_empty: Must be True to execute "empty_trash" action (safety confirmation)
        apply_to_all: Must be True to allow operations without subject_keyword or sender filter

    Returns:
        Confirmation message with details of deleted emails
    """

    # Escape all user inputs for AppleScript
    safe_account = escape_applescript(account)
    safe_mailbox = escape_applescript(mailbox)
    subject_terms = normalize_search_terms(subject_keyword, subject_keywords)

    if action == "empty_trash":
        if not confirm_empty:
            return (
                "Error: empty_trash permanently deletes ALL messages in the trash. "
                "Set confirm_empty=True to proceed."
            )
        script = f'''
        tell application "Mail"
            set outputText to "EMPTYING TRASH" & return & return

            try
                set targetAccount to account "{safe_account}"
                set trashMailbox to mailbox "Trash" of targetAccount
                set trashMessages to every message of trashMailbox
                set messageCount to count of trashMessages
                set deleteCount to 0

                -- Delete messages in trash, respecting max_deletes
                repeat with aMessage in trashMessages
                    if deleteCount >= {max_deletes} then exit repeat
                    delete aMessage
                    set deleteCount to deleteCount + 1
                end repeat

                set outputText to outputText & "✓ Emptied trash for account: {safe_account}" & return
                set outputText to outputText & "   Deleted " & deleteCount & " of " & messageCount & " message(s)" & return
                if deleteCount < messageCount then
                    set outputText to outputText & "   (limited by max_deletes=" & {max_deletes} & ")" & return
                end if

            on error errMsg
                return "Error: " & errMsg
            end try

            return outputText
        end tell
        '''
    elif action == "delete_permanent":
        # Safety check: require at least one filter or explicit apply_to_all
        if not subject_terms and not sender and not apply_to_all:
            return (
                "Error: No filter provided. Provide subject_keyword or sender to filter emails, "
                "or set apply_to_all=True to delete all matching messages."
            )

        # Build search condition with escaped inputs
        conditions = []
        if subject_terms:
            conditions.append(contains_any_condition("subject", subject_terms))
        if sender:
            conditions.append(f'sender contains "{escape_applescript(sender)}"')

        if conditions:
            matching_messages_script = f"set matchingMessages to every message of trashMailbox whose {' and '.join(conditions)}"
        else:
            matching_messages_script = (
                "set matchingMessages to every message of trashMailbox"
            )

        script = f'''
        tell application "Mail"
            with timeout of 300 seconds
                set outputText to "PERMANENTLY DELETING EMAILS" & return & return
                set deleteCount to 0

                try
                    set targetAccount to account "{safe_account}"
                    set trashMailbox to mailbox "Trash" of targetAccount
                    {matching_messages_script}
                    set matchingCount to count of matchingMessages

                    if matchingCount is 0 then
                        set targetMessages to {{}}
                    else if matchingCount > {max_deletes} then
                        set targetMessages to items 1 thru {max_deletes} of matchingMessages
                    else
                        set targetMessages to matchingMessages
                    end if

                    repeat with aMessage in targetMessages
                        try
                            set messageSubject to subject of aMessage
                            set messageSender to sender of aMessage

                            set outputText to outputText & "✓ Permanently deleted: " & messageSubject & return
                            set outputText to outputText & "   From: " & messageSender & return & return

                            delete aMessage
                            set deleteCount to deleteCount + 1
                        end try
                    end repeat

                    set outputText to outputText & "========================================" & return
                    set outputText to outputText & "TOTAL DELETED: " & deleteCount & " email(s)" & return
                    set outputText to outputText & "========================================" & return

                on error errMsg
                    return "Error: " & errMsg
                end try

                return outputText
            end timeout
        end tell
        '''
    else:  # move_to_trash
        # Safety check: require at least one filter or explicit apply_to_all
        if not subject_terms and not sender and not apply_to_all:
            return (
                "Error: No filter provided. Provide subject_keyword or sender to filter emails, "
                "or set apply_to_all=True to move all messages to trash."
            )

        # Build search condition with escaped inputs
        conditions = []
        if subject_terms:
            conditions.append(contains_any_condition("subject", subject_terms))
        if sender:
            conditions.append(f'sender contains "{escape_applescript(sender)}"')

        if conditions:
            matching_messages_script = f"set matchingMessages to every message of sourceMailbox whose {' and '.join(conditions)}"
        else:
            matching_messages_script = (
                "set matchingMessages to every message of sourceMailbox"
            )

        script = f'''
        tell application "Mail"
            with timeout of 300 seconds
                set outputText to "MOVING EMAILS TO TRASH" & return & return
                set deleteCount to 0

                try
                    set targetAccount to account "{safe_account}"
                    -- Get source mailbox
                    try
                        set sourceMailbox to mailbox "{safe_mailbox}" of targetAccount
                    on error
                        if "{safe_mailbox}" is "INBOX" then
                            try
                                set sourceMailbox to mailbox "Inbox" of targetAccount
                            on error
                                set sourceMailbox to missing value
                                repeat with mb in mailboxes of targetAccount
                                    set mbName to name of mb
                                    if mbName is "Входящие" or mbName is "Posteingang" or mbName is "Boîte de réception" or mbName is "Bandeja de entrada" or mbName is "受信トレイ" or mbName is "收件箱" then
                                        set sourceMailbox to mb
                                        exit repeat
                                    end if
                                end repeat
                                if sourceMailbox is missing value then
                                    error "Could not find inbox mailbox"
                                end if
                            end try
                        else
                            error "Mailbox not found: {safe_mailbox}"
                        end if
                    end try

                    -- Get trash mailbox
                    set trashMailbox to mailbox "Trash" of targetAccount
                    {matching_messages_script}
                    set matchingCount to count of matchingMessages

                    if matchingCount is 0 then
                        set targetMessages to {{}}
                    else if matchingCount > {max_deletes} then
                        set targetMessages to items 1 thru {max_deletes} of matchingMessages
                    else
                        set targetMessages to matchingMessages
                    end if

                    repeat with aMessage in targetMessages
                        try
                            set messageSubject to subject of aMessage
                            set messageSender to sender of aMessage
                            set messageDate to date received of aMessage

                            move aMessage to trashMailbox
                            set deleteCount to deleteCount + 1

                            set outputText to outputText & "✓ Moved to trash: " & messageSubject & return
                            set outputText to outputText & "   From: " & messageSender & return
                            set outputText to outputText & "   Date: " & (messageDate as string) & return & return
                        end try
                    end repeat

                    set outputText to outputText & "========================================" & return
                    set outputText to outputText & "TOTAL MOVED TO TRASH: " & deleteCount & " email(s)" & return
                    set outputText to outputText & "========================================" & return

                on error errMsg
                    return "Error: " & errMsg
                end try

                return outputText
            end timeout
        end tell
        '''

    result = run_applescript(script, timeout=300)
    return result


import re

# Characters that could break AppleScript strings or mailbox names
_INVALID_MAILBOX_CHARS = re.compile(r"[\\\"<>|?*:\x00-\x1f]")


@mcp.tool()
@inject_preferences
def create_mailbox(
    account: str,
    name: str,
    parent_mailbox: Optional[str] = None,
) -> str:
    """
    Create a new mailbox (folder) in the specified account.

    Supports nested paths via the parent_mailbox parameter (e.g.,
    parent_mailbox="Projects" + name="2024" creates Projects/2024).
    You can also pass a full slash-separated path as *name*
    (e.g., "Projects/2024/ClientName") and omit parent_mailbox.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        name: Name for the new mailbox. May contain "/" to create a
              nested path in one call (each segment is created if needed).
        parent_mailbox: Optional existing parent folder for nesting.

    Returns:
        Confirmation with the new mailbox path.
    """
    # Validate name
    if not name or not name.strip():
        return "Error: Mailbox name cannot be empty."

    # Split name into segments (support "A/B/C" shorthand)
    segments = [s.strip() for s in name.split("/") if s.strip()]
    if not segments:
        return "Error: Mailbox name cannot be empty."

    for seg in segments:
        if _INVALID_MAILBOX_CHARS.search(seg):
            return (
                f"Error: Invalid characters in mailbox name segment '{seg}'. "
                'Avoid \\ " < > | ? * : and control characters.'
            )

    safe_account = escape_applescript(account)

    # If parent_mailbox is given, prepend its segments
    if parent_mailbox:
        parent_segments = [s.strip() for s in parent_mailbox.split("/") if s.strip()]
        segments = parent_segments + segments

    # Build AppleScript to create each level one at a time
    create_blocks = ""
    for depth in range(len(segments)):
        seg = escape_applescript(segments[depth])
        if depth == 0:
            create_blocks += f'''
            try
                set parentRef to mailbox "{seg}" of targetAccount
            on error
                make new mailbox at targetAccount with properties {{name:"{seg}"}}
                set parentRef to mailbox "{seg}" of targetAccount
            end try
'''
        else:
            create_blocks += f'''
            try
                set parentRef to mailbox "{seg}" of parentRef
            on error
                make new mailbox at parentRef with properties {{name:"{seg}"}}
                set parentRef to mailbox "{seg}" of parentRef
            end try
'''

    full_path = "/".join(segments)
    safe_path = escape_applescript(full_path)

    script = f'''
    tell application "Mail"
        set outputText to "CREATING MAILBOX" & return & return

        try
            set targetAccount to account "{safe_account}"

            {create_blocks}

            set outputText to outputText & "OK Mailbox created successfully!" & return & return
            set outputText to outputText & "Account: {safe_account}" & return
            set outputText to outputText & "Path: {safe_path}" & return

        on error errMsg
            return "Error: " & errMsg
        end try

        return outputText
    end tell
    '''

    return run_applescript(script)


@mcp.tool()
@inject_preferences
def archive_emails(
    account: str,
    subject_keyword: Optional[str] = None,
    sender: Optional[str] = None,
    older_than_days: Optional[int] = None,
    only_read: bool = True,
    from_mailbox: str = "INBOX",
    archive_mailbox: str = "Archive",
    max_archive: int = 50,
    dry_run: bool = True,
) -> str:
    """
    Archive emails matching criteria by moving them to an Archive mailbox.

    Safety features:
    - At least one filter (subject_keyword, sender, or older_than_days) is required.
    - dry_run=True (default) previews what would be archived without moving.
    - only_read=True (default) skips unread emails.
    - max_archive caps the number of emails moved in one call.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        subject_keyword: Optional keyword to filter by subject
        sender: Optional sender to filter by
        older_than_days: Optional age filter - only archive emails older than N days
        only_read: If True (default), only archive emails that have been read
        from_mailbox: Source mailbox (default "INBOX")
        archive_mailbox: Destination mailbox (default "Archive")
        max_archive: Maximum emails to archive per call (default 50)
        dry_run: If True (default), only preview - do not actually move emails

    Returns:
        Summary of archived (or previewed) emails
    """
    # Safety: require at least one filter
    if not subject_keyword and not sender and not older_than_days:
        return (
            "Error: At least one filter is required (subject_keyword, sender, "
            "or older_than_days). This prevents accidentally archiving everything."
        )

    safe_account = escape_applescript(account)

    # Build conditions
    condition_str = build_filter_condition(subject=subject_keyword, sender=sender)
    if only_read:
        read_cond = "messageRead is true"
        condition_str = (
            f"{condition_str} and {read_cond}" if condition_str != "true" else read_cond
        )

    # Date filter
    date_setup = ""
    date_cond = ""
    if older_than_days and older_than_days > 0:
        date_setup = f"set cutoffDate to (current date) - ({older_than_days} * days)"
        date_cond = " and messageDate < cutoffDate"

    if dry_run:
        action_label = "DRY RUN - PREVIEW ARCHIVE"
        move_script = ""
        result_prefix = "Would archive"
    else:
        action_label = "ARCHIVING EMAILS"
        move_script = "move aMessage to destMailbox"
        result_prefix = "Archived"

    script = f'''
    tell application "Mail"
        set outputText to "{action_label}" & return & return
        set archiveCount to 0

        try
            set targetAccount to account "{safe_account}"

            -- Resolve source mailbox
            {build_mailbox_ref(from_mailbox, var_name="sourceMailbox")}

            -- Resolve or create archive mailbox
            try
                set destMailbox to mailbox "{escape_applescript(archive_mailbox)}" of targetAccount
            on error
                make new mailbox at targetAccount with properties {{name:"{escape_applescript(archive_mailbox)}"}}
                set destMailbox to mailbox "{escape_applescript(archive_mailbox)}" of targetAccount
            end try

            {date_setup}

            set sourceMessages to every message of sourceMailbox

            repeat with aMessage in sourceMessages
                if archiveCount >= {max_archive} then exit repeat

                try
                    set messageSubject to subject of aMessage
                    set messageSender to sender of aMessage
                    set messageDate to date received of aMessage
                    set messageRead to read status of aMessage

                    if {condition_str}{date_cond} then
                        {move_script}

                        set outputText to outputText & "{result_prefix}: " & messageSubject & return
                        set outputText to outputText & "   From: " & messageSender & return
                        set outputText to outputText & "   Date: " & (messageDate as string) & return & return

                        set archiveCount to archiveCount + 1
                    end if
                end try
            end repeat

            set outputText to outputText & "========================================" & return
            set outputText to outputText & "TOTAL: " & archiveCount & " email(s) {result_prefix.lower()}" & return
            set outputText to outputText & "========================================" & return

        on error errMsg
            return "Error: " & errMsg
        end try

        return outputText
    end tell
    '''

    return run_applescript(script)

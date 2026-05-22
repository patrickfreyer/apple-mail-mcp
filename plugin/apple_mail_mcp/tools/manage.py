"""Management tools: moving, status updates, trash, and attachments."""

import os
import re
from datetime import datetime, timedelta
from typing import Optional, List

from apple_mail_mcp import server as _server
from apple_mail_mcp.server import (
    mcp,
    WRITE_TOOL_ANNOTATIONS,
    IDEMPOTENT_WRITE_TOOL_ANNOTATIONS,
    DESTRUCTIVE_TOOL_ANNOTATIONS,
)
from apple_mail_mcp.core import (
    AppleScriptTimeout,
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
    validate_account_name,
)
from apple_mail_mcp.tools.search import _search_mail_records_sync as _search_mail_records


def _date_to_for_older_than(days: Optional[int]) -> Optional[str]:
    """Return YYYY-MM-DD cutoff date for older-than filters."""
    if days is None or days <= 0:
        return None
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")


def _date_from_for_recent_days(days: Optional[float]) -> Optional[str]:
    """Return YYYY-MM-DD cutoff date for recent-window filters."""
    if days is None or days <= 0:
        return None
    return (datetime.now() - timedelta(days=float(days))).strftime("%Y-%m-%d")


def _format_dry_run_records(title: str, records, result_prefix: str, limit: int) -> str:
    """Format structured search records as existing dry-run text."""
    lines = [title, ""]
    for record in records[:limit]:
        lines.append(f"{result_prefix}: {record.get('subject', '')}")
        lines.append(f"   From: {record.get('sender', '')}")
        lines.append(f"   Date: {record.get('received_date', '')}")
        lines.append("")
    lines.append("========================================")
    lines.append(f"TOTAL: {min(len(records), limit)} email(s) {result_prefix.lower()}")
    if len(records) > limit:
        lines.append("(limit reached)")
    lines.append("========================================")
    return "\n".join(lines)


# Characters that could break AppleScript strings or mailbox names
_INVALID_MAILBOX_CHARS = re.compile(r"[\\\"<>|?*:\x00-\x1f]")


@mcp.tool(annotations=WRITE_TOOL_ANNOTATIONS)
@inject_preferences
def move_email(
    account: Optional[str] = None,
    to_mailbox: str = "",
    message_ids: Optional[List[str]] = None,
    subject_keyword: Optional[str] = None,
    from_mailbox: str = "INBOX",
    max_moves: int = 50,
    subject_keywords: Optional[List[str]] = None,
    sender: Optional[str] = None,
    older_than_days: Optional[int] = None,
    dry_run: bool = False,
    only_read: bool = False,
    recent_days: float = 2.0,
    timeout: Optional[int] = None,
) -> str:
    """
    Move email(s) matching filters from one mailbox to another.

    Supports subject, sender, and date filters. Use dry_run=True to preview
    matches without moving. Set only_read=True to skip unread emails (useful
    for archiving). For archiving to "Archive", just set to_mailbox="Archive".

    When ``message_ids`` is provided, moves exact IDs and ignores keyword/sender
    filters. When ``account`` is None the configured ``DEFAULT_MAIL_ACCOUNT`` is used.

    Args:
        account: Account name (e.g., "Gmail", "Work"). Defaults to DEFAULT_MAIL_ACCOUNT.
        to_mailbox: Destination mailbox name. For nested mailboxes, use "/" separator (e.g., "Projects/Amplify Impact")
        message_ids: Optional list of exact Mail message ids for precise targeting
        subject_keyword: Optional keyword to search for in email subjects
        from_mailbox: Source mailbox name (default: "INBOX")
        max_moves: Maximum number of emails to move (default: 50, safety limit)
        subject_keywords: Optional list of keywords to match in subjects; matches any keyword
        sender: Optional sender to filter emails by
        older_than_days: Optional age filter - only move emails older than N days
        dry_run: If True, preview what would be moved without acting (default: False)
        only_read: If True, only move emails that have been read (default: False)
        recent_days: Recent window to search by default (default: 2.0, 0 = unbounded).
            Ignored when older_than_days is set or message_ids is provided.
        timeout: Optional AppleScript timeout in seconds (default: 300s).

    Returns:
        Confirmation message with details of moved emails
    """
    if account is None:
        account = _server.DEFAULT_MAIL_ACCOUNT
    if not account:
        return "Error: account is required (and no DEFAULT_MAIL_ACCOUNT configured)."

    validation_timeout = 30 if timeout is None else min(timeout, 30)
    account_err = validate_account_name(account, timeout=validation_timeout)
    if account_err:
        return account_err

    if not to_mailbox:
        return "Error: to_mailbox is required."

    safe_account = escape_applescript(account)
    safe_from = escape_applescript(from_mailbox)
    safe_to = escape_applescript(to_mailbox)
    effective_timeout = timeout if timeout is not None else 300

    mailbox_parts = to_mailbox.split("/")
    if len(mailbox_parts) > 1:
        dest_ref = f'mailbox "{escape_applescript(mailbox_parts[-1])}" of '
        for i in range(len(mailbox_parts) - 2, -1, -1):
            dest_ref += f'mailbox "{escape_applescript(mailbox_parts[i])}" of '
        dest_ref += "targetAccount"
    else:
        dest_ref = f'mailbox "{safe_to}" of targetAccount'

    if message_ids is not None:
        normalized_ids = normalize_message_ids(message_ids)
        if not normalized_ids:
            return "Error: 'message_ids' must contain one or more numeric Mail ids"

        id_condition = equals_any_numeric_condition("id", normalized_ids)
        mode_label = (
            f"DRY RUN - PREVIEW MOVE BY IDS: {safe_from} -> {safe_to}"
            if dry_run
            else f"MOVING EMAILS BY IDS: {safe_from} -> {safe_to}"
        )
        move_action = "" if dry_run else "move aMessage to destMailbox"
        result_prefix = "Would move" if dry_run else "Moved"
        dest_setup = "" if dry_run else f"""
                set destMailbox to {dest_ref}"""

        script = f'''
    tell application "Mail"
        with timeout of {effective_timeout} seconds
            set outputText to "{mode_label}" & return & return
            set moveCount to 0

            try
                set targetAccount to account "{safe_account}"
                {build_mailbox_ref(from_mailbox, var_name="sourceMailbox")}
                {dest_setup}

                set matchingMessages to every message of sourceMailbox whose {id_condition}
                if (count of matchingMessages) > {max_moves} then
                    set matchingMessages to items 1 thru {max_moves} of matchingMessages
                end if

                repeat with aMessage in matchingMessages
                    try
                        set messageSubject to subject of aMessage
                        set messageSender to sender of aMessage
                        set messageDate to date received of aMessage

                        {move_action}

                        set outputText to outputText & "{result_prefix}: " & messageSubject & return
                        set outputText to outputText & "   From: " & messageSender & return
                        set outputText to outputText & "   Date: " & (messageDate as string) & return & return

                        set moveCount to moveCount + 1
                    end try
                end repeat

                set outputText to outputText & "========================================" & return
                set outputText to outputText & "REQUESTED IDS: {len(normalized_ids)}" & return
                set outputText to outputText & "TOTAL: " & moveCount & " email(s) {result_prefix.lower()}" & return
                if moveCount >= {max_moves} then
                    set outputText to outputText & "(max_moves limit reached)" & return
                end if
                set outputText to outputText & "========================================" & return

            on error errMsg
                return "Error: " & errMsg & return & "Check that account and mailbox names are correct. For nested mailboxes, use '/' separator."
            end try

            return outputText
        end timeout
    end tell
    '''

        try:
            return run_applescript(script, timeout=effective_timeout)
        except AppleScriptTimeout:
            return (
                f"Error: move_email timed out after {effective_timeout}s on account "
                f"'{account}'. Retry with a larger timeout or tighter filters."
            )

    subject_terms = normalize_search_terms(subject_keyword, subject_keywords)
    if not subject_terms and not sender and not older_than_days:
        return (
            "Error: At least one filter is required (subject_keyword, sender, "
            "or older_than_days). This prevents accidentally moving everything."
        )

    # Build whose-clause conditions (pushed down into AppleScript so we
    # never enumerate `every message of sourceMailbox` on large mailboxes).
    whose_conditions: List[str] = []
    if subject_terms:
        whose_conditions.append(contains_any_condition("subject", subject_terms))
    if sender:
        whose_conditions.append(f'sender contains "{escape_applescript(sender)}"')
    if only_read:
        whose_conditions.append("read status is true")

    date_setup = ""
    effective_recent_days = recent_days if older_than_days is None else 0
    if older_than_days and older_than_days > 0:
        date_setup = f"set cutoffDate to (current date) - ({older_than_days} * days)"
        whose_conditions.append("date received < cutoffDate")
    elif effective_recent_days and effective_recent_days > 0:
        date_setup = (
            f"set recentCutoffDate to (current date) - ({float(effective_recent_days)} * days)"
        )
        whose_conditions.append("date received >= recentCutoffDate")

    whose_clause = " and ".join(whose_conditions)

    # Build nested mailbox reference for destination
    mailbox_parts = to_mailbox.split("/")
    if len(mailbox_parts) > 1:
        dest_ref = f'mailbox "{escape_applescript(mailbox_parts[-1])}" of '
        for i in range(len(mailbox_parts) - 2, -1, -1):
            dest_ref += f'mailbox "{escape_applescript(mailbox_parts[i])}" of '
        dest_ref += "targetAccount"
    else:
        dest_ref = f'mailbox "{safe_to}" of targetAccount'

    if dry_run:
        try:
            records = _search_mail_records(
                account=account,
                mailbox=from_mailbox,
                subject_terms=subject_terms or None,
                sender=sender,
                read_status="read" if only_read else "all",
                date_from=_date_from_for_recent_days(effective_recent_days),
                date_to=_date_to_for_older_than(older_than_days),
                include_content=False,
                offset=0,
                limit=max_moves + 1,
                timeout=timeout if timeout is not None else 45,
            )
        except AppleScriptTimeout:
            return (
                f"Error: move_email dry-run timed out on account '{account}'. "
                "Retry with a larger timeout or tighter filters."
            )
        return _format_dry_run_records(
            f"DRY RUN - PREVIEW MOVE: {from_mailbox} -> {to_mailbox}",
            records,
            "Would move",
            max_moves,
        )
    else:
        mode_label = "MOVING EMAILS"
        move_action = "move aMessage to destMailbox"
        result_prefix = "Moved"

    dest_setup = "" if dry_run else f"""
            set destMailbox to {dest_ref}"""

    effective_timeout = timeout if timeout is not None else 300

    script = f'''
    tell application "Mail"
        with timeout of {effective_timeout} seconds
            set outputText to "{mode_label}: {safe_from} -> {safe_to}" & return & return
            set moveCount to 0

            try
                set targetAccount to account "{safe_account}"
                {build_mailbox_ref(from_mailbox, var_name="sourceMailbox")}
                {dest_setup}
                {date_setup}

                set matchingMessages to (every message of sourceMailbox whose {whose_clause})
                if (count of matchingMessages) > {max_moves} then
                    set matchingMessages to items 1 thru {max_moves} of matchingMessages
                end if

                repeat with aMessage in matchingMessages
                    try
                        set messageSubject to subject of aMessage
                        set messageSender to sender of aMessage
                        set messageDate to date received of aMessage

                        {move_action}

                        set outputText to outputText & "{result_prefix}: " & messageSubject & return
                        set outputText to outputText & "   From: " & messageSender & return
                        set outputText to outputText & "   Date: " & (messageDate as string) & return & return

                        set moveCount to moveCount + 1
                    end try
                end repeat

                set outputText to outputText & "========================================" & return
                set outputText to outputText & "TOTAL: " & moveCount & " email(s) {result_prefix.lower()}" & return
                if moveCount >= {max_moves} then
                    set outputText to outputText & "(max_moves limit reached)" & return
                end if
                set outputText to outputText & "========================================" & return

            on error errMsg
                return "Error: " & errMsg & return & "Check that account and mailbox names are correct. For nested mailboxes, use '/' separator."
            end try

            return outputText
        end timeout
    end tell
    '''

    try:
        return run_applescript(script, timeout=effective_timeout)
    except AppleScriptTimeout:
        return (
            f"Error: move_email timed out after {effective_timeout}s on account "
            f"'{account}'. Retry with a larger timeout or tighter filters."
        )


@mcp.tool(annotations=WRITE_TOOL_ANNOTATIONS)
@inject_preferences
def save_email_attachment(
    account: Optional[str] = None,
    subject_keyword: str = "",
    attachment_name: str = "",
    save_path: str = "",
    message_ids: Optional[List[str]] = None,
    timeout: Optional[int] = None,
) -> str:
    """
    Save a specific attachment from an email to disk.

    When ``message_ids`` is provided, locates the message by exact ID and
    ignores ``subject_keyword``.

    Args:
        account: Account name (e.g., "Gmail", "Work"). Defaults to DEFAULT_MAIL_ACCOUNT.
        subject_keyword: Keyword to search for in email subjects (omit when message_ids is set)
        attachment_name: Name of the attachment to save
        save_path: Full path where to save the attachment
        message_ids: Optional list of exact Mail message ids for precise targeting
        timeout: Optional AppleScript timeout in seconds (default: 120s).

    Returns:
        Confirmation message with save location
    """
    if account is None:
        account = _server.DEFAULT_MAIL_ACCOUNT
    if not account:
        return "Error: account is required (and no DEFAULT_MAIL_ACCOUNT configured)."

    account_err = validate_account_name(
        account, timeout=30 if timeout is None else min(timeout, 30)
    )
    if account_err:
        return account_err

    if message_ids is None and (not subject_keyword or not attachment_name or not save_path):
        return "Error: subject_keyword, attachment_name, and save_path are required."
    if not attachment_name or not save_path:
        return "Error: attachment_name and save_path are required."

    if message_ids is not None:
        normalized_ids = normalize_message_ids(message_ids)
        if not normalized_ids:
            return "Error: 'message_ids' must contain one or more numeric Mail ids"
        message_filter_script = (
            f"set inboxMessages to every message of inboxMailbox whose "
            f"{equals_any_numeric_condition('id', normalized_ids)}"
        )
        not_found_detail = f"Message ids: {', '.join(normalized_ids)}"
    else:
        message_filter_script = (
            f'set inboxMessages to (every message of inboxMailbox whose subject contains "{escape_applescript(subject_keyword)}")'
        )
        not_found_detail = f"Email keyword: {escape_applescript(subject_keyword)}"

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
    escaped_keyword = escape_applescript(subject_keyword) if subject_keyword else ""
    escaped_attachment = escape_applescript(attachment_name)
    escaped_path = escape_applescript(expanded_path)

    # Cap candidate set for subject search only — ID lookup is exact.
    SCAN_CAP = 200
    cap_script = ""
    if message_ids is None:
        cap_script = f"""
            if (count of inboxMessages) > {SCAN_CAP} then
                set inboxMessages to items 1 thru {SCAN_CAP} of inboxMessages
            end if"""

    script = f'''
    tell application "Mail"
        set outputText to ""

        try
            set targetAccount to account "{escaped_account}"
            {inbox_mailbox_script("inboxMailbox", "targetAccount")}
            {message_filter_script}
            {cap_script}
            set foundAttachment to false

            repeat with aMessage in inboxMessages
                try
                    set messageSubject to subject of aMessage
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
                end try
            end repeat

            if not foundAttachment then
                set outputText to "⚠ Attachment not found" & return
                set outputText to outputText & "{not_found_detail}" & return
                set outputText to outputText & "Attachment name: {escaped_attachment}" & return
            end if

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
        return (
            f"Error: AppleScript timed out while saving attachment from account "
            f"{account!r}. Try again or pass a larger `timeout`."
        )
    return result


@mcp.tool(annotations=IDEMPOTENT_WRITE_TOOL_ANNOTATIONS)
@inject_preferences
def update_email_status(
    account: Optional[str] = None,
    action: str = "mark_read",
    subject_keyword: Optional[str] = None,
    subject_keywords: Optional[List[str]] = None,
    sender: Optional[str] = None,
    mailbox: str = "INBOX",
    max_updates: int = 10,
    apply_to_all: bool = False,
    message_ids: Optional[List[str]] = None,
    older_than_days: Optional[int] = None,
    timeout: Optional[int] = None,
) -> str:
    """
    Update email status - mark as read/unread or flag/unflag emails.

    When message_ids is provided, uses exact ID matching (ignores other filters).
    Otherwise filters by subject, sender, and/or age.

    When ``account`` is None the configured ``DEFAULT_MAIL_ACCOUNT`` is used.

    Args:
        account: Account name (e.g., "Gmail", "Work"). Defaults to DEFAULT_MAIL_ACCOUNT.
        action: Action to perform: "mark_read", "mark_unread", "flag", "unflag"
        subject_keyword: Optional keyword to filter emails by subject
        subject_keywords: Optional list of subject keywords; matches any keyword
        sender: Optional sender to filter emails by
        mailbox: Mailbox to search in (default: "INBOX")
        max_updates: Maximum number of emails to update (safety limit, default: 10)
        apply_to_all: Must be True to allow updates without any filter
        message_ids: Optional list of exact Mail message ids for precise targeting
        older_than_days: Optional age filter - only update emails older than N days
        timeout: Optional AppleScript timeout in seconds (default: 300s).

    Returns:
        Confirmation message with details of updated emails
    """
    if account is None:
        account = _server.DEFAULT_MAIL_ACCOUNT
    if not account:
        return "Error: account is required (and no DEFAULT_MAIL_ACCOUNT configured)."

    validation_timeout = 30 if timeout is None else min(timeout, 30)
    account_err = validate_account_name(account, timeout=validation_timeout)
    if account_err:
        return account_err

    safe_account = escape_applescript(account)
    effective_timeout = timeout if timeout is not None else 300

    # Build action scripts
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

    # --- ID-based path (fast, ignores other filters) ---
    if message_ids is not None:
        normalized_ids = normalize_message_ids(message_ids)
        if not normalized_ids:
            return "Error: 'message_ids' must contain one or more numeric Mail ids"

        id_condition = equals_any_numeric_condition("id", normalized_ids)

        script = f'''
        tell application "Mail"
            with timeout of {effective_timeout} seconds
                set outputText to "UPDATING EMAIL STATUS BY IDS: {action_label}" & return & return
                set updateCount to 0

                try
                    set targetAccount to account "{safe_account}"
                    {build_mailbox_ref(mailbox, var_name="targetMailbox")}

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

                                set outputText to outputText & "- {action_label}: " & messageSubject & return
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

        try:
            return run_applescript(script, timeout=effective_timeout)
        except AppleScriptTimeout:
            return (
                f"Error: update_email_status timed out after {effective_timeout}s "
                f"on account '{account}'."
            )

    # --- Filter-based path ---
    subject_terms = normalize_search_terms(subject_keyword, subject_keywords)

    # Safety check: require at least one filter or explicit apply_to_all
    has_filter = bool(subject_terms) or bool(sender) or (
        older_than_days is not None and older_than_days > 0
    )
    if not has_filter and not apply_to_all:
        return (
            "Error: No filter provided. Provide subject_keyword, sender, or older_than_days "
            "to filter emails, or set apply_to_all=True to update all messages in the mailbox."
        )

    # Pre-filter conditions (skip no-op updates)
    if action == "mark_read":
        conditions = ["read status is false"]
    elif action == "mark_unread":
        conditions = ["read status is true"]
    elif action == "flag":
        conditions = ["flagged status is false"]
    else:  # unflag
        conditions = ["flagged status is true"]

    if subject_terms:
        conditions.append(contains_any_condition("subject", subject_terms))
    if sender:
        conditions.append(f'sender contains "{escape_applescript(sender)}"')

    # Date filter — pushed into the whose clause so AppleScript filters in
    # one pass instead of enumerating + Python-side checking.
    date_setup = ""
    if older_than_days and older_than_days > 0:
        date_setup = f"set cutoffDate to (current date) - ({older_than_days} * days)"
        conditions.append("date received < cutoffDate")

    search_condition = " and ".join(conditions)

    script = f'''
    tell application "Mail"
        with timeout of {effective_timeout} seconds
            set outputText to "UPDATING EMAIL STATUS: {action_label}" & return & return
            set updateCount to 0

            try
                set targetAccount to account "{safe_account}"
                {build_mailbox_ref(mailbox, var_name="targetMailbox")}
                {date_setup}

                set matchingMessages to every message of targetMailbox whose {search_condition}
                set matchingCount to count of matchingMessages

                if matchingCount is 0 then
                    set targetMessages to {{}}
                else if matchingCount > {max_updates} then
                    set targetMessages to items 1 thru {max_updates} of matchingMessages
                else
                    set targetMessages to matchingMessages
                end if

                repeat with aMessage in targetMessages
                    try
                        {single_action_script}
                        set messageSubject to subject of aMessage
                        set messageSender to sender of aMessage
                        set messageDate to date received of aMessage

                        set outputText to outputText & "- {action_label}: " & messageSubject & return
                        set outputText to outputText & "   From: " & messageSender & return
                        set outputText to outputText & "   Date: " & (messageDate as string) & return & return
                        set updateCount to updateCount + 1
                    end try
                end repeat

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

    try:
        return run_applescript(script, timeout=effective_timeout)
    except AppleScriptTimeout:
        return (
            f"Error: update_email_status timed out after {effective_timeout}s "
            f"on account '{account}'."
        )


@mcp.tool(annotations=DESTRUCTIVE_TOOL_ANNOTATIONS)
@inject_preferences
def manage_trash(
    account: Optional[str] = None,
    action: str = "move_to_trash",
    message_ids: Optional[List[str]] = None,
    subject_keyword: Optional[str] = None,
    subject_keywords: Optional[List[str]] = None,
    sender: Optional[str] = None,
    mailbox: str = "INBOX",
    max_deletes: int = 5,
    confirm_empty: bool = False,
    apply_to_all: bool = False,
    older_than_days: Optional[int] = None,
    dry_run: bool = True,
    recent_days: float = 2.0,
    timeout: Optional[int] = None,
) -> str:
    """
    Manage trash operations - delete emails or empty trash.

    When dry_run=True (default) and action is "move_to_trash", previews what
    would be deleted without acting. Set dry_run=False to actually move to trash.

    When ``message_ids`` is provided for ``move_to_trash`` or ``delete_permanent``,
    targets exact IDs and ignores keyword/sender filters.

    When ``account`` is None the configured ``DEFAULT_MAIL_ACCOUNT`` is used.

    Args:
        account: Account name (e.g., "Gmail", "Work"). Defaults to DEFAULT_MAIL_ACCOUNT.
        action: Action to perform: "move_to_trash", "delete_permanent", "empty_trash"
        message_ids: Optional list of exact Mail message ids for precise targeting
        subject_keyword: Optional keyword to filter emails (not used for empty_trash)
        subject_keywords: Optional list of subject keywords; matches any keyword
        sender: Optional sender to filter emails (not used for empty_trash)
        mailbox: Source mailbox (default: "INBOX", not used for empty_trash or delete_permanent)
        max_deletes: Maximum number of emails to delete (safety limit, default: 5)
        confirm_empty: Must be True to execute "empty_trash" action (safety confirmation)
        apply_to_all: Must be True to allow operations without subject_keyword or sender filter
        older_than_days: Optional age filter - only affect emails older than N days
        dry_run: If True (default), preview what would be affected without acting
        recent_days: Recent window to search by default (default: 2.0, 0 = unbounded).
            Ignored when older_than_days is set or message_ids is provided.
        timeout: Optional AppleScript timeout in seconds (default: 300s).

    Returns:
        Confirmation message with details of deleted emails
    """
    if account is None:
        account = _server.DEFAULT_MAIL_ACCOUNT
    if not account:
        return "Error: account is required (and no DEFAULT_MAIL_ACCOUNT configured)."

    validation_timeout = 30 if timeout is None else min(timeout, 30)
    account_err = validate_account_name(account, timeout=validation_timeout)
    if account_err:
        return account_err

    # Escape all user inputs for AppleScript
    safe_account = escape_applescript(account)
    safe_mailbox = escape_applescript(mailbox)
    subject_terms = normalize_search_terms(subject_keyword, subject_keywords)
    effective_timeout = timeout if timeout is not None else 300
    effective_recent_days = recent_days if older_than_days is None else 0

    if message_ids is not None:
        if action == "empty_trash":
            return "Error: message_ids cannot be used with empty_trash"

        normalized_ids = normalize_message_ids(message_ids)
        if not normalized_ids:
            return "Error: 'message_ids' must contain one or more numeric Mail ids"

        id_condition = equals_any_numeric_condition("id", normalized_ids)

        if action == "move_to_trash":
            mode_label = (
                "DRY RUN - PREVIEW TRASH BY IDS"
                if dry_run
                else "MOVING EMAILS TO TRASH BY IDS"
            )
            move_script = "" if dry_run else "move aMessage to trashMailbox"
            result_verb = "Would trash" if dry_run else "Moved to trash"
            trash_setup = "" if dry_run else """
                    set trashMailbox to mailbox "Trash" of targetAccount"""
            mailbox_ref = build_mailbox_ref(mailbox, var_name="sourceMailbox")
        elif action == "delete_permanent":
            mode_label = "PERMANENTLY DELETING EMAILS BY IDS"
            move_script = "delete aMessage"
            result_verb = "Permanently deleted"
            trash_setup = ""
            mailbox_ref = 'set sourceMailbox to mailbox "Trash" of targetAccount'
        else:
            return (
                f"Error: Invalid action '{action}'. Use: move_to_trash, "
                "delete_permanent, empty_trash"
            )

        script = f'''
        tell application "Mail"
            with timeout of {effective_timeout} seconds
                set outputText to "{mode_label}" & return & return
                set deleteCount to 0

                try
                    set targetAccount to account "{safe_account}"
                    {mailbox_ref}
                    {trash_setup}

                    set matchingMessages to every message of sourceMailbox whose {id_condition}
                    if (count of matchingMessages) > {max_deletes} then
                        set matchingMessages to items 1 thru {max_deletes} of matchingMessages
                    end if

                    repeat with aMessage in matchingMessages
                        try
                            set messageSubject to subject of aMessage
                            set messageSender to sender of aMessage
                            set messageDate to date received of aMessage

                            {move_script}

                            set outputText to outputText & "{result_verb}: " & messageSubject & return
                            set outputText to outputText & "   From: " & messageSender & return
                            set outputText to outputText & "   Date: " & (messageDate as string) & return & return
                            set deleteCount to deleteCount + 1
                        end try
                    end repeat

                    set outputText to outputText & "========================================" & return
                    set outputText to outputText & "REQUESTED IDS: {len(normalized_ids)}" & return
                    set outputText to outputText & "TOTAL: " & deleteCount & " email(s) {result_verb.lower()}" & return
                    set outputText to outputText & "========================================" & return

                on error errMsg
                    return "Error: " & errMsg
                end try

                return outputText
            end timeout
        end tell
        '''

        try:
            return run_applescript(script, timeout=effective_timeout)
        except AppleScriptTimeout:
            return (
                f"Error: manage_trash timed out after {effective_timeout}s on "
                f"account '{account}'."
            )

    if action == "empty_trash":
        if not confirm_empty:
            return (
                "Error: empty_trash permanently deletes ALL messages in the trash. "
                "Set confirm_empty=True to proceed."
            )
        script = f'''
        tell application "Mail"
            with timeout of {effective_timeout} seconds
                set outputText to "EMPTYING TRASH" & return & return

                try
                    set targetAccount to account "{safe_account}"
                    set trashMailbox to mailbox "Trash" of targetAccount
                    set messageCount to count of messages of trashMailbox
                    set deleteCount to 0

                    if messageCount > {max_deletes} then
                        set trashMessages to messages 1 thru {max_deletes} of trashMailbox
                    else
                        set trashMessages to messages of trashMailbox
                    end if

                    repeat with aMessage in trashMessages
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
            end timeout
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
            matching_messages_script = (
                f"set matchingMessages to every message of trashMailbox whose {' and '.join(conditions)}"
            )
        else:
            # No filters (apply_to_all path) — cap before binding so we don't
            # materialize the full trash mailbox.
            matching_messages_script = (
                f"if (count of messages of trashMailbox) > {max_deletes} then\n"
                f"                        set matchingMessages to messages 1 thru {max_deletes} of trashMailbox\n"
                f"                    else\n"
                f"                        set matchingMessages to messages of trashMailbox\n"
                f"                    end if"
            )

        script = f'''
        tell application "Mail"
            with timeout of {effective_timeout} seconds
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
        has_filter = bool(subject_terms) or bool(sender) or (
            older_than_days is not None and older_than_days > 0
        )
        if not has_filter and not apply_to_all:
            return (
                "Error: No filter provided. Provide subject_keyword, sender, or older_than_days "
                "to filter emails, or set apply_to_all=True to move all messages to trash."
            )

        # Date filter — push into whose clause so AppleScript filters in a
        # single pass instead of enumerating + Python-side date checks.
        date_setup = ""
        conditions: List[str] = []
        if subject_terms:
            conditions.append(contains_any_condition("subject", subject_terms))
        if sender:
            conditions.append(f'sender contains "{escape_applescript(sender)}"')
        if older_than_days and older_than_days > 0:
            date_setup = f"set cutoffDate to (current date) - ({older_than_days} * days)"
            conditions.append("date received < cutoffDate")
        elif effective_recent_days and effective_recent_days > 0:
            date_setup = (
                f"set recentCutoffDate to (current date) - ({float(effective_recent_days)} * days)"
            )
            conditions.append("date received >= recentCutoffDate")

        if conditions:
            matching_messages_script = (
                f"set matchingMessages to every message of sourceMailbox whose {' and '.join(conditions)}"
            )
        else:
            # No filters (apply_to_all path) — cap before binding so we don't
            # materialize the full mailbox.
            matching_messages_script = (
                f"if (count of messages of sourceMailbox) > {max_deletes} then\n"
                f"                        set matchingMessages to messages 1 thru {max_deletes} of sourceMailbox\n"
                f"                    else\n"
                f"                        set matchingMessages to messages of sourceMailbox\n"
                f"                    end if"
            )

        if dry_run:
            try:
                records = _search_mail_records(
                    account=account,
                    mailbox=mailbox,
                    subject_terms=subject_terms or None,
                    sender=sender,
                    date_from=_date_from_for_recent_days(effective_recent_days),
                    date_to=_date_to_for_older_than(older_than_days),
                    include_content=False,
                    offset=0,
                    limit=max_deletes + 1,
                    timeout=timeout if timeout is not None else 45,
                )
            except AppleScriptTimeout:
                return (
                    f"Error: manage_trash dry-run timed out on account '{account}'. "
                    "Retry with a larger timeout or tighter filters."
                )
            return _format_dry_run_records(
                "DRY RUN - PREVIEW TRASH",
                records,
                "Would trash",
                max_deletes,
            )
        else:
            mode_label = "MOVING EMAILS TO TRASH"
            move_script = "move aMessage to trashMailbox"
            result_verb = "Moved to trash"

        trash_setup = "" if dry_run else """
                    set trashMailbox to mailbox "Trash" of targetAccount"""

        script = f'''
        tell application "Mail"
            with timeout of {effective_timeout} seconds
                set outputText to "{mode_label}" & return & return
                set deleteCount to 0

                try
                    set targetAccount to account "{safe_account}"
                    {build_mailbox_ref(mailbox, var_name="sourceMailbox")}
                    {trash_setup}
                    {date_setup}

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

                            {move_script}
                            set deleteCount to deleteCount + 1

                            set outputText to outputText & "{result_verb}: " & messageSubject & return
                            set outputText to outputText & "   From: " & messageSender & return
                            set outputText to outputText & "   Date: " & (messageDate as string) & return & return
                        end try
                    end repeat

                    set outputText to outputText & "========================================" & return
                    set outputText to outputText & "TOTAL: " & deleteCount & " email(s) {result_verb.lower()}" & return
                    set outputText to outputText & "========================================" & return

                on error errMsg
                    return "Error: " & errMsg
                end try

                return outputText
            end timeout
        end tell
        '''

    try:
        return run_applescript(script, timeout=effective_timeout)
    except AppleScriptTimeout:
        return (
            f"Error: manage_trash timed out after {effective_timeout}s on "
            f"account '{account}'."
        )


@mcp.tool(annotations=WRITE_TOOL_ANNOTATIONS)
@inject_preferences
def create_mailbox(
    account: Optional[str] = None,
    name: str = "",
    parent_mailbox: Optional[str] = None,
) -> str:
    """
    Create a new mailbox (folder) in the specified account.

    Supports nested paths via the parent_mailbox parameter (e.g.,
    parent_mailbox="Projects" + name="2024" creates Projects/2024).
    You can also pass a full slash-separated path as *name*
    (e.g., "Projects/2024/ClientName") and omit parent_mailbox.

    When ``account`` is None the configured ``DEFAULT_MAIL_ACCOUNT`` is used.

    Args:
        account: Account name (e.g., "Gmail", "Work"). Defaults to DEFAULT_MAIL_ACCOUNT.
        name: Name for the new mailbox. May contain "/" to create a
              nested path in one call (each segment is created if needed).
        parent_mailbox: Optional existing parent folder for nesting.

    Returns:
        Confirmation with the new mailbox path.
    """
    if account is None:
        account = _server.DEFAULT_MAIL_ACCOUNT
    if not account:
        return "Error: account is required (and no DEFAULT_MAIL_ACCOUNT configured)."

    account_err = validate_account_name(account)
    if account_err:
        return account_err

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




@mcp.tool(annotations=IDEMPOTENT_WRITE_TOOL_ANNOTATIONS)
@inject_preferences
def synchronize_account(account: Optional[str] = None, confirm_sync: bool = False) -> str:
    """
    Force Mail.app to synchronize an account (or every account) with its
    IMAP / Exchange server right now. Equivalent to clicking the
    refresh button next to the account or selecting Mailbox → Synchronize.

    Use after `move_email`, `update_email_status`, or `manage_trash`
    when downstream clients (iPhone, web mail, etc.) need to see the
    change immediately. Mail.app's natural sync cadence is "automatic"
    which can be several minutes — this collapses that to one IMAP push.

    Implementation note:
    --------------------
    Uses the `synchronize with <account>` AppleScript verb (per Mail.sdef:
    "Command to trigger synchronizing of an IMAP account with the server")
    rather than `check for new mail`. The latter is receive-only — it
    pulls new messages but does NOT push pending IMAP commands like
    queued moves / archives / flag changes. With `check for new mail`,
    archives done via `move_email` could sit in Mail.app's local cache
    for several minutes before reaching the IMAP server, leaving iPhone
    Mail (which reads IMAP directly) showing already-archived messages
    still in INBOX. `synchronize with` is the bidirectional verb that
    drains pending IMAP commands AND fetches new mail.

    Mail.app's synchronize is potentially long-running. We wrap each
    invocation in `with timeout of N seconds` so the AppleScript returns
    promptly. When the timeout fires (error -1712) Mail.app keeps the
    sync running in the background — exactly the fire-and-forget
    semantics callers expect.

    Args:
        account: Account name (e.g., "Gmail", "Work"). Omit to sync every
                 configured account.
        confirm_sync: Required explicit opt-in. Synchronizing can make Mail.app
                 download a large backlog of messages, so agents and test
                 batteries must not trigger it implicitly.

    Returns:
        Confirmation string with the account(s) synced or queued.
    """
    # 8 s is comfortably longer than a healthy IMAP sync but short enough
    # that a stuck account / network blip doesn't block the MCP call. On
    # timeout we report "queued" — the sync continues asynchronously.
    PER_ACCOUNT_TIMEOUT_S = 8

    if account is None or not account.strip():
        if not confirm_sync:
            return (
                "Error: synchronize_account requires confirm_sync=True. "
                "Synchronizing can trigger Mail.app to download a large message backlog; "
                "do not call it from routine tests."
            )
        script = f'''
        tell application "Mail"
            set acctNames to {{}}
            set queuedNames to {{}}
            repeat with a in accounts
                set acctName to name of a
                set end of acctNames to acctName
                try
                    with timeout of {PER_ACCOUNT_TIMEOUT_S} seconds
                        synchronize with a
                    end timeout
                on error errMsg number errNum
                    if errNum is -1712 then
                        set end of queuedNames to acctName
                    end if
                end try
            end repeat
            set AppleScript's text item delimiters to ", "
            if (count of queuedNames) > 0 then
                return "Synchronized all accounts: " & (acctNames as string) & " (queued: " & (queuedNames as string) & ")"
            else
                return "Synchronized all accounts: " & (acctNames as string)
            end if
        end tell
        '''
        return run_applescript(script)

    account = account.strip()
    account_err = validate_account_name(account, timeout=PER_ACCOUNT_TIMEOUT_S)
    if account_err:
        return account_err
    if not confirm_sync:
        return (
            f"Error: synchronize_account for '{account}' requires confirm_sync=True. "
            "Synchronizing can trigger Mail.app to download a large message backlog."
        )

    acct_escaped = escape_applescript(account)
    script = f'''
    tell application "Mail"
        try
            set targetAccount to first account whose name is "{acct_escaped}"
            try
                with timeout of {PER_ACCOUNT_TIMEOUT_S} seconds
                    synchronize with targetAccount
                end timeout
                return "Synchronized: {acct_escaped}"
            on error errMsg number errNum
                if errNum is -1712 then
                    return "Synchronizing: {acct_escaped} (queued — push in progress)"
                end if
                return "Error: " & errMsg
            end try
        on error errMsg
            return "Error: " & errMsg
        end try
    end tell
    '''
    return run_applescript(script)

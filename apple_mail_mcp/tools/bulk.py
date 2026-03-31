"""Bulk email operations: batch mark, delete, and move emails."""

from typing import Optional

from apple_mail_mcp.server import mcp
from apple_mail_mcp.core import inject_preferences, escape_applescript, run_applescript, build_mailbox_ref


# ---------------------------------------------------------------------------
# Shared helpers for bulk operations
# ---------------------------------------------------------------------------

def _build_filter_conditions(
    subject_keyword: Optional[str] = None,
    sender: Optional[str] = None,
) -> str:
    """Build AppleScript filter conditions from optional parameters.

    Returns an AppleScript boolean expression string.
    """
    conditions: list[str] = []
    if subject_keyword:
        conditions.append(
            f'messageSubject contains "{escape_applescript(subject_keyword)}"'
        )
    if sender:
        conditions.append(
            f'messageSender contains "{escape_applescript(sender)}"'
        )
    return " and ".join(conditions) if conditions else "true"



def _date_filter_script(older_than_days: Optional[int]) -> str:
    """Return AppleScript lines that set `cutoffDate` and a check condition.

    If *older_than_days* is ``None`` or <= 0 the condition is always true.
    Returns a tuple-like pair: (setup_lines, condition_expression).
    We encode both in a small dataclass-style dict so callers stay simple.
    """
    if older_than_days and older_than_days > 0:
        setup = f"set cutoffDate to (current date) - ({older_than_days} * days)"
        condition = "(date received of aMessage) < cutoffDate"
    else:
        setup = ""
        condition = "true"
    return setup, condition


def _validate_filters(
    subject_keyword: Optional[str],
    sender: Optional[str],
    older_than_days: Optional[int] = None,
) -> Optional[str]:
    """Return an error string if no filters are provided, else None."""
    has_filter = bool(subject_keyword) or bool(sender) or (
        older_than_days is not None and older_than_days > 0
    )
    if not has_filter:
        return (
            "Error: At least one filter is required (subject_keyword, sender, "
            "or older_than_days). Refusing to operate on all emails without a filter."
        )
    return None


# ---------------------------------------------------------------------------
# mark_emails  (issue #2)
# ---------------------------------------------------------------------------

@mcp.tool()
@inject_preferences
def mark_emails(
    account: str,
    action: str,
    subject_keyword: Optional[str] = None,
    sender: Optional[str] = None,
    mailbox: str = "INBOX",
    older_than_days: Optional[int] = None,
    max_emails: int = 50,
) -> str:
    """
    Batch mark emails as read/unread and/or flagged/unflagged.

    At least one filter (subject_keyword, sender, or older_than_days) is required.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        action: Action to perform: "read", "unread", "flagged", "unflagged"
        subject_keyword: Optional keyword to filter emails by subject
        sender: Optional sender email/name to filter by
        mailbox: Mailbox to search in (default: "INBOX")
        older_than_days: Only affect emails older than N days
        max_emails: Maximum number of emails to update (safety limit, default: 50)

    Returns:
        Summary of affected emails
    """
    # Validate at least one filter
    err = _validate_filters(subject_keyword, sender, older_than_days)
    if err:
        return err

    # Map action to AppleScript property change
    action_map = {
        "read": ("set read status of aMessage to true", "Marked as read"),
        "unread": ("set read status of aMessage to false", "Marked as unread"),
        "flagged": ("set flagged status of aMessage to true", "Flagged"),
        "unflagged": ("set flagged status of aMessage to false", "Unflagged"),
    }
    if action not in action_map:
        return f"Error: Invalid action '{action}'. Use: read, unread, flagged, unflagged"

    action_script, action_label = action_map[action]

    safe_account = escape_applescript(account)
    condition_str = _build_filter_conditions(subject_keyword, sender)
    date_setup, date_condition = _date_filter_script(older_than_days)
    mailbox_setup = build_mailbox_ref(mailbox, "targetAccount", "targetMailbox")

    script = f'''
    tell application "Mail"
        set outputText to "BATCH MARK EMAILS: {action_label}" & return & return
        set updateCount to 0

        try
            set targetAccount to account "{safe_account}"
            {mailbox_setup}
            {date_setup}

            set mailboxMessages to every message of targetMailbox

            repeat with aMessage in mailboxMessages
                if updateCount >= {max_emails} then exit repeat

                try
                    set messageSubject to subject of aMessage
                    set messageSender to sender of aMessage
                    set messageDate to date received of aMessage

                    if {condition_str} then
                        if {date_condition} then
                            {action_script}

                            set outputText to outputText & "- {action_label}: " & messageSubject & return
                            set outputText to outputText & "  From: " & messageSender & return & return

                            set updateCount to updateCount + 1
                        end if
                    end if
                end try
            end repeat

            set outputText to outputText & "========================================" & return
            set outputText to outputText & "TOTAL UPDATED: " & updateCount & " email(s)" & return
            if updateCount >= {max_emails} then
                set outputText to outputText & "(max_emails limit reached)" & return
            end if
            set outputText to outputText & "========================================" & return

        on error errMsg
            return "Error: " & errMsg
        end try

        return outputText
    end tell
    '''

    return run_applescript(script)


# ---------------------------------------------------------------------------
# delete_emails  (issue #3)
# ---------------------------------------------------------------------------

@mcp.tool()
@inject_preferences
def delete_emails(
    account: str,
    subject_keyword: Optional[str] = None,
    sender: Optional[str] = None,
    older_than_days: Optional[int] = None,
    mailbox: str = "INBOX",
    max_emails: int = 25,
    dry_run: bool = True,
) -> str:
    """
    Soft-delete emails (move to Trash) matching filters, with safety features.

    IMPORTANT: dry_run=True by default -- shows what WOULD be deleted without acting.
    Set dry_run=False to actually move emails to Trash.

    At least one filter (subject_keyword, sender, or older_than_days) is required.
    Emails are moved to Trash, never permanently deleted.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        subject_keyword: Optional keyword to filter emails by subject
        sender: Optional sender email/name to filter by
        older_than_days: Only affect emails older than N days
        mailbox: Source mailbox to search in (default: "INBOX")
        max_emails: Maximum number of emails to delete (safety limit, default: 25)
        dry_run: If True (default), only preview what would be deleted

    Returns:
        List of affected email subjects and count
    """
    # Validate at least one filter
    err = _validate_filters(subject_keyword, sender, older_than_days)
    if err:
        return err

    safe_account = escape_applescript(account)
    condition_str = _build_filter_conditions(subject_keyword, sender)
    date_setup, date_condition = _date_filter_script(older_than_days)
    mailbox_setup = build_mailbox_ref(mailbox, "targetAccount", "sourceMailbox")

    mode_label = "DRY RUN - PREVIEW" if dry_run else "DELETING (move to Trash)"
    move_action = "" if dry_run else """
                            move aMessage to trashMailbox"""

    # Only resolve trash mailbox if not dry_run
    trash_setup = "" if dry_run else """
            set trashMailbox to mailbox "Trash" of targetAccount"""

    script = f'''
    tell application "Mail"
        set outputText to "{mode_label}" & return & return
        set matchCount to 0

        try
            set targetAccount to account "{safe_account}"
            {mailbox_setup}
            {trash_setup}
            {date_setup}

            set mailboxMessages to every message of sourceMailbox

            repeat with aMessage in mailboxMessages
                if matchCount >= {max_emails} then exit repeat

                try
                    set messageSubject to subject of aMessage
                    set messageSender to sender of aMessage
                    set messageDate to date received of aMessage

                    if {condition_str} then
                        if {date_condition} then
                            set outputText to outputText & "- " & messageSubject & return
                            set outputText to outputText & "  From: " & messageSender & return
                            set outputText to outputText & "  Date: " & (messageDate as string) & return & return
                            {move_action}
                            set matchCount to matchCount + 1
                        end if
                    end if
                end try
            end repeat

            set outputText to outputText & "========================================" & return
            if {"true" if dry_run else "false"} then
                set outputText to outputText & "WOULD DELETE: " & matchCount & " email(s)" & return
                set outputText to outputText & "(Set dry_run=False to actually delete)" & return
            else
                set outputText to outputText & "MOVED TO TRASH: " & matchCount & " email(s)" & return
            end if
            if matchCount >= {max_emails} then
                set outputText to outputText & "(max_emails limit reached)" & return
            end if
            set outputText to outputText & "========================================" & return

        on error errMsg
            return "Error: " & errMsg
        end try

        return outputText
    end tell
    '''

    return run_applescript(script)


# ---------------------------------------------------------------------------
# bulk_move_emails  (issue #4)
# ---------------------------------------------------------------------------

@mcp.tool()
@inject_preferences
def bulk_move_emails(
    account: str,
    to_mailbox: str,
    subject_keyword: Optional[str] = None,
    sender: Optional[str] = None,
    from_mailbox: str = "INBOX",
    older_than_days: Optional[int] = None,
    max_emails: int = 50,
    dry_run: bool = False,
) -> str:
    """
    Move multiple emails matching filters to a destination mailbox.

    Both from_mailbox (source) and to_mailbox (destination) are required.
    At least one filter (subject_keyword, sender, or older_than_days) is required.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        to_mailbox: Destination mailbox. Use "/" for nested mailboxes (e.g., "Projects/ClientX")
        subject_keyword: Optional keyword to filter emails by subject
        sender: Optional sender email/name to filter by
        from_mailbox: Source mailbox (default: "INBOX")
        older_than_days: Only affect emails older than N days
        max_emails: Maximum number of emails to move (safety limit, default: 50)
        dry_run: If True, preview what would be moved without acting (default: False)

    Returns:
        Summary of moved emails with count
    """
    # Validate at least one filter
    err = _validate_filters(subject_keyword, sender, older_than_days)
    if err:
        return err

    safe_account = escape_applescript(account)
    condition_str = _build_filter_conditions(subject_keyword, sender)
    date_setup, date_condition = _date_filter_script(older_than_days)
    source_setup = build_mailbox_ref(from_mailbox, "targetAccount", "sourceMailbox")

    # Build nested mailbox reference for destination
    mailbox_parts = to_mailbox.split("/")
    if len(mailbox_parts) > 1:
        dest_ref = f'mailbox "{escape_applescript(mailbox_parts[-1])}" of '
        for i in range(len(mailbox_parts) - 2, -1, -1):
            dest_ref += f'mailbox "{escape_applescript(mailbox_parts[i])}" of '
        dest_ref += "targetAccount"
    else:
        dest_ref = f'mailbox "{escape_applescript(to_mailbox)}" of targetAccount'

    mode_label = "DRY RUN - PREVIEW MOVE" if dry_run else "MOVING EMAILS"
    safe_from = escape_applescript(from_mailbox)
    safe_to = escape_applescript(to_mailbox)
    move_action = "" if dry_run else """
                            move aMessage to destMailbox"""

    # Only resolve dest mailbox when actually moving
    dest_setup = "" if dry_run else f"""
            set destMailbox to {dest_ref}"""

    script = f'''
    tell application "Mail"
        set outputText to "{mode_label}: {safe_from} -> {safe_to}" & return & return
        set moveCount to 0

        try
            set targetAccount to account "{safe_account}"
            {source_setup}
            {dest_setup}
            {date_setup}

            set mailboxMessages to every message of sourceMailbox

            repeat with aMessage in mailboxMessages
                if moveCount >= {max_emails} then exit repeat

                try
                    set messageSubject to subject of aMessage
                    set messageSender to sender of aMessage
                    set messageDate to date received of aMessage

                    if {condition_str} then
                        if {date_condition} then
                            set outputText to outputText & "- " & messageSubject & return
                            set outputText to outputText & "  From: " & messageSender & return
                            {move_action}
                            set moveCount to moveCount + 1
                        end if
                    end if
                end try
            end repeat

            set outputText to outputText & "========================================" & return
            if {"true" if dry_run else "false"} then
                set outputText to outputText & "WOULD MOVE: " & moveCount & " email(s)" & return
                set outputText to outputText & "(Set dry_run=False to actually move)" & return
            else
                set outputText to outputText & "TOTAL MOVED: " & moveCount & " email(s)" & return
            end if
            if moveCount >= {max_emails} then
                set outputText to outputText & "(max_emails limit reached)" & return
            end if
            set outputText to outputText & "========================================" & return

        on error errMsg
            return "Error: " & errMsg & return & "Check that account and mailbox names are correct. For nested mailboxes, use '/' separator."
        end try

        return outputText
    end tell
    '''

    return run_applescript(script)

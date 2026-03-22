"""Core helpers: AppleScript execution, escaping, parsing, and preference injection."""

import subprocess
from typing import Optional, List, Dict, Any, Tuple

from apple_mail_mcp.server import USER_PREFERENCES


def inject_preferences(func):
    """Decorator that appends user preferences to tool docstrings"""
    if USER_PREFERENCES:
        if func.__doc__:
            func.__doc__ = (
                func.__doc__.rstrip() + f"\n\nUser Preferences: {USER_PREFERENCES}"
            )
        else:
            func.__doc__ = f"User Preferences: {USER_PREFERENCES}"
    return func


def escape_applescript(value: str) -> str:
    """Escape a string for safe injection into AppleScript double-quoted strings.

    Handles backslashes first, then double quotes, then newlines/returns/tabs,
    and Unicode line/paragraph separators to prevent injection and AppleScript
    syntax errors.
    """
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r\n", "\\n")
        .replace("\r", "\\n")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        # Unicode line/paragraph separators can break AppleScript string parsing
        .replace("\u2028", "\\n")
        .replace("\u2029", "\\n")
    )


def _sanitize_for_json(text: str) -> str:
    """Sanitize text for safe JSON serialization over MCP stdio transport.

    Forces ASCII-safe output to avoid encoding issues in the
    Desktop <-> CLI <-> MCP communication chain.
    """
    # Normalize line endings first (AppleScript uses \r)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Force ASCII: replaces non-ASCII chars with their Unicode escape or drops them
    text = text.encode("ascii", "replace").decode("ascii")
    # Strip remaining control characters (keep \n and \t)
    return "".join(ch for ch in text if ch in ("\n", "\t") or (" " <= ch <= "~"))


def run_applescript(script: str, timeout: int = 120) -> str:
    """Execute AppleScript via stdin pipe for reliable multi-line handling."""
    try:
        result = subprocess.run(
            ["osascript", "-"],
            input=script.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            if stderr:
                raise Exception(f"AppleScript error: {stderr}")
        output = result.stdout.decode("utf-8", errors="replace").strip()
        return _sanitize_for_json(output)
    except subprocess.TimeoutExpired:
        raise Exception("AppleScript execution timed out")
    except Exception as e:
        raise Exception(f"AppleScript execution failed: {str(e)}")


def normalize_search_terms(
    search_term: Optional[str] = None,
    search_terms: Optional[List[str]] = None,
) -> List[str]:
    """Return de-duplicated, non-empty search terms preserving order."""
    normalized = []

    if search_term and search_term.strip():
        normalized.append(search_term.strip())

    if search_terms:
        for term in search_terms:
            if term and term.strip():
                normalized.append(term.strip())

    unique_terms = []
    for term in normalized:
        if term not in unique_terms:
            unique_terms.append(term)

    return unique_terms


def contains_any_condition(field_name: str, values: List[str]) -> str:
    """Return AppleScript OR conditions for substring matches."""
    if not values:
        return "true"

    escaped_values = [escape_applescript(value) for value in values]
    parts = [f'{field_name} contains "{value}"' for value in escaped_values]
    return "(" + " or ".join(parts) + ")"


def normalize_message_ids(message_ids: Optional[List[Any]]) -> List[str]:
    """Return de-duplicated numeric Mail ids as strings preserving order."""
    if not message_ids:
        return []

    normalized = []
    for value in message_ids:
        value_text = str(value).strip()
        if value_text and value_text.isdigit() and value_text not in normalized:
            normalized.append(value_text)

    return normalized


def equals_any_numeric_condition(field_name: str, values: List[str]) -> str:
    """Return AppleScript OR conditions for numeric equality matches."""
    if not values:
        return "false"

    parts = [f"{field_name} is {value}" for value in values]
    return "(" + " or ".join(parts) + ")"


def parse_email_list(output: str) -> List[Dict[str, Any]]:
    """Parse the structured email output from AppleScript"""
    emails = []
    lines = output.split("\n")

    current_email = {}
    for line in lines:
        line = line.strip()
        if (
            not line
            or line.startswith("=")
            or line.startswith("━")
            or line.startswith("📧")
            or line.startswith("⚠")
        ):
            continue

        if line.startswith("✉") or line.startswith("✓"):
            # New email entry
            if current_email:
                emails.append(current_email)

            is_read = line.startswith("✓")
            subject = line[2:].strip()  # Remove indicator
            current_email = {"subject": subject, "is_read": is_read}
        elif line.startswith("From:"):
            current_email["sender"] = line[5:].strip()
        elif line.startswith("Date:"):
            current_email["date"] = line[5:].strip()
        elif line.startswith("Preview:"):
            current_email["preview"] = line[8:].strip()
        elif line.startswith("TOTAL EMAILS"):
            # End of email list
            if current_email:
                emails.append(current_email)
            break

    if current_email and current_email not in emails:
        emails.append(current_email)

    return emails


# ---------------------------------------------------------------------------
# Shared AppleScript template helpers
# ---------------------------------------------------------------------------

LOWERCASE_HANDLER = """
    on lowercase(str)
        set lowerStr to do shell script "echo " & quoted form of str & " | tr '[:upper:]' '[:lower:]'"
        return lowerStr
    end lowercase
"""


def inbox_mailbox_script(
    var_name: str = "inboxMailbox", account_var: str = "anAccount"
) -> str:
    """Return AppleScript snippet to get inbox mailbox with INBOX/Inbox fallback."""
    return f"""
                try
                    set {var_name} to mailbox "INBOX" of {account_var}
                on error
                    set {var_name} to mailbox "Inbox" of {account_var}
                end try"""


def content_preview_script(max_length: int, output_var: str = "outputText") -> str:
    """Return AppleScript snippet to extract and truncate email content preview."""
    return f"""
                            try
                                set msgContent to content of aMessage
                                set AppleScript's text item delimiters to {{return, linefeed}}
                                set contentParts to text items of msgContent
                                set AppleScript's text item delimiters to " "
                                set cleanText to contentParts as string
                                set AppleScript's text item delimiters to ""

                                if length of cleanText > {max_length} then
                                    set contentPreview to text 1 thru {max_length} of cleanText & "..."
                                else
                                    set contentPreview to cleanText
                                end if

                                set {output_var} to {output_var} & "   Content: " & contentPreview & return
                            on error
                                set {output_var} to {output_var} & "   Content: [Not available]" & return
                            end try"""


def date_cutoff_script(days_back: int, var_name: str = "cutoffDate") -> str:
    """Return AppleScript snippet to set a date cutoff variable."""
    if days_back <= 0:
        return ""
    return f"""
            set {var_name} to (current date) - ({days_back} * days)"""


def skip_folders_condition(var_name: str = "mailboxName") -> str:
    """Return AppleScript condition to skip system folders (Trash, Junk, etc)."""
    from apple_mail_mcp.constants import SKIP_FOLDERS

    folder_list = ", ".join(f'"{f}"' for f in SKIP_FOLDERS)
    return f"{var_name} is not in {{{folder_list}}}"


def build_mailbox_ref(
    mailbox: str,
    account_var: str = "targetAccount",
    var_name: str = "targetMailbox",
) -> str:
    """Return AppleScript snippet to resolve a mailbox by name with INBOX fallback.

    Handles:
    - Normal mailbox names (e.g. "Archive")
    - INBOX / Inbox case variation
    - Nested mailbox paths using "/" separator (e.g. "Projects/2024")

    The resulting variable *var_name* will hold the resolved mailbox reference.
    """
    escaped = escape_applescript(mailbox)
    parts = mailbox.split("/")

    if len(parts) > 1:
        # Build nested mailbox reference: mailbox "Child" of mailbox "Parent" of account
        ref = f'mailbox "{escape_applescript(parts[-1])}" of '
        for i in range(len(parts) - 2, -1, -1):
            ref += f'mailbox "{escape_applescript(parts[i])}" of '
        ref += account_var
        return f"set {var_name} to {ref}"

    return f'''try
                set {var_name} to mailbox "{escaped}" of {account_var}
            on error
                if "{escaped}" is "INBOX" then
                    set {var_name} to mailbox "Inbox" of {account_var}
                else
                    error "Mailbox not found: {escaped}"
                end if
            end try'''


def build_filter_condition(
    subject: Optional[str] = None,
    sender: Optional[str] = None,
    subject_var: str = "messageSubject",
    sender_var: str = "messageSender",
) -> str:
    """Return an AppleScript boolean expression combining subject/sender filters.

    When both are provided they are ANDed together.
    Returns ``"true"`` when neither filter is given.
    """
    conditions: list[str] = []
    if subject:
        conditions.append(f'{subject_var} contains "{escape_applescript(subject)}"')
    if sender:
        conditions.append(f'{sender_var} contains "{escape_applescript(sender)}"')
    return " and ".join(conditions) if conditions else "true"


def build_date_filter(
    days_back: int,
    var_name: str = "cutoffDate",
) -> Tuple[str, str]:
    """Return (setup_script, condition_fragment) for a date-based cutoff.

    *setup_script* should be placed before the message loop.
    *condition_fragment* is an AppleScript fragment like
    ``"and messageDate > cutoffDate"`` suitable for appending to an ``if``
    clause.  When *days_back* is 0 both strings are empty.
    """
    if days_back <= 0:
        return ("", "")
    setup = f"set {var_name} to (current date) - ({days_back} * days)"
    condition = f"and messageDate > {var_name}"
    return (setup, condition)


def build_email_fields_script(
    message_var: str = "aMessage",
    include_content: bool = False,
    max_content_length: int = 300,
    output_var: str = "outputText",
) -> str:
    """Return AppleScript snippet that extracts common fields from an email.

    Sets local variables: messageSubject, messageSender, messageDate,
    messageRead.  Optionally appends a cleaned content preview to
    *output_var*.
    """
    fields = f"""set messageSubject to subject of {message_var}
                                set messageSender to sender of {message_var}
                                set messageDate to date received of {message_var}
                                set messageRead to read status of {message_var}"""

    if not include_content:
        return fields

    content = f"""
                                try
                                    set msgContent to content of {message_var}
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
                                    set {output_var} to {output_var} & "   Content: " & contentPreview & return
                                on error
                                    set {output_var} to {output_var} & "   Content: [Not available]" & return
                                end try"""
    return fields + content

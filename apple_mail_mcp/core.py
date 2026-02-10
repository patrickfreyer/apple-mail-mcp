"""Core helpers: AppleScript execution, escaping, parsing, and preference injection."""

import subprocess
from typing import List, Dict, Any

from apple_mail_mcp.server import USER_PREFERENCES


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


# ---------------------------------------------------------------------------
# Shared AppleScript template helpers
# ---------------------------------------------------------------------------

LOWERCASE_HANDLER = '''
    on lowercase(str)
        set lowerStr to do shell script "echo " & quoted form of str & " | tr '[:upper:]' '[:lower:]'"
        return lowerStr
    end lowercase
'''


def inbox_mailbox_script(var_name: str = "inboxMailbox", account_var: str = "anAccount") -> str:
    """Return AppleScript snippet to get inbox mailbox with INBOX/Inbox fallback."""
    return f'''
                try
                    set {var_name} to mailbox "INBOX" of {account_var}
                on error
                    set {var_name} to mailbox "Inbox" of {account_var}
                end try'''


def content_preview_script(max_length: int, output_var: str = "outputText") -> str:
    """Return AppleScript snippet to extract and truncate email content preview."""
    return f'''
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
                            end try'''


def date_cutoff_script(days_back: int, var_name: str = "cutoffDate") -> str:
    """Return AppleScript snippet to set a date cutoff variable."""
    if days_back <= 0:
        return ""
    return f'''
            set {var_name} to (current date) - ({days_back} * days)'''


def skip_folders_condition(var_name: str = "mailboxName") -> str:
    """Return AppleScript condition to skip system folders (Trash, Junk, etc)."""
    from apple_mail_mcp.constants import SKIP_FOLDERS
    folder_list = ', '.join(f'"{f}"' for f in SKIP_FOLDERS)
    return f'{var_name} is not in {{{folder_list}}}'

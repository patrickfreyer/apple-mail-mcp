"""Core helpers: AppleScript execution, escaping, parsing, and preference injection."""

import atexit
import re
import signal
import subprocess
import threading
from typing import Optional, List, Dict, Any, Tuple

from apple_mail_mcp.server import USER_PREFERENCES


# ---------------------------------------------------------------------------
# In-flight osascript child tracking
# ---------------------------------------------------------------------------
# All live Popen objects for in-flight osascript calls.  Guarded by
# _inflight_lock so callers on any thread can safely add/remove entries.
_inflight_children: set = set()
_inflight_lock = threading.Lock()

# Sentinel so we only register atexit + signal handlers once.
_cleanup_registered = False
_cleanup_lock = threading.Lock()


def _kill_inflight_children() -> None:
    """Kill every in-flight osascript child that is still alive.

    Called from atexit and chained signal handlers so that graceful
    SIGTERM/SIGHUP/normal-exit paths do not leave orphaned osascript
    processes behind.  The AppleScript-level ``with timeout`` block (see
    _apply_applescript_timeout) is the safety net for SIGKILL / os._exit,
    where these handlers never run.
    """
    with _inflight_lock:
        procs = list(_inflight_children)
    for proc in procs:
        try:
            proc.kill()
            proc.wait()
        except Exception:
            pass


def _register_cleanup_once() -> None:
    """Register atexit and SIGTERM/SIGHUP handlers exactly once, thread-safely.

    Signal handlers may only be set from the main thread; the try/except
    guards against ImportError or ValueError when called from a worker thread
    so that module import never crashes in non-main-thread contexts.
    """
    global _cleanup_registered
    with _cleanup_lock:
        if _cleanup_registered:
            return
        _cleanup_registered = True

    atexit.register(_kill_inflight_children)

    # Chain onto any previously installed signal handlers rather than
    # clobbering them (e.g. FastMCP installs its own SIGTERM handler).
    for sig in (signal.SIGTERM, signal.SIGHUP):
        try:
            old_handler = signal.getsignal(sig)

            def _make_handler(old, signum_capture=sig):
                def _handler(signum, frame):
                    _kill_inflight_children()
                    if callable(old) and old not in (
                        signal.SIG_DFL,
                        signal.SIG_IGN,
                    ):
                        old(signum, frame)
                return _handler

            signal.signal(sig, _make_handler(old_handler))
        except (ValueError, OSError):
            # Not on the main thread or signal not available — skip silently.
            pass


def _popen_factory(*args, **kwargs) -> subprocess.Popen:
    """Thin wrapper around subprocess.Popen; injectable for unit tests."""
    return subprocess.Popen(*args, **kwargs)


# ---------------------------------------------------------------------------
# AppleScript timeout injection
# ---------------------------------------------------------------------------


# Handler definitions ("on name(...)" / "to name(...)") are only legal at the
# top level of an AppleScript — never inside a block.  "on error" is a try
# clause, not a handler definition, so it must not trigger the guard.
_HANDLER_DEFINITION_RE = re.compile(r"^\s*(?:on|to)\s+(?!error\b)\w+", re.MULTILINE)


def _apply_applescript_timeout(script: str, timeout: int) -> str:
    """Wrap *script* in an AppleScript ``with timeout`` block.

    The inner timeout is ``max(timeout - 5, 5)`` seconds, giving the
    AppleScript interpreter a chance to exit cleanly before the Python-side
    ``communicate(timeout=…)`` fires.

    Two classes of script cannot legally be nested inside a block and are
    returned unchanged:

    * scripts with a top-level ``use`` declaration (e.g. ASObjC
      ``use framework "Foundation"`` in compose.py);
    * scripts that define handlers (``on name(...)`` / ``to name(...)``) —
      handler definitions are only legal at the top level, so wrapping them
      fails with 'Expected "end" but found "on"' (-2741, issue #63).  These
      scripts keep their own inner ``with timeout`` blocks, and the
      Python-side ``communicate(timeout=…)`` kill still covers them.

    Nested ``with timeout`` blocks are legal in AppleScript, so this wrap is
    compatible with per-tool timeouts already present in manage.py / search.py.
    """
    if any(line.lstrip().startswith("use ") for line in script.splitlines()):
        return script
    if _HANDLER_DEFINITION_RE.search(script):
        return script
    inner = max(timeout - 5, 5)
    return f"with timeout of {inner} seconds\n{script}\nend timeout"


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

    Preserves Unicode (including Cyrillic, CJK, Arabic, etc.) while
    stripping control characters.
    """
    # Normalize line endings first (AppleScript uses \r)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Strip control characters but keep \n, \t, and all printable Unicode
    return "".join(ch for ch in text if ch in ("\n", "\t") or (ord(ch) >= 32))


def run_applescript(script: str, timeout: int = 120) -> str:
    """Execute AppleScript via stdin pipe for reliable multi-line handling.

    Two-layer defence against orphaned osascript children (issue #58):

    1. The script is wrapped in an AppleScript ``with timeout`` block so the
       interpreter self-terminates even when the parent process is SIGKILLed
       or exits via os._exit() (e.g. the orphan-watcher in __main__.py).

    2. The live Popen object is tracked in ``_inflight_children``.  An atexit
       handler and chained SIGTERM/SIGHUP handlers call kill() on any survivors
       so graceful-exit paths also clean up.
    """
    # Ensure signal/atexit handlers are registered (idempotent, main-thread only).
    _register_cleanup_once()

    # Inject an AppleScript-level timeout so the child self-terminates even if
    # the Python process is killed before communicate() can enforce its timeout.
    wrapped = _apply_applescript_timeout(script, timeout)

    proc = _popen_factory(
        ["osascript", "-"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    with _inflight_lock:
        _inflight_children.add(proc)

    try:
        stdout, stderr = proc.communicate(
            input=wrapped.encode("utf-8"), timeout=timeout
        )
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise Exception("AppleScript execution timed out")
    except Exception as e:
        raise Exception(f"AppleScript execution failed: {str(e)}")
    finally:
        with _inflight_lock:
            _inflight_children.discard(proc)

    if proc.returncode != 0:
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        if stderr_text:
            raise Exception(f"AppleScript error: {stderr_text}")

    output = stdout.decode("utf-8", errors="replace").strip()
    return _sanitize_for_json(output)


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


# Localized inbox mailbox names. Mail.app uses the system locale to name
# the inbox folder for non-IMAP accounts (Exchange, on-my-Mac), so we must
# try multiple names to find it. IMAP accounts (iCloud, Gmail) typically
# expose 'INBOX' regardless of system language.
INBOX_NAMES = [
    "INBOX",                  # IMAP standard (iCloud, Gmail, Fastmail)
    "Inbox",                  # English non-IMAP
    "Boîte de réception",     # French (Exchange/Outlook on FR system)
    "Boîte aux lettres",      # French alt
    "Réception",              # French alt
    "Posteingang",            # German
    "Bandeja de entrada",     # Spanish
    "Posta in arrivo",        # Italian
    "Caixa de entrada",       # Portuguese
    "Postvak IN",             # Dutch
    "受信トレイ",             # Japanese
]


def inbox_mailbox_script(
    var_name: str = "inboxMailbox", account_var: str = "anAccount"
) -> str:
    """Return AppleScript snippet to resolve the inbox mailbox.

    Iterates through INBOX_NAMES (localized variants) so non-English
    Mail.app accounts — typically Exchange on a French/German/etc.
    system where the inbox is 'Boîte de réception' / 'Posteingang' —
    still resolve correctly.
    """
    name_list = ", ".join(f'"{n}"' for n in INBOX_NAMES)
    return f"""
                set {var_name} to missing value
                repeat with __inboxLookupName in {{{name_list}}}
                    try
                        set {var_name} to mailbox (__inboxLookupName as string) of {account_var}
                        exit repeat
                    end try
                end repeat
                if {var_name} is missing value then
                    error "No inbox mailbox found for account " & (name of {account_var})
                end if"""


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

    # When caller asks for "INBOX" (default for most tools), iterate the
    # localized fallback list so Exchange/non-English inboxes are found.
    if mailbox.upper() == "INBOX":
        name_list = ", ".join(f'"{n}"' for n in INBOX_NAMES)
        return f'''set {var_name} to missing value
            repeat with __mailboxLookupName in {{{name_list}}}
                try
                    set {var_name} to mailbox (__mailboxLookupName as string) of {account_var}
                    exit repeat
                end try
            end repeat
            if {var_name} is missing value then
                error "Mailbox not found: {escaped} (no localized inbox match)"
            end if'''

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

"""Raw source tool: return the full RFC 822 source of a message.

The other body-extraction paths in this MCP go through ``content of aMessage``
— Mail.app's rendered (display-text) representation. That path collapses HTML
to plain text and replaces embedded objects (including hyperlinks) with
U+FFFC, so hrefs and MIME structure don't survive.

This tool exposes the parallel ``source of aMessage`` property instead. Same
property that produces the ``.partial.emlx`` file content on disk. The caller
gets the full RFC 822 bytes and can decode them with their MIME library of
choice (``email.message_from_string()``, ``mailparser``, regex over hrefs,
etc.).

Use when the rendered output from ``search_emails`` / ``export_emails`` is
insufficient — URL extraction, custom header inspection, MIME part discovery,
faithful archival.
"""

from typing import Optional

from apple_mail_mcp.server import mcp
from apple_mail_mcp.core import escape_applescript, run_applescript


# Default byte cap for returned source. A plain message is ~200 KB; messages
# with attachments are typically far larger and would flood the model context
# if returned in full. Callers needing the whole payload can raise the cap or
# read the on-disk ``.partial.emlx`` directly.
DEFAULT_MAX_BYTES = 256 * 1024


def _apply_size_cap(source: str, max_bytes: int) -> str:
    """Truncate ``source`` to ``max_bytes`` (UTF-8 encoded) with a marker.

    The cap is applied on the encoded byte length, not character count, so
    multi-byte payloads (UTF-8 headers, base64 with non-ASCII filenames) cap
    at the intended size. Truncation is performed at a UTF-8 character
    boundary so the returned prefix remains decodable.
    """
    encoded = source.encode("utf-8", errors="replace")
    original_size = len(encoded)
    if original_size <= max_bytes:
        return source

    # ``errors="ignore"`` drops any partial multi-byte sequence at the cut.
    prefix = encoded[:max_bytes].decode("utf-8", errors="ignore")
    marker = (
        f"\n\n[... truncated: original size {original_size} bytes, "
        f"cap {max_bytes} bytes ...]"
    )
    return prefix + marker


@mcp.tool()
def get_email_source(
    account: str,
    subject_keyword: Optional[str] = None,
    message_id: Optional[str] = None,
    mailbox: str = "INBOX",
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> str:
    """Return the raw RFC 822 source of a single message.

    The MCP's other body-extraction paths return Mail.app's rendered content
    (HTML collapsed to display text, hrefs dropped, embedded objects replaced
    with U+FFFC). This tool returns the raw source instead — all headers, all
    MIME parts, all hrefs intact.

    Implementation note:
    --------------------
    Wraps the ``source`` property of ``message`` defined in ``Mail.sdef``
    (the AppleScript dictionary for Mail.app). That property returns the
    same RFC 822 text Mail.app writes to the on-disk ``.partial.emlx`` file,
    so the consumer does not need filesystem access or knowledge of the
    Mail directory layout to recover MIME parts / hrefs / custom headers.

    Identifier resolution: ``message_id`` is preferred when both are provided
    (exact match on the RFC 822 ``Message-Id`` header via AppleScript's
    ``message id`` property — distinct from ``id``, which is Mail.app's
    internal numeric id). ``subject_keyword`` matches the first message in
    ``mailbox`` whose subject contains the substring.

    Output sizing: messages can be large (a plain note is ~200 KB; with
    attachments far larger). ``max_bytes`` caps the returned payload and
    appends a truncation marker when exceeded.

    Args:
        account: Account name (e.g., ``"Gmail"``, ``"Work"``).
        subject_keyword: Substring to match against subject (first hit).
        message_id: RFC 822 Message-Id for exact match (preferred when known).
        mailbox: Mailbox name (default: ``"INBOX"``).
        max_bytes: Byte cap on the returned payload (default 256 KB).

    Returns:
        The raw RFC 822 source as a string, or a string starting with
        ``"Error:"`` if the message could not be resolved.
    """
    if not subject_keyword and not message_id:
        return "Error: must provide subject_keyword or message_id"

    if message_id:
        match_clause = (
            f'whose message id is "{escape_applescript(message_id)}"'
        )
    else:
        match_clause = (
            f'whose subject contains "{escape_applescript(subject_keyword)}"'
        )

    script = f'''
    tell application "Mail"
        try
            set targetAccount to first account whose name is "{escape_applescript(account)}"
        on error
            return "Error: account not found: {escape_applescript(account)}"
        end try

        try
            set targetMailbox to mailbox "{escape_applescript(mailbox)}" of targetAccount
        on error
            return "Error: mailbox not found: {escape_applescript(mailbox)}"
        end try

        set matches to (messages of targetMailbox {match_clause})
        if (count of matches) is 0 then
            return "Error: no message found matching the given criteria"
        end if

        return source of (item 1 of matches)
    end tell
    '''

    result = run_applescript(script)

    # Don't post-process error returns from the AppleScript layer.
    if isinstance(result, str) and result.startswith("Error:"):
        return result

    return _apply_size_cap(result, max_bytes)

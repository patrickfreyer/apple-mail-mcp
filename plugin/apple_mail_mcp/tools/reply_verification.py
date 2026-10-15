"""Verify a saved reply's new body landed outside Mail's quoted original.

`reply_to_email` (see `compose.py`) inserts the new reply body via a blind
clipboard paste into Mail's native reply composer, which already contains
the quoted original thread. That paste is not verified by reading back
`content of replyMessage` -- Mail's GUI editor buffer is decoupled from that
scriptable property, so a read-back there always reports the pre-paste
value even after a successful paste (see the comment above the keystroke
step in `compose.py`).

This module verifies the *saved* draft instead, by reading its raw RFC 822
source (via the existing `get_email_source` tool) after the paste has
already landed on disk. If the new body ends up inside Mail's quoted-original
container -- HTML `<blockquote type="cite">` or a plain-text `>`-quoted
block -- instead of above it, this catches that rather than the tool
reporting success on text presence alone (#71).

Heuristic, not exact: substring matching after whitespace/tag normalization
can produce a false negative if Mail's own text engine reformats the pasted
text (autocorrect, smart-quote substitution) before saving. That is a
narrower failure mode than the one this module closes -- a wrong verdict
that still gets caught by *no* match at all is safer than the previous
behaviour, which never checked in the first place.
"""

import html
import re
from email import message_from_string, policy
from email.utils import getaddresses
from typing import List, Optional, Tuple

_CITE_BLOCKQUOTE_RE = re.compile(
    r'<blockquote[^>]*\btype\s*=\s*["\']cite["\'][^>]*>', re.IGNORECASE
)
_TAG_RE = re.compile(r"<[^>]+>")


def _extract_bodies(raw_source: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (html_body, text_body) from an RFC 822 source string.

    Prefers the first `text/html` and first `text/plain` part found while
    walking the message (covers both `multipart/alternative` and a bare
    single-part message of either type).
    """
    msg = message_from_string(raw_source, policy=policy.default)
    html_body: Optional[str] = None
    text_body: Optional[str] = None

    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        content_type = part.get_content_type()
        if content_type == "text/html" and html_body is None:
            html_body = part.get_content()
        elif content_type == "text/plain" and text_body is None:
            text_body = part.get_content()

    return html_body, text_body


def _html_before_quote(html_body: str) -> str:
    """Return the HTML preceding Mail's quoted-original blockquote, if any.

    Mail's reply composer places new content entirely above the quote
    block, never interleaved, so "before the first cite-blockquote's open
    tag" is the new-content region for a well-formed reply.
    """
    match = _CITE_BLOCKQUOTE_RE.search(html_body)
    return html_body if match is None else html_body[: match.start()]


def _text_before_quote(text_body: str) -> str:
    """Return the plain-text lines preceding the first `>`-quoted line."""
    unquoted_lines = []
    for line in text_body.splitlines():
        if line.lstrip().startswith(">"):
            break
        unquoted_lines.append(line)
    return "\n".join(unquoted_lines)


def _normalize(text: str, *, is_html: bool = False) -> str:
    """Collapse whitespace, decoding markup only for an actual HTML body."""
    if is_html:
        text = html.unescape(_TAG_RE.sub(" ", text))
    return " ".join(text.split())


def _extract_addresses(raw_source: str, header_name: str) -> List[str]:
    """Return the addr-spec list for one address-type header (`to`, `cc`).

    `Bcc` is deliberately not offered through this helper. Whether an
    unsent Mail.app draft's own RFC 822 source retains a `Bcc` header at
    all -- as opposed to only applying it at send time, the way SMTP
    conventionally strips it from what's transmitted -- is not something
    this repo can determine without a live Mail.app draft to inspect, and
    guessing at it risks a check that always silently reports "not found"
    and is mistaken for a working verification.
    """
    msg = message_from_string(raw_source, policy=policy.default)
    header = msg[header_name]
    if header is None:
        return []
    return [address.addr_spec for address in header.addresses]


def verify_recipients(
    raw_source: str,
    *,
    expected_cc: Optional[str] = None,
    expected_from: Optional[str] = None,
) -> Tuple[bool, str]:
    """Verify the saved draft's actual To/Cc/From against what was intended.

    `reply_to_email`'s own AppleScript reports "To: " followed by the
    *original message's sender* -- correct for a plain reply, but
    misleading whenever Mail's own reply-to-all/CC/sender-override
    behaviour means the actually-saved recipients differ from that (#70).
    This reads the real, saved values instead of restating an assumption.

    Args:
        raw_source: RFC 822 source of the saved draft.
        expected_cc: The `cc` argument `reply_to_email` was called with, if
            any -- comma-separated addresses. Checked as a subset: every
            requested address must appear in the saved `Cc` header. Extra
            addresses Mail itself adds (e.g. via reply-to-all) are not
            treated as a mismatch, since those were never the caller's to
            specify in the first place.
        expected_from: The `from_address` `reply_to_email` was called with,
            if any. Compared as case-insensitive addresses against saved `From`.

    Returns:
        `(verified, detail)`. `detail` lists the actual saved To/Cc/From
        and names anything requested that didn't make it into the saved
        draft.
    """
    actual_to = _extract_addresses(raw_source, "to")
    actual_cc = _extract_addresses(raw_source, "cc")
    actual_from = _extract_addresses(raw_source, "from")

    problems: List[str] = []

    if expected_cc:
        requested = [addr for _, addr in getaddresses([expected_cc]) if addr]
        saved_cc = {addr.lower() for addr in actual_cc}
        missing = [addr for addr in requested if addr.lower() not in saved_cc]
        if missing:
            problems.append(
                f"requested CC {missing} not found in saved Cc: {actual_cc}"
            )

    if expected_from:
        requested_from = [addr.lower() for _, addr in getaddresses([expected_from]) if addr]
        if requested_from != [addr.lower() for addr in actual_from]:
            problems.append(
                f"requested From {expected_from!r} not found in saved From: {actual_from}"
            )

    summary = f"To={actual_to} Cc={actual_cc} From={actual_from}"
    if problems:
        return False, f"{summary} -- " + "; ".join(problems)
    return True, summary


def verify_reply_body_outside_quote(
    raw_source: str, reply_body: str, *, body_html: Optional[str] = None
) -> Tuple[bool, str]:
    """Verify `reply_body` was saved outside Mail's quoted-original block.

    Args:
        raw_source: RFC 822 source of the saved draft (from `get_email_source`).
        reply_body: The plain-text reply body that was supposed to be pasted.
        body_html: When supplied, the HTML actually pasted instead of reply_body.

    Returns:
        `(verified, detail)`. `verified` is `True` only when normalized
        `reply_body` is found in the region of the saved body that precedes
        Mail's quote container. `detail` explains which of three outcomes
        occurred: found outside (pass), found only inside the quote (the
        bug #71 describes), or not found at all (paste likely failed for
        an unrelated reason -- see the focus-polling comment in
        `compose.py`).
    """
    reply_snippet = _normalize(body_html or reply_body, is_html=bool(body_html))
    if not reply_snippet:
        return False, "Reply body is empty; nothing to verify."

    html_body, text_body = _extract_bodies(raw_source)

    if html_body is not None:
        if reply_snippet in _normalize(_html_before_quote(html_body), is_html=True):
            return True, "Reply body found outside the quoted original (HTML)."
        if reply_snippet in _normalize(html_body, is_html=True):
            return False, (
                "Reply body found only inside the quoted original (HTML) -- "
                'it landed inside <blockquote type="cite">, not above it.'
            )
        return False, "Reply body not found in the saved draft's HTML body."

    if text_body is not None:
        if reply_snippet in _normalize(_text_before_quote(text_body)):
            return True, "Reply body found outside the quoted original (plain text)."
        if reply_snippet in _normalize(text_body):
            return False, (
                "Reply body found only inside the quoted original (plain text) "
                "-- it landed after a '>' quote marker, not above it."
            )
        return False, "Reply body not found in the saved draft's plain-text body."

    return False, "Saved draft has neither an HTML nor a plain-text body to verify."

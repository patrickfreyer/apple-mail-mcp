"""Composition tools: sending, replying, forwarding, and drafts."""

import mimetypes
import os
import subprocess
import tempfile
import time
import re
import email
from email.message import EmailMessage
from html import escape as html_escape
from pathlib import Path
from typing import Optional, List, Tuple

from apple_mail_mcp import server
from apple_mail_mcp.server import mcp
from apple_mail_mcp.core import (
    inject_preferences,
    escape_applescript,
    run_applescript,
    build_mailbox_ref,
)


def _split_addresses(value):
    """Return trimmed recipient addresses preserving order."""
    if not value:
        return []
    return [addr.strip() for addr in value.split(",") if addr and addr.strip()]


def _safe_eml_name(subject):
    """Return a filesystem-safe filename stem for draft exports."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (subject or "rich-email-draft").strip())
    cleaned = cleaned.strip("-._") or "rich-email-draft"
    return cleaned[:80]


def _default_rich_draft_path(subject):
    """Return default output path for generated rich draft EML files."""
    drafts_dir = Path.home() / "Library" / "Caches" / "apple-mail-mcp" / "rich-drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    return drafts_dir / (_safe_eml_name(subject) + ".eml")


def _account_default_alias_if_single(account):
    """Return the sole alias of `account` when it has exactly one configured
    email address, else None. Used when no explicit sender is requested so
    that single-address accounts still send from their own alias rather than
    Mail's global "Send new messages from" preference.
    """
    safe_account = escape_applescript(account)
    script = f'''
    tell application "Mail"
        try
            set targetAccount to account "{safe_account}"
            set emailAddrs to email addresses of targetAccount
            if (count of emailAddrs) is 1 then
                return item 1 of emailAddrs
            end if
            return ""
        on error
            return ""
        end try
    end tell
    '''
    result = (run_applescript(script) or "").strip()
    return result or None


def _compose_sender_script(variable, account_ref, sender_override):
    """Return AppleScript that sets the sender for a compose/reply/forward
    outgoing message variable, respecting Mail's account-level defaults.

    With `sender_override` the value is applied unconditionally. Without an
    override, Mail's global composing preference may otherwise win over the
    caller's account choice, so the sender is pinned to the account's only
    alias when the account has a single address, and left untouched for
    multi-alias accounts so the user's Mail preference stays in effect.
    """
    if sender_override:
        safe_sender = escape_applescript(sender_override)
        return f'set sender of {variable} to "{safe_sender}"'
    return (
        f"set emailAddrs to email addresses of {account_ref}\n"
        f"if (count of emailAddrs) is 1 then\n"
        f"    set sender of {variable} to item 1 of emailAddrs\n"
        f"end if"
    )


def _validate_from_address(account, from_address):
    """Return (validated_address, error_message) for a sender override.

    When `from_address` is blank the override is skipped and both values
    are None. Otherwise the candidate is matched case-insensitively
    against the account's configured email addresses, and the original
    casing from Mail is returned on success.
    """
    if from_address is None:
        return None, None
    candidate = from_address.strip()
    if not candidate:
        return None, None
    safe_account = escape_applescript(account)
    script = f'''
    tell application "Mail"
        try
            set targetAccount to account "{safe_account}"
            set emailAddrs to email addresses of targetAccount
            set AppleScript's text item delimiters to linefeed
            set addrText to emailAddrs as text
            set AppleScript's text item delimiters to ""
            return addrText
        on error
            return ""
        end try
    end tell
    '''
    raw = run_applescript(script) or ""
    aliases = [line.strip() for line in raw.splitlines() if line.strip()]
    if not aliases:
        return None, (
            f"Error: Could not read email addresses for account {account!r}."
        )
    lowered = {alias.lower(): alias for alias in aliases}
    match = lowered.get(candidate.lower())
    if not match:
        return None, (
            f"Error: 'from_address' {candidate!r} is not configured on account "
            f"{account!r}. Known addresses: {', '.join(aliases)}"
        )
    return match, None


_CDATA_BLOCK_PATTERN = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)


def _strip_cdata_wrappers(text):
    """Remove XML CDATA section markers from user-provided body content.

    LLM callers occasionally wrap email bodies in `<![CDATA[...]]>`. HTML
    parsers treat the opening `<![CDATA[` as a bogus comment that ends at
    the first `>` in the actual content, so it's invisible — but the
    trailing `]]>` has no preceding `<` and renders as literal text at the
    end of the message. Strip both forms so callers don't have to know.
    """
    if not text:
        return text
    text = _CDATA_BLOCK_PATTERN.sub(r"\1", text)
    return text.replace("<![CDATA[", "").replace("]]>", "")


def _build_html_from_text(text_body):
    """Return a simple HTML wrapper for plain text content."""
    safe_body = html_escape(text_body or "")
    return (
        '<html><body style="font-family: -apple-system, BlinkMacSystemFont, '
        "'Segoe UI', Arial, sans-serif; line-height: 1.45; color: #111111;\">"
        '<pre style="white-space: pre-wrap; font: inherit; margin: 0;">'
        + safe_body
        + "</pre></body></html>"
    )


def _html_to_pasteboard_script(html_temp_path, pb_var="pb", old_clip_var="oldClip"):
    """Return an AppleScriptObjC snippet that loads HTML and places it on the
    general pasteboard as RICH TEXT (RTF) plus a plain-text fallback.

    Why RTF and not raw HTML: writing the HTML *source* under
    ``NSPasteboardTypeHTML`` (the previous approach) leaves Mail's compose
    editor with only an ambiguous ``public.html`` flavor and no plain-text
    representation. For anything other than a complete, well-formed HTML
    document Mail renders a best-effort version AND surfaces the literal
    markup, so the recipient sees the message twice — once rendered, once as
    raw ``<p>``/``<b>`` source. Converting the HTML to an
    ``NSAttributedString`` and writing it back as RTF gives Mail a single,
    unambiguous rich-text flavor it pastes deterministically as one rendered
    body; the accompanying plain-text flavor is the *rendered* text (tags
    stripped), so even a plain-text fallback never shows markup.

    The snippet stores the prior clipboard string in ``old_clip_var`` so the
    caller can restore it, and reads the HTML from ``html_temp_path`` (written
    by the Python caller to avoid AppleScript string-escaping issues).
    """
    return f"""set htmlString to do shell script "cat '{html_temp_path}'"
set {pb_var} to current application's NSPasteboard's generalPasteboard()
set {old_clip_var} to {pb_var}'s stringForType:(current application's NSPasteboardTypeString)
set htmlNSStr to current application's NSString's stringWithString:htmlString
set htmlBytes to htmlNSStr's dataUsingEncoding:(current application's NSUTF8StringEncoding)
-- Pin the HTML importer to UTF-8. Without NSCharacterEncodingDocumentAttribute the
-- Cocoa HTML reader auto-detects the charset and defaults to Latin-1/Windows-1252,
-- so the UTF-8 bytes for ä/ö/ü/ß/emoji get double-decoded into mojibake
-- (e.g. "Grüße" -> "GrÃ¼ÃŸe"). Passing NSUTF8StringEncoding fixes all multibyte text.
set htmlOptKeys to {{current application's NSDocumentTypeDocumentAttribute, current application's NSCharacterEncodingDocumentAttribute}}
set htmlOptVals to {{current application's NSHTMLTextDocumentType, current application's NSUTF8StringEncoding}}
set htmlOpts to current application's NSDictionary's dictionaryWithObjects:htmlOptVals forKeys:htmlOptKeys
set attrStr to current application's NSAttributedString's alloc()'s initWithData:htmlBytes options:htmlOpts documentAttributes:(missing value) |error|:(missing value)
{pb_var}'s clearContents()
if attrStr is not missing value then
    set attrRange to current application's NSMakeRange(0, attrStr's |length|())
    set rtfData to attrStr's RTFFromRange:attrRange documentAttributes:(current application's NSDictionary's dictionary())
    {pb_var}'s setData:rtfData forType:(current application's NSPasteboardTypeRTF)
    {pb_var}'s setString:(attrStr's |string|()) forType:(current application's NSPasteboardTypeString)
else
    -- Conversion failed (malformed HTML): fall back to pasting the raw string
    -- as plain text so the body is never silently empty.
    {pb_var}'s setString:htmlString forType:(current application's NSPasteboardTypeString)
end if"""


def _prepare_rich_bodies(subject, text_body, html_body):
    """Return plain-text and HTML bodies, filling sensible placeholders."""
    plain_body = text_body or ""
    rich_body = html_body or ""

    if not plain_body and not rich_body:
        plain_body = (
            "Draft outline\n\n"
            "- Add recipients\n"
            "- Add the final rich-text content\n"
            "- Review before sending"
        )
        rich_body = _build_html_from_text(plain_body)
        return plain_body, rich_body, ["body"]

    if rich_body and not plain_body:
        plain_body = (
            (subject.strip() + "\n\n" if subject and subject.strip() else "")
            + "This message contains rich HTML content. Open it in Mail for the rendered version."
        )

    if plain_body and not rich_body:
        rich_body = _build_html_from_text(plain_body)

    return plain_body, rich_body, []


_SAVE_AS_DRAFT_UNSUPPORTED_NOTE = (
    "save_as_draft could not be honored: Mail opens a `.eml` file as a read-only message "
    "viewer, not a compose object, so there is no draft for Mail to save here. Use "
    "compose_email(mode=\"draft\") or manage_drafts for a real, sendable HTML draft instead."
)


@mcp.tool()
@inject_preferences
def create_rich_email_draft(
    account: str,
    subject: str = "",
    to: Optional[str] = None,
    text_body: Optional[str] = None,
    html_body: Optional[str] = None,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    output_path: Optional[str] = None,
    open_in_mail: bool = True,
    save_as_draft: bool = False,
    from_address: Optional[str] = None,
    attachments: Optional[str] = None,
) -> str:
    """
    Create a rich-text email draft by generating an unsent `.eml` message and optionally opening it in Mail.

    Use this when you want the message as a file on disk. For a formatted message that has to end up
    in Drafts and stay sendable, use `compose_email(body_html=..., mode="draft")` instead: it hands the
    markup to Mail's `html content` property, which renders it faithfully and keeps the signature.
    Mail opens a `.eml` as a read-only viewer, so this path can never produce a real draft.

    Args:
        account: Account name to use for the sender identity (e.g., "Work", "Oracle")
        subject: Subject line for the draft (optional; defaults to empty)
        to: Optional recipient email address(es), comma-separated for multiple
        text_body: Optional plain-text body. If omitted but html_body is provided, a fallback plain body is generated.
        html_body: Optional HTML body. If omitted but text_body is provided, a basic HTML wrapper is generated.
        cc: Optional CC recipients, comma-separated for multiple
        bcc: Optional BCC recipients, comma-separated for multiple
        output_path: Optional path for the generated `.eml` file
        open_in_mail: If True, open the generated `.eml` in Mail (default: True)
        save_as_draft: Not currently supported. Mail opens a `.eml` as a read-only message
            viewer, not a compose object, so it can never be saved into Drafts this way.
            Passing True is reported honestly in the output rather than silently ignored;
            use `compose_email(mode="draft")` or `manage_drafts` for a real, sendable draft.
        from_address: Optional sender address to stamp into the `.eml` `From:` header. Must be one of the account's configured email addresses. When omitted, Mail fills the account's default "Send new messages from" address on open.
        attachments: Optional file paths to attach, comma-separated. The files are embedded in the `.eml` itself, so they are there when Mail opens it. Paths must be inside your home directory.

    Returns:
        Confirmation with the generated `.eml` path, missing details, and Mail-open/save status
    """
    if not account or not account.strip():
        return "Error: 'account' is required"

    text_body = _strip_cdata_wrappers(text_body)
    html_body = _strip_cdata_wrappers(html_body)

    sender_override, sender_error = _validate_from_address(account, from_address)
    if sender_error:
        return sender_error

    sender_address = sender_override or _account_default_alias_if_single(account)

    recipients_to = _split_addresses(to)
    recipients_cc = _split_addresses(cc)
    recipients_bcc = _split_addresses(bcc)
    plain_body, rich_body, body_missing = _prepare_rich_bodies(
        subject, text_body, html_body
    )

    missing_details = []
    if not subject or not subject.strip():
        missing_details.append("subject")
    if not recipients_to:
        missing_details.append("to")
    missing_details.extend(body_missing)

    attachment_paths: List[str] = []
    if attachments:
        attachment_paths, attachment_error = _validate_attachment_paths(attachments)
        if attachment_error:
            return attachment_error

    message = EmailMessage()
    if subject:
        message["Subject"] = subject
    if sender_address:
        message["From"] = sender_address
    if recipients_to:
        message["To"] = ", ".join(recipients_to)
    if recipients_cc:
        message["Cc"] = ", ".join(recipients_cc)
    if recipients_bcc:
        message["Bcc"] = ", ".join(recipients_bcc)
    message["X-Unsent"] = "1"
    message.set_content(plain_body)
    message.add_alternative(rich_body, subtype="html")

    # Embedding the files in the `.eml` is the only way this path can carry an
    # attachment: the opened message is not a scriptable compose object, so
    # nothing can be attached to it afterwards.
    for path in attachment_paths:
        guessed_type, _ = mimetypes.guess_type(path)
        main_type, _, sub_type = (guessed_type or "application/octet-stream").partition("/")
        with open(path, "rb") as handle:
            message.add_attachment(
                handle.read(),
                maintype=main_type,
                subtype=sub_type or "octet-stream",
                filename=os.path.basename(path),
            )

    draft_path = (
        Path(output_path).expanduser()
        if output_path
        else _default_rich_draft_path(subject)
    )
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_bytes(bytes(message))

    opened = False
    save_requested = open_in_mail and save_as_draft
    if open_in_mail:
        subprocess.run(["open", "-a", "Mail", str(draft_path)], check=True)
        opened = True

    output_lines = ["RICH EMAIL DRAFT", "", "✓ Rich draft prepared successfully!", ""]
    output_lines.append("Account: " + account)
    output_lines.append("Subject: " + (subject if subject else "[empty]"))
    output_lines.append("EML path: " + str(draft_path))
    output_lines.append("Opened in Mail: " + ("yes" if opened else "no"))
    if open_in_mail:
        output_lines.append("Saved in Drafts: no")
        if save_requested:
            output_lines.append("Note: " + _SAVE_AS_DRAFT_UNSUPPORTED_NOTE)
    if sender_address:
        output_lines.append("From: " + sender_address)
    if recipients_to:
        output_lines.append("To: " + ", ".join(recipients_to))
    if recipients_cc:
        output_lines.append("CC: " + ", ".join(recipients_cc))
    if recipients_bcc:
        output_lines.append("BCC: " + ", ".join(recipients_bcc))
    if attachment_paths:
        output_lines.append(
            "Attachments embedded: "
            + ", ".join(os.path.basename(path) for path in attachment_paths)
        )
    output_lines.append(
        "Missing details: "
        + (", ".join(missing_details) if missing_details else "none")
    )
    output_lines.append(
        "Note: this `.eml` opens as a read-only viewer, not a compose window. "
        'Use compose_email(body_html=..., mode="draft") for a formatted draft '
        "you can edit and send from Mail."
    )
    return "\n".join(output_lines)


# --- Mail.app body wrapper (macOS 15+) ------------------------------------
#
# Mail wraps EVERY body it receives through AppleScript in its "share"
# template, whether the body arrives as a `content` property, a later
# `set content`, a `set html content`, or a GUI paste into a scripted compose
# window:
#
#   <div class="Apple-Mail-URLShareUserContentTopClass"><br></div>
#   <div class="Apple-Mail-URLShareWrapperClass" style="position: relative !important;">
#     <blockquote type="cite" style="border-left-style: none; color: inherit;
#                                    padding: inherit; margin: inherit;">
#       ... the body we set ...
#     </blockquote>
#   </div>
#
# Nothing in this package writes that markup, and no ordering of the
# AppleScript calls avoids it — all four routes were measured against
# Mail 16.0 (3864.600.51.1.1) on 2026-09-05 and produced it identically.
# The inline styles neutralise the quote look in clients that honour them,
# but clients that ignore `inherit` (Outlook's Word engine) indent it, and
# clients that collapse `type="cite"` (Gmail) can hide the message behind a
# "..." toggle.  There is no in-process fix; see README "Known Mail.app
# limitations".
#
# What we can prevent is the wrapper STACKING.  Every edit that feeds a
# stored body back through the composer adds another layer, so a draft that
# is edited three times ends up three blockquotes deep.  The helpers below
# peel the existing layers off before a body is reused.

_SHARE_WRAPPER_OPEN = re.compile(
    r'<div\b[^>]*class="[^"]*Apple-Mail-URLShareWrapperClass[^"]*"[^>]*>\s*'
    r'<blockquote\b[^>]*type="cite"[^>]*>',
    re.IGNORECASE,
)
_SHARE_TOP_OPEN = re.compile(
    r'<div\b[^>]*class="[^"]*Apple-Mail-URLShareUserContentTopClass[^"]*"[^>]*>',
    re.IGNORECASE,
)
_MAIL_SIGNATURE_OPEN = re.compile(
    r'<div\b[^>]*id="AppleMailSignature"[^>]*>', re.IGNORECASE
)
_TRAILING_BREAKS = re.compile(r'(?:\s|<br\b[^>]*/?>)+$', re.IGNORECASE)
_MARKUP_ONLY = re.compile(r'<[^>]*>|&nbsp;|\s', re.IGNORECASE)


def _matching_close(html, search_from, tag):
    """Return ``(close_start, close_end)`` of the ``</tag>`` that closes an
    already-consumed ``<tag ...>`` opening.

    ``search_from`` is the index just past that opening tag.  Nesting is
    counted, so an inner ``<blockquote>`` does not end the outer one — which
    is exactly the case a twice-wrapped body produces.  Returns ``None`` when
    the markup is unbalanced; callers then leave the body untouched rather
    than cutting it at the wrong place.
    """
    open_re = re.compile(r"<" + tag + r"\b", re.IGNORECASE)
    close_re = re.compile(r"</" + tag + r"\s*>", re.IGNORECASE)
    depth = 1
    pos = search_from
    while True:
        next_close = close_re.search(html, pos)
        if not next_close:
            return None
        next_open = open_re.search(html, pos)
        if next_open and next_open.start() < next_close.start():
            depth += 1
            pos = next_open.end()
            continue
        depth -= 1
        pos = next_close.end()
        if depth == 0:
            return next_close.start(), next_close.end()


def _has_visible_content(html):
    """True when the fragment holds more than tags and whitespace."""
    return bool(_MARKUP_ONLY.sub("", html or "").strip())


def _strip_mail_share_wrapper(html):
    """Peel Mail's share-template wrapper off a stored body.

    Removes every ``Apple-Mail-URLShareWrapperClass`` /
    ``blockquote type="cite"`` layer and the empty
    ``Apple-Mail-URLShareUserContentTopClass`` div in front of it.  A top div
    that actually carries text is kept — that is where a human typing above
    the wrapper ends up.
    """
    if not html:
        return html

    while True:
        before = html

        top = _SHARE_TOP_OPEN.search(html)
        if top:
            close = _matching_close(html, top.end(), "div")
            if close:
                inner = html[top.end():close[0]]
                replacement = inner if _has_visible_content(inner) else ""
                html = html[:top.start()] + replacement + html[close[1]:]

        wrapper = _SHARE_WRAPPER_OPEN.search(html)
        if wrapper:
            close = _matching_close(html, wrapper.end(), "blockquote")
            if close:
                inner = html[wrapper.end():close[0]]
                tail = html[close[1]:]
                # The </blockquote> is followed by the </div> of the wrapper.
                tail = re.sub(r"^\s*</div\s*>", "", tail, count=1, flags=re.IGNORECASE)
                html = html[:wrapper.start()] + inner + tail

        if html == before:
            return html


def _strip_mail_signature_block(html):
    """Remove the ``<div id="AppleMailSignature">`` block Mail bakes into a
    saved message, together with the ``<br>``s it puts in front of it.

    Reusing a stored body means reusing that baked-in copy.  Stripping it and
    leaving the message's ``message signature`` property alone lets Mail
    attach the live signature again — the recipient gets the real, formatted
    signature and Mail's compose window still shows which one is selected,
    instead of "None".
    """
    if not html:
        return html

    match = _MAIL_SIGNATURE_OPEN.search(html)
    if not match:
        return html
    close = _matching_close(html, match.end(), "div")
    if not close:
        return html

    head = _TRAILING_BREAKS.sub("", html[:match.start()])
    return head + html[close[1]:]


def _send_html_email(
    account: str,
    to: str,
    subject: str,
    body_plain: str,
    body_html: str,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    attachments_script: str = "",
    attachment_info: str = "",
    mode: str = "send",
    sender_override: Optional[str] = None,
) -> str:
    """Send, draft or open an HTML message using Mail's ``html content``.

    ``set html content`` hands Mail the markup verbatim: headings, lists,
    links, inline colours and umlauts all survive byte-for-byte (measured
    2026-09-05 against Mail 16.0/3864.600.51.1.1).  It also leaves the
    message's ``message signature`` property alone, so Mail attaches the
    real, formatted signature and the compose window still names it.

    This replaces the previous clipboard route, which converted the HTML to
    an ``NSAttributedString``, wrote it back as RTF and pasted it into a
    visible compose window with synthetic Cmd+A/Cmd+V keystrokes.  That route
    stole keyboard focus, failed silently whenever Mail did not come to the
    front, and flattened every message to 12px black Helvetica because the
    RTF round-trip discards CSS.

    Two limits remain, both Mail's and both reported to the caller:

    * The body is wrapped in Mail's share template — see the module comment
      above ``_strip_mail_share_wrapper``.  Unavoidable on macOS 15+.
    * Adding an attachment makes Mail re-render the body through its editor,
      which flattens the markup exactly the way the old paste route did.  A
      message without attachments keeps its formatting; one with attachments
      keeps the attachment and loses the CSS.  Setting the body *after* the
      attachment is not an option: that drops the attachment.

    ``body_plain`` is accepted for signature compatibility but unused: a saved
    draft's ``text/plain`` alternative comes out empty whether or not
    ``content`` is set first (measured both ways), and Mail regenerates the
    alternative when the message is actually sent.
    """
    safe_account = escape_applescript(account)
    escaped_subject = escape_applescript(subject)

    # Build recipient scripts
    to_lines = ""
    for addr in [a.strip() for a in to.split(",") if a.strip()]:
        to_lines += f'make new to recipient at end of to recipients with properties {{address:"{escape_applescript(addr)}"}}\n'

    cc_lines = ""
    if cc:
        for addr in [a.strip() for a in cc.split(",") if a.strip()]:
            cc_lines += f'make new cc recipient at end of cc recipients with properties {{address:"{escape_applescript(addr)}"}}\n'

    bcc_lines = ""
    if bcc:
        for addr in [a.strip() for a in bcc.split(",") if a.strip()]:
            bcc_lines += f'make new bcc recipient at end of bcc recipients with properties {{address:"{escape_applescript(addr)}"}}\n'

    sender_script = _compose_sender_script(
        "newMsg", f'account "{safe_account}"', sender_override
    )

    if mode == "send":
        visible = "false"
        final_command = "send newMsg"
        success_text = "Email sent successfully (HTML)"
    elif mode == "draft":
        # Close the message object, never `window 1`: the object owns no
        # window here, so `close window 1` would close (and silently save)
        # whatever the user had open instead.
        visible = "false"
        final_command = "close newMsg saving yes"
        success_text = "Email saved as draft (HTML)"
    else:  # open
        visible = "true"
        final_command = "activate"
        success_text = (
            "Email opened in Mail for review (HTML). Edit and send when ready."
        )

    # The HTML goes through a temp file rather than an AppleScript string
    # literal: no escaping of quotes or backslashes, no length ceiling, and
    # `read ... as «class utf8»` decodes multibyte text (ä/ö/ü/ß, emoji)
    # correctly where a naive read would fall back to MacRoman.
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".html",
        prefix="mail_html_",
        delete=False,
        encoding="utf-8",
    )
    tmp.write(body_html)
    tmp.close()
    html_temp_path = tmp.name

    # Body first, attachments after: `set html content` replaces the whole
    # body and would drop an attachment added beforehand.
    if attachments_script.strip():
        attachments_block = (
            "    tell newMsg\n"
            f"        {attachments_script}\n"
            "    end tell"
        )
    else:
        attachments_block = "    -- (no attachments)"

    script = f'''
tell application "Mail"
    set htmlBody to (read (POSIX file "{escape_applescript(html_temp_path)}") as «class utf8»)
    set newMsg to make new outgoing message with properties {{subject:"{escaped_subject}", visible:{visible}}}
    {sender_script}
    tell newMsg
        {to_lines}
        {cc_lines}
        {bcc_lines}
    end tell
    set html content of newMsg to htmlBody
{attachments_block}
    {final_command}
    return "{success_text}"
end tell
'''

    # Each attachment carries its own `delay 1`, so the budget grows with them.
    timeout = 120 + 5 * max(0, attachments_script.count("make new attachment"))

    try:
        output = run_applescript(script, timeout=timeout)
    except Exception as exc:  # osascript failure or timeout
        verb = {"send": "sending", "draft": "saving"}.get(mode, "opening")
        return f"Error {verb} HTML email: {exc}"
    finally:
        if os.path.exists(html_temp_path):
            os.unlink(html_temp_path)

    if output.startswith("Error"):
        return output

    confirm = f"{output}\n\nFrom: {account}\nTo: {to}\nSubject: {subject}"
    if cc:
        confirm += f"\nCC: {cc}"
    if bcc:
        confirm += f"\nBCC: {bcc}"
    if attachment_info:
        confirm += f"\nAttachments:\n{attachment_info.rstrip()}"
        confirm += (
            "\nNote: Mail re-renders the body when an attachment is added, "
            "which flattens HTML formatting. Send without attachments to keep "
            "the styling, or attach the file by hand in Mail."
        )
    return confirm


def _locate_saved_draft(subject: str) -> Optional[Tuple[str, int]]:
    """Return (account_name, attachment_count) for the draft with this subject.

    Mail decides itself which account a draft belongs to — it follows the
    sender address, not the account the caller named, so a draft can land in a
    different account's Drafts when two accounts share an address. Callers
    report the real location instead of claiming success blindly.

    Returns None when no draft with that exact subject exists anywhere.
    """
    if not subject:
        return None
    safe_subject = escape_applescript(subject)
    script = f'''
    tell application "Mail"
        set foundLine to ""
        repeat with anAccount in accounts
            if foundLine is "" then
                repeat with aMailbox in mailboxes of anAccount
                    if foundLine is "" and (name of aMailbox) is "Drafts" then
                        -- `whose` filters inside Mail; walking every draft over
                        -- Apple Events costs seconds on a busy Drafts folder.
                        set matches to (messages of aMailbox whose subject is "{safe_subject}")
                        if (count of matches) > 0 then
                            set attachmentCount to 0
                            try
                                set attachmentCount to count of mail attachments of (item 1 of matches)
                            end try
                            set foundLine to (name of anAccount) & "|||" & attachmentCount
                        end if
                    end if
                end repeat
            end if
        end repeat
        return foundLine
    end tell
    '''
    raw = ""
    for attempt in range(4):
        try:
            raw = (run_applescript(script) or "").strip()
        except Exception:
            return None
        if raw:
            break
        # An empty answer means the draft is not in the mailbox yet: Mail
        # writes it asynchronously and a freshly saved draft can take a moment
        # to appear (measured: up to ~4 s). Any non-empty answer is final.
        if attempt < 3:
            time.sleep(1.5)
    if "|||" not in raw:
        return None
    account_name, _, count_text = raw.rpartition("|||")
    try:
        return account_name, int(count_text)
    except ValueError:
        return account_name, 0


def _draft_location_note(subject: str, expected_attachments: int = 0) -> str:
    """Return report lines stating where a draft landed and what it carries."""
    located = _locate_saved_draft(subject)
    if located is None:
        return (
            "\n⚠ Draft not found in any Drafts mailbox after saving. "
            "Check Mail before assuming it exists."
        )
    account_name, attachment_count = located
    lines = [f"\nSaved in: {account_name}/Drafts"]
    if expected_attachments:
        lines.append(
            f"Attachments in draft: {attachment_count} of {expected_attachments}"
        )
        if attachment_count < expected_attachments:
            lines.append(
                "⚠ Mail did not keep every attachment. Re-attach before sending."
            )
    return "\n".join(lines)


# Header line that introduces the quoted original in a plain-text reply.
# Mail.app writes this in the system language; Robin's Mail runs German, so
# German is the default here. One line to change for another language.
REPLY_QUOTE_HEADER = "Am {date} schrieb {sender}:"

# Upper bound for the quoted original. Newsletters and digests can carry
# hundreds of kilobytes; quoting all of it would bloat every reply.
REPLY_QUOTE_LIMIT = 20000


def _build_quoted_reply(
    reply_body: str,
    sender: str,
    date_text: str,
    original_content: str,
    limit: int = REPLY_QUOTE_LIMIT,
) -> str:
    """Return the full plain-text reply body including the quoted original.

    Mail builds its own rich quote only in the GUI layer. Setting `content`
    on the reply message replaces that layer, so the quote has to be rebuilt
    here — that is the price for a reply body that lands deterministically
    instead of depending on a Cmd+V into a window that may not have focus.
    """
    body = (reply_body or "").rstrip("\n")
    original = (original_content or "").replace("\r\n", "\n").replace("\r", "\n")
    # Marketing mails pad their preview text with hundreds of zero-width
    # characters and object-replacement marks. Quoted verbatim they turn the
    # reply into a wall of invisible junk.
    for junk in ("\u200b", "\u200c", "\u200d", "\u2060", "\ufeff", "\ufffc"):
        original = original.replace(junk, "")
    original = "\n".join(line.rstrip() for line in original.split("\n"))
    original = original.strip()

    if not original:
        return body + "\n\n"

    truncated = False
    if len(original) > limit:
        original = original[:limit].rstrip()
        truncated = True

    quoted_lines = []
    for line in original.split("\n"):
        quoted_lines.append("> " + line if line else ">")
    if truncated:
        quoted_lines.append("> [...]")
    quoted = "\n".join(quoted_lines)

    header = REPLY_QUOTE_HEADER.format(date=date_text, sender=sender)
    return f"{body}\n\n{header}\n\n{quoted}\n"


def _find_reply_target(account: str, mailbox: str, subject_keyword: str):
    """Return (fields, error) for the first message matching *subject_keyword*.

    fields is a dict with id, subject, sender, date and content of the
    original message; error is a ready-to-return message when nothing
    matched or Mail refused the lookup.
    """
    separator = "<<<AMMCP-" + os.urandom(8).hex() + ">>>"
    safe_account = escape_applescript(account)
    safe_keyword = escape_applescript(subject_keyword)
    script = f'''
    tell application "Mail"
        try
            set targetAccount to account "{safe_account}"
            {build_mailbox_ref(mailbox, account_var="targetAccount", var_name="searchMailbox")}
            -- `whose` filters inside Mail instead of pulling every message
            -- over Apple Events: measured on a 1299-message archive, the
            -- element-by-element loop took over 100 s and timed out, the
            -- `whose` clause 3.4 s.
            set matchingMessages to (messages of searchMailbox whose subject contains "{safe_keyword}")
            set matchCount to count of matchingMessages
            if matchCount is 0 then
                return ""
            end if

            -- Reply to the NEWEST match, not to whatever the mailbox happens to
            -- list first: with several messages in a thread the latest one is
            -- what "reply to that mail" means. Scanning is capped so a keyword
            -- that matches hundreds of messages cannot stall the call.
            set scanLimit to matchCount
            if scanLimit > 100 then set scanLimit to 100
            set foundMessage to item 1 of matchingMessages
            set foundDate to date received of foundMessage
            repeat with scanIndex from 2 to scanLimit
                try
                    set candidate to item scanIndex of matchingMessages
                    set candidateDate to date received of candidate
                    if candidateDate > foundDate then
                        set foundMessage to candidate
                        set foundDate to candidateDate
                    end if
                end try
            end repeat

            set originalContent to ""
            try
                set originalContent to (content of foundMessage) as text
            end try

            return ((id of foundMessage) as text) & "{separator}" & ¬
                (subject of foundMessage) & "{separator}" & ¬
                (sender of foundMessage) & "{separator}" & ¬
                ((date received of foundMessage) as string) & "{separator}" & ¬
                (matchCount as text) & "{separator}" & ¬
                originalContent
        on error errMsg
            return "ERROR{separator}" & errMsg
        end try
    end tell
    '''
    raw = run_applescript(script, timeout=180) or ""
    if not raw.strip():
        return None, (
            f"No email found matching: {subject_keyword} "
            f"(searched mailbox: {mailbox} of account {account})"
        )
    parts = raw.split(separator)
    if parts[0] == "ERROR":
        return None, "Error: " + (parts[1] if len(parts) > 1 else "unknown")
    if len(parts) < 6:
        return None, "Error: unexpected reply lookup output from Mail."
    try:
        match_count = int(parts[4].strip())
    except ValueError:
        match_count = 1
    return (
        {
            "id": parts[0].strip(),
            "subject": parts[1],
            "sender": parts[2],
            "date": parts[3],
            "match_count": match_count,
            "content": separator.join(parts[5:]),
        },
        None,
    )



def _reply_plain(
    account: str,
    mailbox: str,
    subject_keyword: str,
    reply_body: str,
    reply_to_all: bool,
    cc: Optional[str],
    bcc: Optional[str],
    effective_mode: str,
    attachments: Optional[str],
    sender_override: Optional[str],
) -> str:
    """Reply without driving Mail's GUI.

    The clipboard path (see reply_to_email) inserts the body with a blind
    Cmd+V into the compose window. When Mail cannot come to the front — the
    screen is locked, another Space is active, another app holds focus — the
    keystroke lands somewhere else and the reply is saved or sent with an
    EMPTY body, without any error. Measured on 25.08.2026: the resulting
    draft carried correct In-Reply-To/References headers and no body at all.

    This path sets `content` directly instead, which costs Mail's rich quote
    of the original (setting `content` replaces that layer) and therefore
    rebuilds the quote as plain text. Trade: a plain quote instead of a rich
    one, in exchange for a body that is always there.
    """
    fields, error = _find_reply_target(account, mailbox, subject_keyword)
    if error:
        return error

    attachment_script = ""
    attachment_info = ""
    validated_paths: List[str] = []
    if attachments:
        validated_paths, attachment_error = _validate_attachment_paths(attachments)
        if attachment_error:
            return attachment_error
        for path in validated_paths:
            safe_path = escape_applescript(path)
            attachment_script += f'''
                set theFile to POSIX file "{safe_path}"
                make new attachment with properties {{file name:theFile}} at after the last paragraph
                delay 1
            '''
            attachment_info += f"  {path}\n"

    full_body = _build_quoted_reply(
        reply_body, fields["sender"], fields["date"], fields["content"]
    )

    body_tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        prefix="mail_reply_plain_",
        delete=False,
        encoding="utf-8",
    )
    body_tmp.write(full_body)
    body_tmp.close()
    body_temp_path = body_tmp.name

    safe_account = escape_applescript(account)
    separator = "<<<AMMCP-" + os.urandom(8).hex() + ">>>"
    reply_command = "set replyMessage to reply foundMessage without opening window"
    if reply_to_all:
        reply_command += " and reply to all"

    recipient_script = ""
    for addr in _split_addresses(cc):
        recipient_script += (
            "make new cc recipient at end of cc recipients of replyMessage "
            f'with properties {{address:"{escape_applescript(addr)}"}}\n            '
        )
    for addr in _split_addresses(bcc):
        recipient_script += (
            "make new bcc recipient at end of bcc recipients of replyMessage "
            f'with properties {{address:"{escape_applescript(addr)}"}}\n            '
        )

    sender_script = _compose_sender_script(
        "replyMessage", "targetAccount", sender_override
    )

    if effective_mode == "send":
        final_action = "send replyMessage"
        success_text = "Reply sent successfully!"
    elif effective_mode == "open":
        final_action = "set visible of replyMessage to true\n            activate"
        success_text = "Reply opened in Mail for review. Edit and send when ready."
    else:
        # `save` commits the reply to Drafts. Never `close window 1` — that
        # closes whatever window Mail has in front, which used to save and
        # close the user's own open message instead of this reply.
        final_action = "save replyMessage"
        success_text = "Reply saved as draft!"

    script = f'''
    tell application "Mail"
        try
            set targetAccount to account "{safe_account}"
            {build_mailbox_ref(mailbox, account_var="targetAccount", var_name="searchMailbox")}
            set candidates to (messages of searchMailbox whose id is {int(fields["id"])})
            if (count of candidates) is 0 then
                return "Error: the original message disappeared between lookup and reply."
            end if
            set foundMessage to item 1 of candidates

            {reply_command}
            delay 0.3

            {sender_script}

            {recipient_script}

            -- Body first, attachments after: setting `content` replaces the
            -- whole body and would drop an attachment added beforehand.
            set replyBodyText to do shell script "cat " & quoted form of "{body_temp_path}"
            set content of replyMessage to replyBodyText

            tell replyMessage
                {attachment_script}
            end tell

            set replySubject to ""
            try
                set replySubject to subject of replyMessage
            end try

            {final_action}

            return "{success_text}" & "{separator}" & replySubject
        on error errMsg
            return "Error: " & errMsg
        end try
    end tell
    '''

    try:
        result = run_applescript(script, timeout=180)
    finally:
        if os.path.exists(body_temp_path):
            os.unlink(body_temp_path)

    if result.startswith("Error:"):
        return result

    status, _, reply_subject = result.partition(separator)
    reply_subject = reply_subject.strip() or ("Re: " + fields["subject"])

    lines = [
        "REPLY",
        "",
        status.strip(),
        "To: " + fields["sender"],
        "Subject: " + reply_subject,
        "Original from: " + fields["date"] + " (mailbox: " + mailbox + ")",
    ]
    if fields.get("match_count", 1) > 1:
        lines.append(
            f"Note: {fields['match_count']} messages matched "
            f"{subject_keyword!r}; replied to the newest one."
        )
    if cc:
        lines.append("CC: " + cc)
    if bcc:
        lines.append("BCC: " + bcc)
    if attachment_info:
        lines.append("Attachments:\n" + attachment_info.rstrip())

    output = "\n".join(lines)
    if effective_mode == "draft":
        output += _draft_location_note(reply_subject, len(validated_paths))
    return output


def _read_draft(draft_subject: str, account: Optional[str] = None):
    """Return (fields, error) for the first draft matching *draft_subject*.

    Searches every account's Drafts mailbox, preferring *account* when given:
    Mail files a draft by sender address, so it regularly ends up in a
    different account than the one the caller named when creating it.
    """
    separator = "<<<AMMCP-" + os.urandom(8).hex() + ">>>"
    safe_subject = escape_applescript(draft_subject)
    preferred = escape_applescript(account) if account else ""
    script = f'''
    tell application "Mail"
        set orderedAccounts to {{}}
        repeat with anAccount in accounts
            if "{preferred}" is not "" and (name of anAccount) is "{preferred}" then
                set beginning of orderedAccounts to anAccount
            else
                set end of orderedAccounts to anAccount
            end if
        end repeat

        repeat with anAccount in orderedAccounts
            try
                set draftsMailbox to mailbox "Drafts" of anAccount
                set matches to (messages of draftsMailbox whose subject contains "{safe_subject}")
                if (count of matches) > 0 then
                    set theDraft to item 1 of matches

                    set toList to ""
                    try
                        repeat with aRecipient in to recipients of theDraft
                            set toList to toList & (address of aRecipient) & ","
                        end repeat
                    end try
                    set ccList to ""
                    try
                        repeat with aRecipient in cc recipients of theDraft
                            set ccList to ccList & (address of aRecipient) & ","
                        end repeat
                    end try
                    set bccList to ""
                    try
                        repeat with aRecipient in bcc recipients of theDraft
                            set bccList to bccList & (address of aRecipient) & ","
                        end repeat
                    end try
                    set attachmentList to ""
                    try
                        repeat with anAttachment in mail attachments of theDraft
                            set attachmentList to attachmentList & (name of anAttachment) & ","
                        end repeat
                    end try
                    set senderAddress to ""
                    try
                        set senderAddress to sender of theDraft
                    end try
                    set draftContent to ""
                    try
                        set draftContent to (content of theDraft) as text
                    end try

                    return ((id of theDraft) as text) & "{separator}" & ¬
                        (name of anAccount) & "{separator}" & ¬
                        (subject of theDraft) & "{separator}" & ¬
                        toList & "{separator}" & ccList & "{separator}" & bccList & "{separator}" & ¬
                        attachmentList & "{separator}" & senderAddress & "{separator}" & draftContent
                end if
            end try
        end repeat
        return ""
    end tell
    '''
    raw = run_applescript(script, timeout=180) or ""
    if not raw.strip():
        return None, f"Error: No draft found matching: {draft_subject}"
    parts = raw.split(separator)
    if len(parts) < 9:
        return None, "Error: unexpected draft lookup output from Mail."

    def _addresses(value):
        return [item.strip() for item in value.split(",") if item.strip()]

    return (
        {
            "id": parts[0].strip(),
            "account": parts[1],
            "subject": parts[2],
            "to": _addresses(parts[3]),
            "cc": _addresses(parts[4]),
            "bcc": _addresses(parts[5]),
            "attachments": _addresses(parts[6]),
            "sender": parts[7].strip(),
            "content": separator.join(parts[8:]),
        },
        None,
    )


def _draft_html_body(draft_id: str, account: str) -> Optional[str]:
    """Return the ``text/html`` part of a stored draft, or ``None``.

    ``_read_draft`` goes through ``content of theDraft``, which is Mail's
    *rendered* plain text: formatting, links and the whole signature block
    are already gone by the time the caller sees it.  Rebuilding a draft from
    that string is what turned an edited message into flat text with a
    plain-text signature.  ``source of theDraft`` returns the raw RFC 822
    message instead, so the real HTML body can be recovered and handed back
    to Mail verbatim.
    """
    # Mail's message id is numeric. Anything else is not a valid identifier
    # and has no business being interpolated into the script unquoted.
    numeric_id = str(draft_id).strip()
    if not numeric_id.isdigit():
        return None

    script = f'''
    tell application "Mail"
        try
            set theDraft to first message of mailbox "Drafts" of account "{escape_applescript(account)}" whose id is {numeric_id}
            return source of theDraft
        on error
            return ""
        end try
    end tell
    '''
    try:
        raw = run_applescript(script, timeout=180)
    except Exception:
        return None
    if not raw or not raw.strip():
        return None

    try:
        parsed = email.message_from_string(raw)
    except Exception:
        return None

    for part in parsed.walk():
        if part.get_content_type() != "text/html":
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            return payload.decode(charset, errors="replace")
        except LookupError:
            return payload.decode("utf-8", errors="replace")
    return None


def _export_draft_attachments(draft_id: str, account: str, names: List[str]):
    """Save the named attachments of a draft to a private cache directory.

    Re-attaching is the only way to keep an attachment through an edit: Mail
    cannot modify a stored draft in place, so the draft is rebuilt and every
    kept file has to come from disk again.
    """
    if not names:
        return [], None
    export_dir = (
        Path.home() / "Library" / "Caches" / "apple-mail-mcp" / "draft-edit" / draft_id
    )
    if export_dir.exists():
        for stale in export_dir.iterdir():
            try:
                stale.unlink()
            except OSError:
                pass
    export_dir.mkdir(parents=True, exist_ok=True)

    safe_account = escape_applescript(account)
    safe_dir = escape_applescript(str(export_dir))
    wanted_list = ", ".join(f'"{escape_applescript(n)}"' for n in names)
    script = f'''
    tell application "Mail"
        try
            set draftsMailbox to mailbox "Drafts" of account "{safe_account}"
            set matches to (messages of draftsMailbox whose id is {int(draft_id)})
            if (count of matches) is 0 then
                return "ERROR: draft vanished before its attachments could be saved"
            end if
            set theDraft to item 1 of matches
            set wantedNames to {{{wanted_list}}}
            set savedNames to ""
            repeat with anAttachment in mail attachments of theDraft
                set attachmentName to name of anAttachment
                if wantedNames contains attachmentName then
                    try
                        save anAttachment in POSIX file ("{safe_dir}/" & attachmentName)
                        set savedNames to savedNames & attachmentName & linefeed
                    end try
                end if
            end repeat
            return savedNames
        on error errMsg
            return "ERROR: " & errMsg
        end try
    end tell
    '''
    result = run_applescript(script, timeout=180) or ""
    if result.startswith("ERROR:"):
        return [], "Error: " + result[len("ERROR:"):].strip()

    saved = []
    for name in result.splitlines():
        name = name.strip()
        if not name:
            continue
        candidate = export_dir / name
        if candidate.is_file():
            saved.append(str(candidate))
    missing = [n for n in names if not (export_dir / n).is_file()]
    if missing:
        return saved, (
            "Error: could not extract these existing attachments, refusing to "
            "rebuild the draft and lose them: " + ", ".join(missing)
        )
    return saved, None


def _discard_draft_export(draft_id: str) -> None:
    """Remove the temporary attachment copies made for a draft edit."""
    export_dir = (
        Path.home() / "Library" / "Caches" / "apple-mail-mcp" / "draft-edit" / draft_id
    )
    if not export_dir.exists():
        return
    for leftover in export_dir.iterdir():
        try:
            leftover.unlink()
        except OSError:
            pass
    try:
        export_dir.rmdir()
    except OSError:
        pass


def _matches_any(name: str, patterns: List[str]) -> bool:
    lowered = name.lower()
    return any(pattern.lower() in lowered for pattern in patterns)


def _validate_attachment_paths(attachments: str) -> Tuple[List[str], Optional[str]]:
    """Validate and resolve attachment file paths.

    Splits comma-separated paths, expands tildes, resolves symlinks,
    and enforces security constraints (home-dir-only, no sensitive dirs,
    file must exist).

    Returns:
        A tuple of (resolved_paths, error_message).
        If error_message is not None, resolved_paths should be ignored.
    """
    home_dir = os.path.expanduser("~")
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

    resolved_paths: List[str] = []
    raw_paths = [p.strip() for p in attachments.split(",")]

    for raw_path in raw_paths:
        if not raw_path:
            continue

        # Expand tilde and resolve symlinks
        expanded = os.path.expanduser(raw_path)
        resolved = os.path.realpath(expanded)

        # Must be under the user's home directory
        if not resolved.startswith(home_dir + os.sep) and resolved != home_dir:
            return (
                [],
                f"Error: Attachment path must be under your home directory ({home_dir}). Got: {resolved}",
            )

        # Block sensitive directories
        for sensitive_dir in sensitive_dirs:
            if resolved.startswith(sensitive_dir + os.sep) or resolved == sensitive_dir:
                return (
                    [],
                    f"Error: Cannot attach files from sensitive directory: {sensitive_dir}",
                )

        # File must exist
        if not os.path.isfile(resolved):
            return [], f"Error: Attachment file does not exist: {resolved}"

        resolved_paths.append(resolved)

    if not resolved_paths:
        return [], "Error: No valid attachment paths provided."

    return resolved_paths, None


def _draft_id_for_subject(subject: str, exclude_id: Optional[str] = None) -> Optional[str]:
    """Return the id of a draft with this exact subject, ignoring *exclude_id*."""
    safe_subject = escape_applescript(subject)
    exclude = int(exclude_id) if exclude_id and exclude_id.isdigit() else -1
    script = f'''
    tell application "Mail"
        repeat with anAccount in accounts
            try
                set draftsMailbox to mailbox "Drafts" of anAccount
                repeat with aDraft in (messages of draftsMailbox whose subject is "{safe_subject}")
                    if (id of aDraft) is not {exclude} then
                        return (id of aDraft) as text
                    end if
                end repeat
            end try
        end repeat
        return ""
    end tell
    '''
    result = (run_applescript(script, timeout=120) or "").strip()
    return result or None


def _delete_draft_by_id(draft_id: str, account: str) -> bool:
    """Delete one draft by id. Returns True when it is gone afterwards."""
    safe_account = escape_applescript(account)
    script = f'''
    tell application "Mail"
        try
            set draftsMailbox to mailbox "Drafts" of account "{safe_account}"
            set matches to (messages of draftsMailbox whose id is {int(draft_id)})
            if (count of matches) is 0 then
                return "gone"
            end if
            set theDraft to item 1 of matches
            set doomedSubject to subject of theDraft
            delete theDraft

            -- Silence the compose object Mail would autosave back into Drafts
            -- a few seconds later; see the same guard in manage_drafts delete.
            set liveComposes to outgoing messages
            repeat with composeIndex from (count of liveComposes) to 1 by -1
                try
                    set aCompose to item composeIndex of liveComposes
                    if (visible of aCompose) is false and (subject of aCompose) is doomedSubject then
                        close aCompose saving no
                    end if
                end try
            end repeat
            delay 0.5
            set stillThere to (messages of draftsMailbox whose id is {int(draft_id)})
            if (count of stillThere) is 0 then
                return "gone"
            end if
            return "still there"
        on error errMsg
            return "error: " & errMsg
        end try
    end tell
    '''
    return (run_applescript(script, timeout=120) or "").strip() == "gone"


def _update_draft(
    account: str,
    draft_subject: str,
    subject: Optional[str] = None,
    to: Optional[str] = None,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    body: Optional[str] = None,
    attachments: Optional[str] = None,
    remove_attachments: Optional[str] = None,
) -> str:
    """Rewrite an existing draft with changed fields and attachments.

    Mail's scripting interface cannot modify a stored draft, so the draft is
    read, rebuilt as a new message and only then is the old one deleted. The
    old draft stays untouched until the replacement is confirmed to exist.

    When the body is not being changed, the rebuild reuses the stored HTML
    (via ``_draft_html_body``) rather than Mail's plain-text rendering, minus
    the share wrapper and the baked-in signature copy. Formatting and the
    signature survive the edit, and the wrapper does not gain a layer each
    time. If the HTML cannot be recovered the old plain-text rebuild is used
    and the return value says so.
    """
    existing, error = _read_draft(draft_subject, account)
    if error:
        return error

    keep_names = list(existing["attachments"])
    removed_names: List[str] = []
    if remove_attachments:
        patterns = [p.strip() for p in remove_attachments.split(",") if p.strip()]
        if patterns == ["all"]:
            removed_names = keep_names
            keep_names = []
        else:
            removed_names = [n for n in keep_names if _matches_any(n, patterns)]
            keep_names = [n for n in keep_names if n not in removed_names]
            unmatched = [
                p for p in patterns
                if not any(p.lower() in n.lower() for n in existing["attachments"])
            ]
            if unmatched:
                return (
                    "Error: no attachment matches "
                    + ", ".join(repr(u) for u in unmatched)
                    + ". Draft left untouched. Present: "
                    + (", ".join(existing["attachments"]) or "none")
                )

    new_paths: List[str] = []
    if attachments:
        new_paths, attachment_error = _validate_attachment_paths(attachments)
        if attachment_error:
            return attachment_error

    kept_paths, export_error = _export_draft_attachments(
        existing["id"], existing["account"], keep_names
    )
    if export_error:
        return export_error

    new_subject = subject if subject is not None else existing["subject"]
    recipients_to = (
        _split_addresses(to) if to is not None else existing["to"]
    )
    recipients_cc = (
        _split_addresses(cc) if cc is not None else existing["cc"]
    )
    recipients_bcc = (
        _split_addresses(bcc) if bcc is not None else existing["bcc"]
    )

    reuse_content = body is None

    # Reusing the body must not mean reusing Mail's plain-text rendering of
    # it. Pull the real HTML out of the stored message, peel off the share
    # wrapper Mail added the last time round (it would otherwise nest one
    # layer deeper on every edit) and drop the baked-in signature copy so
    # Mail can attach the live one again.
    reused_html = None
    if reuse_content:
        raw_html = _draft_html_body(existing["id"], existing["account"])
        if raw_html:
            candidate = _strip_mail_signature_block(
                _strip_mail_share_wrapper(raw_html)
            )
            if _has_visible_content(candidate):
                reused_html = candidate

    if reused_html is not None:
        new_body = reused_html
    elif reuse_content:
        new_body = existing["content"]
    else:
        new_body = body

    body_tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".html" if reused_html is not None else ".txt",
        prefix="mail_draft_edit_",
        delete=False,
        encoding="utf-8",
    )
    body_tmp.write(new_body or "")
    body_tmp.close()
    body_temp_path = body_tmp.name

    recipient_script = ""
    for address in recipients_to:
        recipient_script += (
            "make new to recipient at end of to recipients with properties "
            f'{{address:"{escape_applescript(address)}"}}\n                '
        )
    for address in recipients_cc:
        recipient_script += (
            "make new cc recipient at end of cc recipients with properties "
            f'{{address:"{escape_applescript(address)}"}}\n                '
        )
    for address in recipients_bcc:
        recipient_script += (
            "make new bcc recipient at end of bcc recipients with properties "
            f'{{address:"{escape_applescript(address)}"}}\n                '
        )

    attachment_script = ""
    for path in kept_paths + new_paths:
        attachment_script += f'''
                set theFile to POSIX file "{escape_applescript(path)}"
                make new attachment with properties {{file name:theFile}} at after the last paragraph
                delay 1
        '''

    if reused_html is not None:
        # The signature was cut out of the reused HTML above, so Mail must
        # attach the live one — leave `message signature` alone. Killing it
        # (what this path used to do unconditionally) is what stripped the
        # X-Apple-Mail-Signature header and made Mail's compose window report
        # "Signature: None" on every edited draft.
        signature_script = ""
        create_properties = (
            f'{{subject:"{escape_applescript(new_subject)}", visible:false}}'
        )
        # Body before attachments: `set html content` replaces the whole body
        # and would drop a file attached beforehand.
        body_script = "set html content of newDraft to draftBodyText"
    else:
        # Plain-text fallback: the reused string already carries a flattened
        # copy of the signature, so letting Mail append its own would show it
        # twice.
        signature_script = (
            "set message signature of newDraft to missing value"
            if reuse_content
            else ""
        )
        create_properties = (
            f'{{subject:"{escape_applescript(new_subject)}", '
            "content:draftBodyText, visible:false}"
        )
        body_script = ""

    sender_script = (
        f'set sender of newDraft to "{escape_applescript(existing["sender"])}"'
        if existing["sender"]
        else ""
    )

    script = f'''
    tell application "Mail"
        try
            set draftBodyText to (read (POSIX file "{escape_applescript(body_temp_path)}") as «class utf8»)
            set newDraft to make new outgoing message with properties {create_properties}
            {sender_script}
            {signature_script}

            tell newDraft
                {recipient_script}
            end tell

            {body_script}

            tell newDraft
                {attachment_script}
            end tell

            close newDraft saving yes
            return "ok"
        on error errMsg
            return "Error: " & errMsg
        end try
    end tell
    '''

    try:
        result = run_applescript(script, timeout=180)
    finally:
        if os.path.exists(body_temp_path):
            os.unlink(body_temp_path)

    if result.startswith("Error:"):
        return result + "\nThe original draft was left untouched."

    replacement_id = None
    for _ in range(5):
        replacement_id = _draft_id_for_subject(new_subject, exclude_id=existing["id"])
        if replacement_id:
            break
        time.sleep(1.5)

    if not replacement_id:
        return (
            "Error: the rewritten draft did not turn up in Drafts. The original "
            f"draft {existing['subject']!r} was left untouched — check Mail before retrying."
        )

    deleted = _delete_draft_by_id(existing["id"], existing["account"])

    # The extracted copies have served their purpose; leaving them behind would
    # pile up a second copy of every attachment ever edited.
    _discard_draft_export(existing["id"])

    lines = [
        "UPDATING DRAFT",
        "",
        "✓ Draft rewritten.",
        "Subject: " + new_subject,
        "To: " + (", ".join(recipients_to) or "[none]"),
    ]
    if recipients_cc:
        lines.append("CC: " + ", ".join(recipients_cc))
    if recipients_bcc:
        lines.append("BCC: " + ", ".join(recipients_bcc))
    if not reuse_content:
        lines.append("Body: replaced")
    elif reused_html is not None:
        lines.append("Body: unchanged (HTML formatting and signature kept)")
    else:
        lines.append(
            "Body: unchanged (plain text — the stored HTML could not be read, "
            "so formatting and the signature link are lost)"
        )
    if removed_names:
        lines.append("Removed attachments: " + ", ".join(removed_names))
    if new_paths:
        lines.append(
            "Added attachments: " + ", ".join(os.path.basename(p) for p in new_paths)
        )
    if keep_names:
        lines.append("Kept attachments: " + ", ".join(keep_names))
    if reused_html is not None and (kept_paths or new_paths):
        lines.append(
            "Note: Mail re-renders the body when an attachment is added, so "
            "the HTML formatting of this draft is flattened. The signature "
            "link survives; the styling does not."
        )
    if not deleted:
        lines.append(
            "⚠ The old version could not be deleted and is still in Drafts. "
            "Remove it in Mail so you do not send the outdated one."
        )
    output = "\n".join(lines)
    output += _draft_location_note(new_subject, len(kept_paths) + len(new_paths))
    return output


@mcp.tool()
@inject_preferences
def reply_to_email(
    account: str,
    subject_keyword: str,
    reply_body: str,
    mailbox: str = "INBOX",
    reply_to_all: bool = False,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    send: bool = True,
    mode: Optional[str] = None,
    attachments: Optional[str] = None,
    body_html: Optional[str] = None,
    from_address: Optional[str] = None,
) -> str:
    """
    Reply to an email matching a subject keyword.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        subject_keyword: Keyword to search for in email subjects
        reply_body: The body text of the reply
        mailbox: Mailbox to search the original message in (default: "INBOX"). Use e.g. "Archive" to reply to an already archived message; nested mailboxes use "/" (e.g. "Projects/2026").
        reply_to_all: If True, reply to all recipients; if False, reply only to sender (default: False)
        cc: Optional CC recipients, comma-separated for multiple
        bcc: Optional BCC recipients, comma-separated for multiple
        send: If True (default), send immediately; if False, save as draft. Ignored if mode is set.
        mode: Delivery mode — "send" (send immediately), "draft" (save silently), or "open" (open compose window for review). Overrides send parameter when set.
        attachments: Optional file paths to attach, comma-separated for multiple (e.g., "/path/to/file1.png,/path/to/file2.pdf")
        body_html: Optional HTML body for rich formatting (bold, headings, links, colors). When provided, the reply is pasted as HTML. The plain 'reply_body' field is still required as fallback text.
        from_address: Optional sender address to use for this reply. Must be one of the account's configured email addresses. When omitted, Mail uses the account's default "Send new messages from" setting.

    Returns:
        Confirmation message with details of the reply sent, saved draft, or opened draft
    """

    reply_body = _strip_cdata_wrappers(reply_body) or ""
    body_html = _strip_cdata_wrappers(body_html)

    sender_override, sender_error = _validate_from_address(account, from_address)
    if sender_error:
        return sender_error

    # Resolve delivery mode up front: both paths need it.
    if mode is not None:
        if mode not in ("send", "draft", "open"):
            return f"Error: Invalid mode '{mode}'. Use: send, draft, open"
        effective_mode = mode
    else:
        effective_mode = "send" if send else "draft"

    if server.READ_ONLY and effective_mode == "send":
        return (
            "Error: Sending is disabled in read-only mode. "
            'Use mode="draft" to save the reply, or mode="open" to review it in Mail.'
        )

    # Plain-text replies take the GUI-free path: the body is written into the
    # message instead of typed into a window that may not have focus.
    # Only an HTML body still needs the clipboard/keystroke route below,
    # because Mail's scripting interface has no HTML body property.
    if not body_html:
        return _reply_plain(
            account=account,
            mailbox=mailbox,
            subject_keyword=subject_keyword,
            reply_body=reply_body,
            reply_to_all=reply_to_all,
            cc=cc,
            bcc=bcc,
            effective_mode=effective_mode,
            attachments=attachments,
            sender_override=sender_override,
        )

    # Escape all user inputs for AppleScript
    safe_account = escape_applescript(account)
    safe_subject_keyword = escape_applescript(subject_keyword)

    # Write reply body to a temp file to avoid AppleScript string escaping
    # issues with special characters (em dashes, curly quotes, colons, etc.)
    body_tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        prefix="mail_reply_",
        delete=False,
        encoding="utf-8",
    )
    body_tmp.write(reply_body)
    body_tmp.close()
    body_temp_path = body_tmp.name

    # If body_html provided, write it to a temp file for the AppleScript to read.
    # If plain text only, wrap it in basic HTML so the clipboard paste renders
    # properly in Mail's HTML compose view (preserving line breaks and gap).
    html_temp_path = None
    # Append an empty paragraph to create a visible gap before the quoted original.
    # Mail strips trailing <br> tags, so we use a <p> with &nbsp; instead.
    gap_html = "<div><br></div><div><br></div>"
    if body_html:
        html_content = body_html + gap_html
    else:
        # Wrap plain text in HTML, converting newlines to <br>
        escaped_plain = html_escape(reply_body)
        escaped_plain = escaped_plain.replace("\n", "<br>")
        html_content = f"<div>{escaped_plain}</div>{gap_html}"
    html_tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".html",
        prefix="mail_reply_html_",
        delete=False,
        encoding="utf-8",
    )
    html_tmp.write(html_content)
    html_tmp.close()
    html_temp_path = html_tmp.name

    # Build the reply command based on reply_to_all flag
    if reply_to_all:
        reply_command = "set replyMessage to reply foundMessage with opening window and reply to all"
    else:
        reply_command = "set replyMessage to reply foundMessage with opening window"

    # Build CC recipients if provided
    cc_script = ""
    if cc:
        cc_addresses = [addr.strip() for addr in cc.split(",")]
        for addr in cc_addresses:
            safe_addr = escape_applescript(addr)
            cc_script += f'''
            make new cc recipient at end of cc recipients of replyMessage with properties {{address:"{safe_addr}"}}
            '''

    # Build BCC recipients if provided
    bcc_script = ""
    if bcc:
        bcc_addresses = [addr.strip() for addr in bcc.split(",")]
        for addr in bcc_addresses:
            safe_addr = escape_applescript(addr)
            bcc_script += f'''
            make new bcc recipient at end of bcc recipients of replyMessage with properties {{address:"{safe_addr}"}}
            '''

    # Build attachment script if provided
    attachment_script = ""
    attachment_info = ""
    if attachments:
        validated_paths, error = _validate_attachment_paths(attachments)
        if error:
            return error
        for path in validated_paths:
            safe_path = escape_applescript(path)
            attachment_script += f'''
                set theFile to POSIX file "{safe_path}"
                make new attachment with properties {{file name:theFile}} at after the last paragraph
                delay 1
            '''
            attachment_info += f"  {path}\n"

    safe_cc = escape_applescript(cc) if cc else ""
    safe_bcc = escape_applescript(bcc) if bcc else ""
    safe_attachment_info = (
        escape_applescript(attachment_info) if attachment_info else ""
    )

    # Read body from temp file in AppleScript (avoids all string escaping issues)
    read_body_script = f'set replyBodyText to do shell script "cat " & quoted form of "{body_temp_path}"'

    # Determine behavior per mode
    # All modes use HTML clipboard paste (via NSPasteboard) to insert the reply body.
    # This preserves Mail.app's native quoted original in the HTML layer.
    # (setting `content` via AppleScript overwrites the HTML layer entirely,
    # destroying the email thread history.)

    if effective_mode == "send":
        header_text = "SENDING REPLY"
        post_paste_action = """
                delay 0.5
                tell application "Mail"
                    send replyMessage
                end tell"""
        success_text = "Reply sent successfully!"
    elif effective_mode == "open":
        header_text = "OPENING REPLY FOR REVIEW"
        post_paste_action = ""
        success_text = "Reply opened in Mail for review. Edit and send when ready."
    else:  # draft
        header_text = "SAVING REPLY AS DRAFT"
        post_paste_action = """
                delay 0.5
                tell application "Mail"
                    close replyMessage saving yes
                end tell"""
        success_text = "Reply saved as draft!"

    cleanup_script = f'do shell script "rm -f " & quoted form of "{body_temp_path}"'
    html_cleanup_script = f'do shell script "rm -f \'{html_temp_path}\'"'

    sender_script = _compose_sender_script(
        "replyMessage", "targetAccount", sender_override
    )

    script = f'''
use framework "Foundation"
use framework "AppKit"
use scripting additions

-- Step 1: Place the reply body on the clipboard as RTF (rendered rich text)
-- plus a plain-text fallback. The previous raw-HTML-source approach made
-- Mail paste the body twice (rendered + literal tags); RTF pastes once.
{_html_to_pasteboard_script(html_temp_path)}

-- Step 2: Find the email and create reply
tell application "Mail"
    set outputText to "{header_text}" & return & return

    try
        -- Read reply body from temp file (for output text only)
        {read_body_script}

        set targetAccount to account "{safe_account}"
        {build_mailbox_ref(mailbox, account_var="targetAccount", var_name="inboxMailbox")}
        set inboxMessages to every message of inboxMailbox
        set foundMessage to missing value

        -- Find the first matching message
        repeat with aMessage in inboxMessages
            try
                set messageSubject to subject of aMessage

                if messageSubject contains "{safe_subject_keyword}" then
                    set foundMessage to aMessage
                    exit repeat
                end if
            end try
        end repeat

        if foundMessage is not missing value then
            set messageSubject to subject of foundMessage
            set messageSender to sender of foundMessage
            set messageDate to date received of foundMessage

            -- Create reply
            {reply_command}
            delay 0.5

            {sender_script}

            -- Add CC/BCC recipients
            {cc_script}
            {bcc_script}

            -- Add attachments (must be scoped to replyMessage so `last paragraph` resolves;
            -- bare `make new attachment ... at after the last paragraph` inside `tell application "Mail"`
            -- raises "Can't get last paragraph" because the reference has no implicit owner)
            tell replyMessage
                {attachment_script}
            end tell

            -- Paste reply body (HTML already on clipboard from Step 1).
            -- The body is inserted via a blind Cmd+V into the compose window, so the
            -- window MUST have keyboard focus when the keystroke fires. If Mail is not
            -- frontmost at that moment (common on the first compose of a session, when
            -- another app holds focus, or when the machine is busy), the paste lands
            -- nowhere and an EMPTY reply is sent with no error returned.
            --
            -- We deliberately do NOT verify the paste by reading `content of
            -- replyMessage` afterwards: Mail's GUI editor buffer is decoupled from the
            -- scriptable `content` property, so reading it always returns the pre-paste
            -- value (verified empirically — it reports 0 chars even after a successful
            -- paste). A content-read-back guard would therefore false-fail every send.
            -- Instead we make the paste deterministic by polling until Mail is genuinely
            -- frontmost (re-asserting focus each iteration) before issuing the keystroke.
            set visible of replyMessage to true
            activate

            tell application "System Events"
                set focusWaited to 0
                repeat until (frontmost of process "Mail") or (focusWaited is greater than or equal to 40)
                    try
                        set frontmost of process "Mail" to true
                    end try
                    delay 0.1
                    set focusWaited to focusWaited + 1
                end repeat
                -- Never type blind: without focus the keystroke lands in another
                -- app and the reply goes out empty (measured 25.08.2026).
                if not (frontmost of process "Mail") then
                    error "Mail could not be brought to the front, so the reply body could not be inserted. Nothing was sent or saved. Drop body_html to use the GUI-free reply path."
                end if
                -- settle delay so the compose window's body holds keyboard focus
                delay 0.8
                tell process "Mail"
                    keystroke "v" using command down
                end tell
            end tell
            delay 0.5

            {post_paste_action}

            set outputText to outputText & "{success_text}" & return
            set outputText to outputText & "To: " & messageSender & return
            set outputText to outputText & "Subject: " & messageSubject & return
    '''

    if cc:
        script += f"""
                set outputText to outputText & "CC: {safe_cc}" & return
    """

    if bcc:
        script += f"""
                set outputText to outputText & "BCC: {safe_bcc}" & return
    """

    if attachments:
        script += f'''
                set outputText to outputText & "Attachments:" & return & "{safe_attachment_info}" & return
    '''

    script += f"""
            else
                set outputText to outputText & "No email found matching: {safe_subject_keyword} (searched mailbox: {escape_applescript(mailbox)})" & return
            end if

            -- Clean up temp files
            {cleanup_script}
            {html_cleanup_script}

        on error errMsg
            -- Clean up temp files even on error
            try
                {cleanup_script}
                {html_cleanup_script}
            end try
            return "Error: " & errMsg & return & "Please check that the account name is correct and the email exists."
        end try

        return outputText
    end tell

    -- Restore clipboard
    if oldClip is not missing value then
        pb's clearContents()
        pb's setString:oldClip forType:(current application's NSPasteboardTypeString)
    end if
    """

    try:
        # Use osascript directly for AppleScriptObjC (use framework) support
        result = subprocess.run(
            ["osascript", "-"],
            input=script.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            return f"Error in reply: {stderr}"
        return result.stdout.decode("utf-8", errors="replace").strip()
    except subprocess.TimeoutExpired:
        return "Error: Reply script timed out"
    finally:
        # Belt-and-suspenders cleanup in case AppleScript didn't run
        if os.path.exists(body_temp_path):
            os.unlink(body_temp_path)
        if html_temp_path and os.path.exists(html_temp_path):
            os.unlink(html_temp_path)


@mcp.tool()
@inject_preferences
def compose_email(
    account: str,
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    attachments: Optional[str] = None,
    mode: str = "send",
    body_html: Optional[str] = None,
    from_address: Optional[str] = None,
) -> str:
    """
    Compose and send a new email from a specific account.

    Args:
        account: Account name to send from (e.g., "Gmail", "Work", "Personal")
        to: Recipient email address(es), comma-separated for multiple
        subject: Email subject line
        body: Email body text (used as plain-text fallback when body_html is provided)
        cc: Optional CC recipients, comma-separated for multiple
        bcc: Optional BCC recipients, comma-separated for multiple
        attachments: Optional file paths to attach, comma-separated for multiple (e.g., "/path/to/file1.png,/path/to/file2.pdf")
        mode: Delivery mode — "send" (send immediately, default), "draft" (save silently to Drafts), or "open" (open compose window for review before sending)
        body_html: Optional HTML body for rich formatting (bold, headings, links, colors). Handed to Mail verbatim via its `html content` property, so markup and non-ASCII text survive unchanged and your Mail signature stays attached. The plain 'body' field is still required as fallback text. Two Mail limits apply: the body is wrapped in Mail's share template on macOS 15+ (see README, Known Mail.app limitations), and adding an attachment makes Mail re-render the body, which flattens the formatting.
        from_address: Optional sender address to use for this message. Must be one of the account's configured email addresses. When omitted, Mail uses the account's default "Send new messages from" setting.

    Returns:
        Confirmation message with details of the email
    """

    # Validate mode
    if mode not in ("send", "draft", "open"):
        return f"Error: Invalid mode '{mode}'. Use: send, draft, open"

    if server.READ_ONLY and mode == "send":
        return (
            "Error: Sending is disabled in read-only mode. "
            'Use mode="draft" to save the message, or mode="open" to review it in Mail.'
        )

    body = _strip_cdata_wrappers(body) or ""
    body_html = _strip_cdata_wrappers(body_html)

    # Validate optional sender override
    sender_override, sender_error = _validate_from_address(account, from_address)
    if sender_error:
        return sender_error

    # Validate and resolve attachments early
    attachment_script = ""
    attachment_info = ""
    validated_attachment_paths: List[str] = []
    if attachments:
        validated_paths, error = _validate_attachment_paths(attachments)
        if error:
            return error
        validated_attachment_paths = validated_paths
        for path in validated_paths:
            safe_path = escape_applescript(path)
            attachment_script += f'''
                set theFile to POSIX file "{safe_path}"
                make new attachment with properties {{file name:theFile}} at after the last paragraph
                delay 1
            '''
            attachment_info += f"  {path}\n"

    # --- HTML path: use NSPasteboard clipboard injection ---
    if body_html:
        html_result = _send_html_email(
            account=account,
            to=to,
            subject=subject,
            body_plain=body,
            body_html=body_html,
            cc=cc,
            bcc=bcc,
            attachments_script=attachment_script,
            attachment_info=attachment_info,
            mode=mode,
            sender_override=sender_override,
        )
        if mode == "draft" and not html_result.startswith("Error"):
            html_result += _draft_location_note(
                subject, len(validated_attachment_paths)
            )
        return html_result

    # --- Plain-text path: existing AppleScript approach ---
    safe_account = escape_applescript(account)
    escaped_subject = escape_applescript(subject)
    escaped_body = escape_applescript(body)

    # Build TO recipients (split comma-separated addresses)
    to_script = ""
    to_addresses = [addr.strip() for addr in to.split(",")]
    for addr in to_addresses:
        safe_addr = escape_applescript(addr)
        to_script += f'''
                make new to recipient at end of to recipients with properties {{address:"{safe_addr}"}}
        '''

    # Build CC recipients if provided
    cc_script = ""
    if cc:
        cc_addresses = [addr.strip() for addr in cc.split(",")]
        for addr in cc_addresses:
            safe_addr = escape_applescript(addr)
            cc_script += f'''
                make new cc recipient at end of cc recipients with properties {{address:"{safe_addr}"}}
            '''

    # Build BCC recipients if provided
    bcc_script = ""
    if bcc:
        bcc_addresses = [addr.strip() for addr in bcc.split(",")]
        for addr in bcc_addresses:
            safe_addr = escape_applescript(addr)
            bcc_script += f'''
                make new bcc recipient at end of bcc recipients with properties {{address:"{safe_addr}"}}
            '''

    safe_to = escape_applescript(to)
    safe_cc = escape_applescript(cc) if cc else ""
    safe_bcc = escape_applescript(bcc) if bcc else ""
    safe_attachment_info = (
        escape_applescript(attachment_info) if attachment_info else ""
    )

    sender_script = _compose_sender_script(
        "newMessage", "targetAccount", sender_override
    )

    # Determine behavior per mode
    if mode == "send":
        header_text = "COMPOSING EMAIL"
        visible = "false"
        send_command = "send newMessage"
        success_text = "✓ Email sent successfully!"
    elif mode == "open":
        header_text = "OPENING EMAIL FOR REVIEW"
        visible = "true"
        send_command = "activate"
        success_text = "✓ Email opened in Mail for review. Edit and send when ready."
    else:  # draft
        header_text = "SAVING EMAIL AS DRAFT"
        visible = "false"
        # Close the message object, never `window 1`. The message is created
        # with visible:false and therefore owns no window, so `close window 1`
        # targeted Mail's frontmost window instead — it closed (and silently
        # saved as a draft) whatever the user had open, and the attachment of
        # the message we actually wanted to save was lost. Closing the object
        # itself saves it to Drafts with its attachments intact.
        send_command = "close newMessage saving yes"
        success_text = "✓ Email saved as draft!"

    script = f'''
    tell application "Mail"
        set outputText to "{header_text}" & return & return

        try
            set targetAccount to account "{safe_account}"

            -- Create new outgoing message
            set newMessage to make new outgoing message with properties {{subject:"{escaped_subject}", content:"{escaped_body}", visible:{visible}}}

            {sender_script}

            -- Add TO/CC/BCC recipients
            tell newMessage
                {to_script}
                {cc_script}
                {bcc_script}
            end tell

            -- Add attachments
            tell newMessage
                {attachment_script}
            end tell

            -- Send, save as draft, or leave open for review
            {send_command}

            set outputText to outputText & "{success_text}" & return
            set outputText to outputText & "To: {safe_to}" & return
            set outputText to outputText & "Subject: {escaped_subject}" & return
    '''

    if cc:
        script += f"""
            set outputText to outputText & "CC: {safe_cc}" & return
    """

    if bcc:
        script += f"""
            set outputText to outputText & "BCC: {safe_bcc}" & return
    """

    if attachments:
        script += f'''
            set outputText to outputText & "Attachments:" & return & "{safe_attachment_info}" & return
    '''

    script += f'''

        on error errMsg
            return "Error: " & errMsg & return & "Please check that the account name and email addresses are correct."
        end try

        return outputText
    end tell
    '''

    result = run_applescript(script)
    if mode == "draft" and not result.startswith("Error:"):
        result += _draft_location_note(subject, len(validated_attachment_paths))
    return result


@mcp.tool()
@inject_preferences
def forward_email(
    account: str,
    subject_keyword: str,
    to: str,
    message: Optional[str] = None,
    mailbox: str = "INBOX",
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    from_address: Optional[str] = None,
    mode: str = "send",
) -> str:
    """
    Forward an email to one or more recipients.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        subject_keyword: Keyword to search for in email subjects
        to: Recipient email address(es), comma-separated for multiple
        message: Optional message to add before forwarded content. Inserting it needs Mail in the foreground; without a message the forward runs without touching the GUI.
        mailbox: Mailbox to search in (default: "INBOX")
        cc: Optional CC recipients, comma-separated for multiple
        bcc: Optional BCC recipients, comma-separated for multiple
        from_address: Optional sender address to use when forwarding. Must be one of the account's configured email addresses. When omitted, Mail uses the account's default "Send new messages from" setting.
        mode: Delivery mode — "send" (send immediately, default), "draft" (save silently to Drafts), or "open" (open the forward for review)

    Returns:
        Confirmation message with details of forwarded email
    """

    if mode not in ("send", "draft", "open"):
        return f"Error: Invalid mode '{mode}'. Use: send, draft, open"

    if server.READ_ONLY and mode == "send":
        return (
            "Error: Sending is disabled in read-only mode. "
            'Use mode="draft" to save the forward, or mode="open" to review it in Mail.'
        )

    message = _strip_cdata_wrappers(message)

    sender_override, sender_error = _validate_from_address(account, from_address)
    if sender_error:
        return sender_error

    # Escape all user inputs for AppleScript
    safe_account = escape_applescript(account)
    safe_subject_keyword = escape_applescript(subject_keyword)
    safe_to = escape_applescript(to)
    safe_mailbox = escape_applescript(mailbox)
    escaped_message = escape_applescript(message) if message else ""

    sender_script = _compose_sender_script(
        "forwardMessage", "targetAccount", sender_override
    )

    # Build CC recipients if provided
    cc_script = ""
    if cc:
        cc_addresses = [addr.strip() for addr in cc.split(",")]
        for addr in cc_addresses:
            safe_addr = escape_applescript(addr)
            cc_script += f'''
            make new cc recipient at end of cc recipients of forwardMessage with properties {{address:"{safe_addr}"}}
            '''

    # Build BCC recipients if provided
    bcc_script = ""
    if bcc:
        bcc_addresses = [addr.strip() for addr in bcc.split(",")]
        for addr in bcc_addresses:
            safe_addr = escape_applescript(addr)
            bcc_script += f'''
            make new bcc recipient at end of bcc recipients of forwardMessage with properties {{address:"{safe_addr}"}}
            '''

    safe_cc = escape_applescript(cc) if cc else ""
    safe_bcc = escape_applescript(bcc) if bcc else ""

    # Build TO recipients (split comma-separated)
    to_script = ""
    to_addresses = [addr.strip() for addr in to.split(",")]
    for addr in to_addresses:
        safe_addr = escape_applescript(addr)
        to_script += f'''
                make new to recipient at end of to recipients of forwardMessage with properties {{address:"{safe_addr}"}}
        '''

    # If an optional message is provided, write it as HTML to a temp file
    # for NSPasteboard clipboard injection (preserves forwarded content).
    fwd_html_temp_path = None
    fwd_html_paste_script = ""
    fwd_html_cleanup_script = ""
    if message:
        escaped_plain = html_escape(message)
        escaped_plain = escaped_plain.replace("\n", "<br>")
        fwd_html_content = f"{escaped_plain}<br><br>"
        fwd_html_tmp = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".html",
            prefix="mail_fwd_html_",
            delete=False,
            encoding="utf-8",
        )
        fwd_html_tmp.write(fwd_html_content)
        fwd_html_tmp.close()
        fwd_html_temp_path = fwd_html_tmp.name
        fwd_html_cleanup_script = f'do shell script "rm -f \'{fwd_html_temp_path}\'"'
        fwd_html_paste_script = f"""
                set visible of forwardMessage to true
                activate

                tell application "System Events"
                    set focusWaited to 0
                    repeat until (frontmost of process "Mail") or (focusWaited is greater than or equal to 40)
                        try
                            set frontmost of process "Mail" to true
                        end try
                        delay 0.1
                        set focusWaited to focusWaited + 1
                    end repeat
                    -- Never type blind: without focus the paste lands in
                    -- another app and the note silently goes missing.
                    if not (frontmost of process "Mail") then
                        error "Mail could not be brought to the front, so the note could not be inserted. Nothing was sent or saved. Forward without `message` to stay out of the GUI."
                    end if
                end tell
                delay 0.5

                -- Place the prepended note on the clipboard as RTF (rendered)
                -- plus a plain-text fallback, instead of raw HTML source which
                -- Mail would paste twice (rendered + literal tags).
                {_html_to_pasteboard_script(fwd_html_temp_path)}

                tell application "System Events"
                    tell process "Mail"
                        keystroke "v" using command down
                    end tell
                end tell
                delay 0.5

                if oldClip is not missing value then
                    pb's clearContents()
                    pb's setString:oldClip forType:(current application's NSPasteboardTypeString)
                end if
        """

    if mode == "send":
        forward_final_action = "send forwardMessage"
        forward_success_text = "Email forwarded successfully."
    elif mode == "open":
        forward_final_action = (
            "set visible of forwardMessage to true\n            activate"
        )
        forward_success_text = (
            "Forward opened in Mail for review. Edit and send when ready."
        )
    else:
        # `save` commits it to Drafts. Never `close window 1` — that closes
        # whatever window Mail has in front, not this forward.
        forward_final_action = "save forwardMessage"
        forward_success_text = "Forward saved as draft."

    use_frameworks = ""
    if message:
        use_frameworks = """use framework "Foundation"
use framework "AppKit"
use scripting additions
"""

    script = f'''{use_frameworks}
tell application "Mail"
    set outputText to "FORWARDING EMAIL" & return & return

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

        -- `whose` filters inside Mail instead of pulling every message over
        -- Apple Events, and the NEWEST match is forwarded: with several
        -- messages in a thread the latest one is what the caller means.
        set matchingMessages to (messages of targetMailbox whose subject contains "{safe_subject_keyword}")
        set matchCount to count of matchingMessages
        set foundMessage to missing value
        if matchCount > 0 then
            set foundMessage to item 1 of matchingMessages
            set newestDate to date received of foundMessage
            set scanLimit to matchCount
            if scanLimit > 100 then set scanLimit to 100
            repeat with scanIndex from 2 to scanLimit
                try
                    set candidate to item scanIndex of matchingMessages
                    if (date received of candidate) > newestDate then
                        set foundMessage to candidate
                        set newestDate to date received of candidate
                    end if
                end try
            end repeat
        end if

        if foundMessage is not missing value then
            set messageSubject to subject of foundMessage
            set messageSender to sender of foundMessage
            set messageDate to date received of foundMessage

            -- Create forward
            set forwardMessage to forward foundMessage with opening window

            {sender_script}

            -- Add recipients
            {to_script}

            -- Add CC/BCC recipients
            {cc_script}
            {bcc_script}

            -- Add optional message via HTML clipboard paste (preserves forwarded content)
            {fwd_html_paste_script}

            -- Send, save as draft, or leave open for review
            {forward_final_action}

            -- Clean up temp files
            {fwd_html_cleanup_script}

            set outputText to outputText & "{forward_success_text}" & return
            set outputText to outputText & "To: {safe_to}" & return
            set outputText to outputText & "Forwarded message: " & messageSubject & return
            if matchCount > 1 then
                set outputText to outputText & "Note: " & matchCount & " messages matched, forwarded the newest one." & return
            end if
    '''

    if cc:
        script += f"""
                set outputText to outputText & "CC: {safe_cc}" & return
    """

    if bcc:
        script += f"""
                set outputText to outputText & "BCC: {safe_bcc}" & return
    """

    script += f"""
            else
                set outputText to outputText & "⚠ No email found matching: {safe_subject_keyword}" & return
            end if

        on error errMsg
            try
                {fwd_html_cleanup_script}
            end try
            return "Error: " & errMsg
        end try

        return outputText
    end tell
    """

    try:
        if message:
            # Use osascript directly for AppleScriptObjC (use framework) support
            result = subprocess.run(
                ["osascript", "-"],
                input=script.encode("utf-8"),
                capture_output=True,
                timeout=30,
            )
            if result.returncode != 0:
                stderr = result.stderr.decode("utf-8", errors="replace").strip()
                return f"Error forwarding email: {stderr}"
            return result.stdout.decode("utf-8", errors="replace").strip()
        else:
            return run_applescript(script)
    except subprocess.TimeoutExpired:
        return "Error: Forward script timed out"
    finally:
        if fwd_html_temp_path and os.path.exists(fwd_html_temp_path):
            os.unlink(fwd_html_temp_path)


@mcp.tool()
@inject_preferences
def manage_drafts(
    account: str,
    action: str,
    subject: Optional[str] = None,
    to: Optional[str] = None,
    body: Optional[str] = None,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    draft_subject: Optional[str] = None,
    from_address: Optional[str] = None,
    attachments: Optional[str] = None,
    remove_attachments: Optional[str] = None,
) -> str:
    """
    Manage draft emails - list, create, update, send, open, or delete drafts.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        action: Action to perform: "list", "create", "update", "send", "open", "delete". Use "open" to open a draft in a visible compose window for review before sending, "update" to change an existing draft (text, recipients, attachments).
        subject: Email subject (required for create; for update the NEW subject, omit to keep the current one)
        to: Recipient email(s) (comma-separated). Required for create; for update it REPLACES the current recipients, omit to keep them.
        body: Email body. Required for create; for update it replaces the body, omit to keep the current text.
        cc: Optional CC recipients; for update it replaces the current CC list.
        bcc: Optional BCC recipients; for update it replaces the current BCC list.
        draft_subject: Subject keyword to find the draft (required for update/send/open/delete)
        from_address: Optional sender address for new drafts (action="create"). Must be one of the account's configured email addresses. When omitted, Mail uses the account's default "Send new messages from" setting.
        attachments: File paths to attach, comma-separated. For action="update" these are ADDED to the attachments the draft already carries. Note that Mail re-renders the body when a file is attached, which flattens HTML formatting.
        remove_attachments: action="update" only. Comma-separated name fragments of attachments to drop, or "all" to drop every attachment. Combine with `attachments` to swap a file.

    Returns:
        Formatted output based on action

    Note on update: Mail cannot edit a stored draft in place, so the draft is
    rebuilt and the old version deleted afterwards. Existing attachments are
    extracted to disk and re-attached; if any of them cannot be extracted the
    draft is left untouched rather than rebuilt without them. When `body` is
    omitted the stored HTML is reused, so formatting and the Mail signature
    survive the edit; the return value says which of the two paths was taken.
    """

    body = _strip_cdata_wrappers(body)

    # Escape account for all paths
    safe_account = escape_applescript(account)

    if action == "list":
        script = f'''
        tell application "Mail"
            set outputText to "DRAFT EMAILS - {safe_account}" & return & return

            try
                set targetAccount to account "{safe_account}"
                set draftsMailbox to mailbox "Drafts" of targetAccount
                set draftMessages to every message of draftsMailbox
                set draftCount to count of draftMessages

                set outputText to outputText & "Found " & draftCount & " draft(s)" & return & return

                repeat with aDraft in draftMessages
                    try
                        set draftSubject to subject of aDraft
                        set draftDate to date sent of aDraft

                        set outputText to outputText & "✉ " & draftSubject & return
                        set outputText to outputText & "   Created: " & (draftDate as string) & return & return
                    end try
                end repeat

            on error errMsg
                return "Error: " & errMsg
            end try

            return outputText
        end tell
        '''

    elif action == "create":
        if not subject or not to or not body:
            return "Error: 'subject', 'to', and 'body' are required for creating drafts"

        sender_override, sender_error = _validate_from_address(account, from_address)
        if sender_error:
            return sender_error

        escaped_subject = escape_applescript(subject)
        escaped_body = escape_applescript(body)
        safe_to = escape_applescript(to)

        sender_script = _compose_sender_script(
            "newDraft", "targetAccount", sender_override
        )

        # Build TO recipients (split comma-separated)
        to_script = ""
        to_addresses = [addr.strip() for addr in to.split(",")]
        for addr in to_addresses:
            safe_addr = escape_applescript(addr)
            to_script += f'''
                    make new to recipient at end of to recipients with properties {{address:"{safe_addr}"}}
            '''

        # Build CC recipients if provided
        cc_script = ""
        if cc:
            cc_addresses = [addr.strip() for addr in cc.split(",")]
            for addr in cc_addresses:
                safe_addr = escape_applescript(addr)
                cc_script += f'''
                    make new cc recipient at end of cc recipients with properties {{address:"{safe_addr}"}}
                '''

        # Build BCC recipients if provided
        bcc_script = ""
        if bcc:
            bcc_addresses = [addr.strip() for addr in bcc.split(",")]
            for addr in bcc_addresses:
                safe_addr = escape_applescript(addr)
                bcc_script += f'''
                    make new bcc recipient at end of bcc recipients with properties {{address:"{safe_addr}"}}
                '''

        script = f'''
        tell application "Mail"
            set outputText to "CREATING DRAFT" & return & return

            try
                set targetAccount to account "{safe_account}"

                -- Create new outgoing message (draft)
                set newDraft to make new outgoing message with properties {{subject:"{escaped_subject}", content:"{escaped_body}", visible:false}}

                {sender_script}

                -- Add recipients
                tell newDraft
                    {to_script}
                    {cc_script}
                    {bcc_script}
                end tell

                -- Save the draft explicitly instead of trusting Mail's autosave.
                -- Closing the message object (never `window 1`) commits it to
                -- Drafts and disposes of the compose object.
                close newDraft saving yes

                set outputText to outputText & "✓ Draft created successfully!" & return & return
                set outputText to outputText & "Subject: {escaped_subject}" & return
                set outputText to outputText & "To: {safe_to}" & return

            on error errMsg
                return "Error: " & errMsg
            end try

            return outputText
        end tell
        '''

    elif action == "update":
        if not draft_subject:
            return "Error: 'draft_subject' is required for updating drafts"
        return _update_draft(
            account=account,
            draft_subject=draft_subject,
            subject=subject,
            to=to,
            cc=cc,
            bcc=bcc,
            body=body,
            attachments=attachments,
            remove_attachments=remove_attachments,
        )

    elif action == "send":
        if server.READ_ONLY:
            return "Error: Sending drafts is disabled in read-only mode."
        if not draft_subject:
            return "Error: 'draft_subject' is required for sending drafts"

        safe_draft_subject = escape_applescript(draft_subject)

        script = f'''
        tell application "Mail"
            set outputText to "SENDING DRAFT" & return & return

            try
                set targetAccount to account "{safe_account}"
                set draftsMailbox to mailbox "Drafts" of targetAccount
                set matchingDrafts to (messages of draftsMailbox whose subject contains "{safe_draft_subject}")
                set matchCount to count of matchingDrafts

                -- Sending the wrong draft cannot be undone, so an ambiguous
                -- keyword is refused instead of resolved by guessing.
                if matchCount > 1 then
                    set outputText to outputText & "⚠ " & matchCount & " drafts match the keyword. Refusing to guess which one to send. Narrow the keyword; the candidates are:" & return
                    repeat with aDraft in matchingDrafts
                        set outputText to outputText & "   - " & (subject of aDraft) & return
                    end repeat
                    return outputText
                end if

                if matchCount is 1 then
                    set foundDraft to item 1 of matchingDrafts
                    set draftSubject to subject of foundDraft

                    -- Send the draft
                    send foundDraft

                    set outputText to outputText & "✓ Draft sent successfully!" & return
                    set outputText to outputText & "Subject: " & draftSubject & return

                else
                    set outputText to outputText & "⚠ No draft found matching: {safe_draft_subject}" & return
                end if

            on error errMsg
                return "Error: " & errMsg
            end try

            return outputText
        end tell
        '''

    elif action == "open":
        if not draft_subject:
            return "Error: 'draft_subject' is required for opening drafts"

        safe_draft_subject = escape_applescript(draft_subject)

        script = f'''
        tell application "Mail"
            set outputText to "OPENING DRAFT FOR REVIEW" & return & return

            try
                set targetAccount to account "{safe_account}"
                set draftsMailbox to mailbox "Drafts" of targetAccount
                set matchingDrafts to (messages of draftsMailbox whose subject contains "{safe_draft_subject}")
                set matchCount to count of matchingDrafts

                if matchCount is not 0 then
                    -- Opening is harmless, so the newest match wins and the
                    -- caller is told how many there were.
                    set foundDraft to item 1 of matchingDrafts
                    set newestDate to date sent of foundDraft
                    repeat with aDraft in matchingDrafts
                        try
                            if (date sent of aDraft) > newestDate then
                                set foundDraft to aDraft
                                set newestDate to date sent of aDraft
                            end if
                        end try
                    end repeat
                    set draftSubject to subject of foundDraft

                    -- Open the draft in a visible compose window
                    set draftWindow to open foundDraft
                    activate

                    set outputText to outputText & "✓ Draft opened in Mail for review!" & return
                    set outputText to outputText & "Subject: " & draftSubject & return
                    if matchCount > 1 then
                        set outputText to outputText & "Note: " & matchCount & " drafts matched, opened the newest one." & return
                    end if
                    set outputText to outputText & return & "Edit and send when ready." & return

                else
                    set outputText to outputText & "⚠ No draft found matching: {safe_draft_subject}" & return
                end if

            on error errMsg
                return "Error: " & errMsg
            end try

            return outputText
        end tell
        '''

    elif action == "delete":
        if not draft_subject:
            return "Error: 'draft_subject' is required for deleting drafts"

        safe_draft_subject = escape_applescript(draft_subject)

        script = f'''
        tell application "Mail"
            set outputText to "DELETING DRAFT" & return & return

            try
                set targetAccount to account "{safe_account}"
                set draftsMailbox to mailbox "Drafts" of targetAccount
                set matchingDrafts to (messages of draftsMailbox whose subject contains "{safe_draft_subject}")
                set matchCount to count of matchingDrafts

                -- Deleting the wrong draft throws away written work, so an
                -- ambiguous keyword is refused instead of resolved by guessing.
                if matchCount > 1 then
                    set outputText to outputText & "⚠ " & matchCount & " drafts match the keyword. Refusing to guess which one to delete. Narrow the keyword; the candidates are:" & return
                    repeat with aDraft in matchingDrafts
                        set outputText to outputText & "   - " & (subject of aDraft) & return
                    end repeat
                    return outputText
                end if

                if matchCount is 1 then
                    set foundDraft to item 1 of matchingDrafts
                    set draftSubject to subject of foundDraft
                    set draftId to id of foundDraft

                    delete foundDraft

                    -- Mail keeps the compose object alive after a draft is
                    -- saved, and autosaves it again ~15 s later — which
                    -- recreated the draft we just deleted (measured
                    -- 25.08.2026: gone at t+10 s, back at t+15 s). Closing the
                    -- object without saving stops that. Only invisible objects
                    -- are touched: a visible one is a compose window the user
                    -- has open, and closing it would throw away their work.
                    set liveComposes to outgoing messages
                    repeat with composeIndex from (count of liveComposes) to 1 by -1
                        try
                            set aCompose to item composeIndex of liveComposes
                            if (visible of aCompose) is false and (subject of aCompose) is draftSubject then
                                close aCompose saving no
                            end if
                        end try
                    end repeat
                    delay 0.5

                    -- Verify instead of assuming: report what the mailbox says.
                    set stillThere to (messages of draftsMailbox whose id is draftId)
                    if (count of stillThere) is 0 then
                        set outputText to outputText & "✓ Draft deleted." & return
                    else
                        set outputText to outputText & "⚠ Draft is still in Drafts after the delete. Remove it in Mail." & return
                    end if
                    set outputText to outputText & "Subject: " & draftSubject & return

                else
                    set outputText to outputText & "⚠ No draft found matching: {safe_draft_subject}" & return
                end if

            on error errMsg
                return "Error: " & errMsg
            end try

            return outputText
        end tell
        '''

    else:
        return (
            f"Error: Invalid action '{action}'. "
            "Use: list, create, update, send, open, delete"
        )

    result = run_applescript(script)
    if action == "create" and not result.startswith("Error:"):
        result += _draft_location_note(subject)
    return result

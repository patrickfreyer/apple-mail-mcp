"""Reply, forward and new drafts, addressed by Mail message id.

Nothing here sends, and nothing touches the screen unless asked. By
default each tool builds a windowless message (``make new outgoing
message ... visible:false``), saves it to the Drafts mailbox of the
right account and returns the draft's id. ``open_for_review=True`` (off
by default) or ``open_draft(id)`` shows a draft in a compose window.

Messages are found with ``first message of <mailbox> whose id is N``,
never by looping over a subject match, so drafts or mail deleted while
a script runs cannot shift the target.

Replies: Mail's ``reply`` command is the only way to get threading
headers (In-Reply-To/References) from AppleScript, and it opens a
compose window even ``without opening window``. So background replies
are plain new messages with Mail's reply recipients and "Re:" subject
(unthreaded), and the threaded native reply is used only when the
caller asks for a window (``open_for_review=True``). Either way the
quote is rebuilt from ``content of`` the original as "> " lines: the
quote Mail puts in a fresh reply cannot be read and is lost once
``content`` is set, and ``html content`` is wrapped whole in Mail's
cite blockquote, so a native HTML quote below new text is not possible.
"""

import os
import tempfile
from datetime import datetime
from email.utils import parseaddr
from typing import List, Optional

from apple_mail_mcp.core import escape_applescript, inject_preferences, run_applescript
from apple_mail_mcp.server import mcp
from apple_mail_mcp.tools.compose import _validate_attachment_paths

# Separates fields in script output. Results come back as UTF-8 files,
# so this never meets the ASCII-only stdout path.
SEP = "␟"


# ---------- pure helpers (unit tested) ----------


def quote_original(original: str) -> str:
    """Prefix every line of ``original`` with "> " (blank lines get ">")."""
    text = original.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    return "\n".join("> " + line if line else ">" for line in text.split("\n"))


def format_quote_date(iso: str) -> str:
    """``2026-11-20T14:01:02`` -> ``20 Nov 2026 at 14:01``; raw on failure."""
    try:
        return datetime.fromisoformat(iso).strftime("%-d %b %Y at %H:%M")
    except ValueError:
        return iso


def build_reply_text(body: str, sender: str, date_iso: str, original: str) -> str:
    """New body, then "On <date>, <sender> wrote:" and the quoted original."""
    header = f"On {format_quote_date(date_iso)}, {sender} wrote:"
    return f"{body.rstrip()}\n\n{header}\n\n{quote_original(original)}\n"


def build_forward_text(
    body: str, sender: str, date_iso: str, subject: str, to: str, original: str
) -> str:
    """New body followed by a forwarded-message header and the original."""
    head = "\n".join(
        [
            "Begin forwarded message:",
            "",
            f"From: {sender}",
            f"Subject: {subject}",
            f"Date: {format_quote_date(date_iso)}",
            f"To: {to}",
        ]
    )
    return f"{body.rstrip()}\n\n{head}\n\n{original.rstrip()}\n"


def split_addresses(value: Optional[str]) -> List[str]:
    return [a.strip() for a in (value or "").split(",") if a.strip()]


def parse_fields(output: str, n: int) -> List[str]:
    """Split SEP-delimited output into exactly ``n`` fields.

    The last field keeps any further separators (it carries message
    bodies, which may contain anything).
    """
    parts = output.split(SEP, n - 1)
    return parts + [""] * (n - len(parts))


# ---------- AppleScript fragments ----------


def find_message_script(
    message_id: int, account: Optional[str] = None, mailbox: Optional[str] = None
) -> str:
    """Sets ``theMsg`` to the message with this Mail id, or errors.

    Account and mailbox are hints that narrow the search; the id alone
    is enough.
    """
    mid = int(message_id)
    accts = f'{{account "{escape_applescript(account)}"}}' if account else "accounts"
    mbs = (
        f'{{mailbox "{escape_applescript(mailbox)}" of a}}'
        if mailbox
        else "mailboxes of a"
    )
    return f"""
        set theMsg to missing value
        repeat with a in {accts}
            if theMsg is missing value then
                repeat with mb in {mbs}
                    try
                        set theMsg to (first message of mb whose id is {mid})
                        exit repeat
                    end try
                end repeat
            end if
        end repeat
        if theMsg is missing value then error "Message {mid} not found"
    """


def drafts_mailbox_script(account_expr: str) -> str:
    """Sets ``draftsBox`` to the Drafts mailbox of ``account_expr``."""
    return f"""
        try
            set draftsBox to mailbox "Drafts" of ({account_expr})
        on error
            set draftsBox to drafts mailbox
        end try
        set beforeIds to id of every message of draftsBox
    """


def recipients_script(var: str, kind: str, addresses: List[str]) -> str:
    return "".join(
        f"make new {kind} recipient at end of {kind} recipients of {var} "
        f'with properties {{address:"{escape_applescript(a)}"}}\n'
        for a in addresses
    )


def attachments_script(var: str, paths: List[str]) -> str:
    return "".join(
        f"tell content of {var} to make new attachment with properties "
        f'{{file name:(POSIX file "{escape_applescript(p)}")}} '
        f"at after the last paragraph\n"
        for p in paths
    )


ATTACH_SETTLE_SECONDS = 2


def save_and_locate_script(var: str) -> str:
    """Save ``var`` (no window), find the new draft's id in ``draftsBox``
    and put ``id SEP subject SEP to SEP cc`` in ``out``."""
    return f"""
        -- Attachments load asynchronously; saving at once drops them.
        delay {ATTACH_SETTLE_SECONDS}
        save {var}
        set newId to missing value
        repeat 40 times
            delay 0.5
            set nowIds to id of every message of draftsBox
            repeat with i in nowIds
                if beforeIds does not contain (contents of i) then
                    set newId to contents of i
                    exit repeat
                end if
            end repeat
            if newId is not missing value then exit repeat
        end repeat
        if newId is missing value then error "Draft saved but not found in Drafts"
        set d to first message of draftsBox whose id is newId
        set toList to ""
        repeat with r in to recipients of d
            set toList to toList & address of r & ", "
        end repeat
        set ccList to ""
        repeat with r in cc recipients of d
            set ccList to ccList & address of r & ", "
        end repeat
        set out to (newId as string) & "{SEP}" & subject of d & "{SEP}" & toList & "{SEP}" & ccList
    """


# Shows a saved draft. Only ever emitted on an explicit request.
OPEN_DRAFT_SCRIPT = """
        open d
        activate
"""


def _write_temp(text: str) -> str:
    f = tempfile.NamedTemporaryFile(
        "w", suffix=".txt", prefix="mail_draft_", delete=False, encoding="utf-8"
    )
    f.write(text)
    f.close()
    return f.name


def run_mail(body: str, timeout: int = 180, **texts: str) -> str:
    """Run ``body`` inside ``tell application "Mail"``; return ``out``.

    ``texts`` become AppleScript variables, passed through UTF-8 temp
    files so "£" and accents survive. The result comes back the same
    way: osascript's stdout here is forced to ASCII. File reads and
    writes sit outside the tell block, clear of Mail's sandbox.
    """
    paths = {var: _write_temp(text) for var, text in texts.items()}
    out_path = _write_temp("")
    reads = "\n".join(
        f'set {var} to read (POSIX file "{escape_applescript(p)}") as «class utf8»'
        for var, p in paths.items()
    )
    script = f"""
    {reads}
    tell application "Mail"
        set out to ""
        {body}
    end tell
    set fh to open for access (POSIX file "{escape_applescript(out_path)}") with write permission
    set eof fh to 0
    write out to fh as «class utf8»
    close access fh
    """
    try:
        run_applescript(script, timeout=timeout)
        with open(out_path, encoding="utf-8") as f:
            return f.read()
    finally:
        for p in [*paths.values(), out_path]:
            if os.path.exists(p):
                os.unlink(p)


def _report(kind: str, output: str, attachments: List[str], note: str) -> str:
    draft_id, subject, to, cc = parse_fields(output, 4)
    lines = [
        f"{kind} draft saved (not sent).",
        f"Draft id: {draft_id}",
        f"Subject: {subject}",
        f"To: {to.rstrip(', ')}",
    ]
    if cc.strip(", "):
        lines.append(f"Cc: {cc.rstrip(', ')}")
    lines += [f"Attached: {p}" for p in attachments]
    lines.append(note or "Not opened (open_draft to review).")
    return "\n".join(lines)


def _attachments(attachments: Optional[List[str]]):
    if not attachments:
        return [], None
    return _validate_attachment_paths(",".join(attachments))


def _original_script(message_id, account, mailbox) -> str:
    """Puts the original's fields into ``out`` (see ORIGINAL_FIELDS)."""
    return f"""
        {find_message_script(message_id, account, mailbox)}
        set iso to (date received of theMsg) as «class isot» as string
        set toList to ""
        repeat with r in to recipients of theMsg
            set toList to toList & address of r & ", "
        end repeat
        set ccList to ""
        repeat with r in cc recipients of theMsg
            set ccList to ccList & address of r & ", "
        end repeat
        set rt to ""
        try
            set rt to reply to of theMsg
        end try
        set own to ""
        set ownList to email addresses of (account of (mailbox of theMsg))
        repeat with e in ownList
            set own to own & (contents of e) & ", "
        end repeat
        set out to (sender of theMsg) & "{SEP}" & iso & "{SEP}" & (subject of theMsg) & "{SEP}" & toList & "{SEP}" & ccList & "{SEP}" & rt & "{SEP}" & own & "{SEP}" & (content of theMsg)
    """


ORIGINAL_FIELDS = ("sender", "date", "subject", "to", "cc", "reply_to", "own", "content")


def _fetch_original(message_id, account, mailbox, extra: str = "") -> dict:
    out = run_mail(_original_script(message_id, account, mailbox) + extra)
    return dict(zip(ORIGINAL_FIELDS, parse_fields(out, len(ORIGINAL_FIELDS))))


def _bare(addr: str) -> str:
    return parseaddr(addr)[1].lower()


def prefixed_subject(prefix: str, subject: str) -> str:
    """"Re: x" for "x", unchanged when it already starts with the prefix."""
    s = subject.strip()
    return s if s.lower().startswith(prefix.lower()) else f"{prefix} {s}"


def reply_recipients(orig: dict, reply_all: bool) -> tuple:
    """(to, cc, from) for a reply, as Mail's own reply would choose them.

    To is Reply-To if set, else the sender. Reply-all adds the original
    To and Cc to Cc, without the user's own addresses or duplicates.
    From is the user's address the original was sent to, if any.
    """
    own = {_bare(a) for a in split_addresses(orig.get("own"))}
    to = [orig.get("reply_to") or orig.get("sender", "")]
    seen = {_bare(to[0])} | own
    cc = []
    if reply_all:
        for a in split_addresses(orig.get("to")) + split_addresses(orig.get("cc")):
            if _bare(a) not in seen:
                seen.add(_bare(a))
                cc.append(a)
    addressed = [
        _bare(a) for a in split_addresses(orig.get("to")) + split_addresses(orig.get("cc"))
    ]
    sender = next((a for a in addressed if a in own), "")
    return to, cc, sender


def _background_draft_script(account_expr: str, to, cc, bcc, sender, paths) -> str:
    """New windowless message from ``subjectText``/``bodyText``, saved.

    ``make new outgoing message ... visible:false`` opens no window.
    """
    set_sender = f'set sender of m to "{escape_applescript(sender)}"' if sender else ""
    return f"""
        {drafts_mailbox_script(account_expr)}
        set m to make new outgoing message with properties {{subject:subjectText, content:bodyText, visible:false}}
        {set_sender}
        {recipients_script("m", "to", to)}
        {recipients_script("m", "cc", cc)}
        {recipients_script("m", "bcc", bcc)}
        {attachments_script("m", paths)}
        {save_and_locate_script("m")}
    """


# ---------- tools ----------


@mcp.tool()
@inject_preferences
def create_reply_draft(
    message_id: int,
    body: str,
    reply_all: bool = False,
    cc: Optional[str] = None,
    attachments: Optional[List[str]] = None,
    account: Optional[str] = None,
    mailbox: Optional[str] = None,
    open_for_review: bool = False,
) -> str:
    """
    Save a reply as a draft. Never sends.

    The body is followed by "On <date>, <sender> wrote:" and the
    "> "-quoted original.

    Two modes, because Mail's own reply command always opens a window:
    - open_for_review=False (default): built in the background, nothing
      on screen. Recipients and "Re:" subject follow Mail's reply rules,
      but the draft is NOT threaded (no In-Reply-To/References, which
      AppleScript cannot set).
    - open_for_review=True: Mail's native reply, threaded, left open in
      its compose window for review. That window is the draft; no copy.

    Args:
        message_id: Mail id of the message (search/get_email id, same as
            the .emlx file name).
        body: Reply text, above the quote.
        reply_all: Also address the original To/Cc recipients.
        cc: Extra Cc addresses, comma-separated.
        attachments: File paths to attach (under the home directory).
        account, mailbox: Optional hints that speed up the lookup.
        open_for_review: See above (default off).

    Returns:
        Draft id, subject, recipients, and whether it is threaded.
    """
    paths, error = _attachments(attachments)
    if error:
        return error
    orig = _fetch_original(message_id, account, mailbox)
    extra_cc = split_addresses(cc)
    if open_for_review:
        all_ = " and reply to all" if reply_all else ""
        script = f"""
        {find_message_script(message_id, account, mailbox)}
        {drafts_mailbox_script("account of mailbox of theMsg")}
        set r to reply theMsg with opening window{all_}
        delay 1
        set content of r to bodyText
        {recipients_script("r", "cc", extra_cc)}
        {attachments_script("r", paths)}
        {save_and_locate_script("r")}
        """
        note = "Threaded. Open in Mail for review."
    else:
        to, all_cc, sender = reply_recipients(orig, reply_all)
        script = f"""
        {find_message_script(message_id, account, mailbox)}
        {_background_draft_script(
            "account of mailbox of theMsg", to, all_cc + extra_cc, [], sender, paths
        )}
        """
        note = (
            "Not threaded (built in the background). "
            "open_for_review=True gives a threaded reply in a Mail window."
        )
    out = run_mail(
        script,
        bodyText=build_reply_text(body, orig["sender"], orig["date"], orig["content"]),
        subjectText=prefixed_subject("Re:", orig["subject"]),
    )
    return _report("Reply", out, paths, note)


@mcp.tool()
@inject_preferences
def create_forward_draft(
    message_id: int,
    to: str,
    body: str = "",
    cc: Optional[str] = None,
    attachments: Optional[List[str]] = None,
    include_original_attachments: bool = True,
    account: Optional[str] = None,
    mailbox: Optional[str] = None,
    open_for_review: bool = False,
) -> str:
    """
    Save a forward as a draft in the background, keeping the original's
    attachments. Never sends.

    Args:
        message_id: Mail id of the message to forward.
        to: Recipients, comma-separated.
        body: Text above the forwarded message.
        cc: Cc addresses, comma-separated.
        attachments: Extra file paths to attach.
        include_original_attachments: Carry over the original's files
            (Mail saves a copy of each, which is then attached).
        account, mailbox: Optional hints that speed up the lookup.
        open_for_review: Then show the saved draft in Mail (default off).

    Returns:
        Draft id, subject, recipients and attachments.
    """
    to_list = split_addresses(to)
    if not to_list:
        return "Error: 'to' is required for a forward."
    paths, error = _attachments(attachments)
    if error:
        return error

    att_dir = tempfile.mkdtemp(prefix="mail_fwd_")
    try:
        save_atts = ""
        if include_original_attachments:
            # Saving a copy of an attachment reads the message, never changes it.
            save_atts = f"""
                repeat with att in mail attachments of theMsg
                    save att in POSIX file ("{escape_applescript(att_dir)}/" & (name of att))
                end repeat
            """
        orig = _fetch_original(message_id, account, mailbox, save_atts)
        orig_files = sorted(os.path.join(att_dir, f) for f in os.listdir(att_dir))
        out = run_mail(
            f"""
            {find_message_script(message_id, account, mailbox)}
            {_background_draft_script(
                "account of mailbox of theMsg",
                to_list, split_addresses(cc), [], "", orig_files + paths,
            )}
            {OPEN_DRAFT_SCRIPT if open_for_review else ""}
            """,
            bodyText=build_forward_text(
                body,
                orig["sender"],
                orig["date"],
                orig["subject"],
                orig["to"].rstrip(", "),
                orig["content"],
            ),
            subjectText=prefixed_subject("Fwd:", orig["subject"]),
            timeout=240,
        )
    finally:
        for name in os.listdir(att_dir):
            os.unlink(os.path.join(att_dir, name))
        os.rmdir(att_dir)
    names = [os.path.basename(p) for p in orig_files] + paths
    return _report("Forward", out, names, _opened_note(open_for_review))


@mcp.tool()
@inject_preferences
def create_draft(
    account: str,
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    attachments: Optional[List[str]] = None,
    sender: Optional[str] = None,
    open_for_review: bool = False,
) -> str:
    """
    Save a new message as a draft in the background, with optional file
    attachments. Never sends.

    Args:
        account: Account whose Drafts mailbox receives it (e.g. "Work").
        to: Recipients, comma-separated.
        subject: Subject line.
        body: Plain-text body.
        cc, bcc: Comma-separated addresses.
        attachments: File paths to attach (under the home directory).
        sender: From address; defaults to Mail's choice for the account.
        open_for_review: Then show the saved draft in Mail (default off).

    Returns:
        Draft id, subject and recipients.
    """
    paths, error = _attachments(attachments)
    if error:
        return error
    out = run_mail(
        f"""
        {_background_draft_script(
            f'account "{escape_applescript(account)}"',
            split_addresses(to), split_addresses(cc), split_addresses(bcc),
            sender or "", paths,
        )}
        {OPEN_DRAFT_SCRIPT if open_for_review else ""}
        """,
        bodyText=body,
        subjectText=subject,
    )
    return _report("New", out, paths, _opened_note(open_for_review))


def _opened_note(opened: bool) -> str:
    return "Opened in Mail for review." if opened else ""


@mcp.tool()
@inject_preferences
def open_draft(draft_id: int, account: Optional[str] = None) -> str:
    """
    Show a saved draft in a Mail compose window for review.

    Opens the existing draft itself, so no copy is made; it is sent only
    if the user presses Send.

    Args:
        draft_id: Mail id of the draft (returned by the draft tools).
        account: Optional account hint.
    """
    out = run_mail(
        f"""
        {find_message_script(draft_id, account, "Drafts")}
        set d to theMsg
        {OPEN_DRAFT_SCRIPT}
        set out to subject of d
        """
    )
    return f"Opened draft {draft_id} for review: {out}"


@mcp.tool()
@inject_preferences
def list_drafts(account: str) -> str:
    """
    List an account's drafts with their Mail ids.

    Args:
        account: Account name (e.g. "Work").

    Returns:
        One line per draft: id, date, subject, To.
    """
    out = run_mail(
        f"""
        {drafts_mailbox_script(f'account "{escape_applescript(account)}"')}
        repeat with d in (every message of draftsBox)
            set toList to ""
            repeat with r in to recipients of d
                set toList to toList & address of r & ", "
            end repeat
            set out to out & (id of d as string) & "{SEP}" & ((date sent of d) as «class isot» as string) & "{SEP}" & subject of d & "{SEP}" & toList & linefeed
        end repeat
        """
    )
    rows = [parse_fields(line, 4) for line in out.splitlines() if line.strip()]
    if not rows:
        return f"No drafts in {account}."
    return "\n".join(f"{i}  {d}  {s}  to: {t.rstrip(', ')}" for i, d, s, t in rows)


@mcp.tool()
@inject_preferences
def delete_draft(draft_id: int, account: str) -> str:
    """
    Delete one draft by its Mail id (Mail moves it to Trash).

    Only a message in the account's Drafts mailbox can be deleted here.

    Args:
        draft_id: Mail id of the draft.
        account: Account whose Drafts mailbox holds it.
    """
    out = run_mail(
        f"""
        {drafts_mailbox_script(f'account "{escape_applescript(account)}"')}
        set d to first message of draftsBox whose id is {int(draft_id)}
        set out to subject of d
        delete d
        """
    )
    return f"Deleted draft {draft_id}: {out}"

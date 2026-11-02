"""ID-first operations on saved drafts, with verified replacement on edit.

Mail exposes saved messages as read-only objects. Edits therefore create a
replacement and read it back before retiring the original into Trash. No
operation removes other drafts merely because they share a subject.
"""

import hashlib
import json
import re
import tempfile
from html.parser import HTMLParser
from collections import Counter
from email import message_from_string, policy
from email.utils import getaddresses
from pathlib import Path

from apple_mail_mcp import server
from apple_mail_mcp.core import escape_applescript, run_applescript


_DRAFT_NAMES = ["Drafts", "Brouillons", "Entwürfe", "Borradores", "Bozze", "Rascunhos", "Concepten", "下書き"]
_SENT_NAMES = ["Sent", "Sent Messages", "Sent Items", "Sent Mail", "Éléments envoyés", "Envoyés", "Gesendet", "Enviados", "Posta inviata"]
_JSON_HANDLERS = '''use framework "Foundation"
use scripting additions
on textValue(value)
    if value is missing value then return ""
    return value as text
end textValue
on encodeJSON(value)
    set encoded to current application's NSJSONSerialization's dataWithJSONObject:value options:0 |error|:(missing value)
    return (current application's NSString's alloc()'s initWithData:encoded encoding:(current application's NSUTF8StringEncoding)) as text
end encodeJSON
'''


class DraftError(ValueError):
    pass


def _mailbox(account, sent=False):
    names = _SENT_NAMES if sent else _DRAFT_NAMES
    literals = ", ".join('"' + escape_applescript(n) + '"' for n in names)
    return f'''set targetAccount to account "{escape_applescript(account)}"
        set targetMailbox to missing value
        repeat with lookupName in {{{literals}}}
            try
                set targetMailbox to mailbox (lookupName as text) of targetAccount
                exit repeat
            end try
        end repeat
        if targetMailbox is missing value then error "Could not resolve {'Sent' if sent else 'Drafts'} mailbox"'''


def _run_json(script):
    raw = run_applescript(_JSON_HANDLERS + script)
    if raw.startswith("Error:"):
        raise DraftError(raw[6:].strip())
    try:
        return json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise DraftError("Mail returned an invalid draft response") from exc


def _query(account, message_id=None, include_source=False, sent=False, internet_message_id=None):
    selection = "set selectedMessages to every message of targetMailbox"
    if message_id is not None:
        selection = f"set selectedMessages to {{«class mssg» id {int(message_id)} of targetMailbox}}"
    elif internet_message_id:
        selection = f'set selectedMessages to every message of targetMailbox whose message id is "{escape_applescript(internet_message_id)}"'
    return _run_json(f'''
    set payload to current application's NSMutableArray's array()
    tell application "Mail"
        try
            {_mailbox(account, sent)}
            {selection}
            repeat with aDraft in selectedMessages
                if not (deleted status of aDraft) then
                    set entry to current application's NSMutableDictionary's dictionary()
                    entry's setObject:(my textValue(id of aDraft)) forKey:"message_id"
                    entry's setObject:(my textValue(message id of aDraft)) forKey:"internet_message_id"
                    entry's setObject:(my textValue(subject of aDraft)) forKey:"subject"
                    entry's setObject:(my textValue(sender of aDraft)) forKey:"sender"
                    entry's setObject:(my textValue(name of targetMailbox)) forKey:"mailbox"
                    entry's setObject:(address of every to recipient of aDraft) forKey:"to"
                    entry's setObject:(address of every cc recipient of aDraft) forKey:"cc"
                    entry's setObject:(address of every bcc recipient of aDraft) forKey:"bcc"
                    set attachmentNames to {{}}
                    repeat with anAttachment in mail attachments of aDraft
                        set end of attachmentNames to my textValue(name of anAttachment)
                    end repeat
                    entry's setObject:attachmentNames forKey:"attachments"
                    if {str(include_source).lower()} then
                        entry's setObject:(my textValue(content of aDraft)) forKey:"body"
                        entry's setObject:(my textValue(source of aDraft)) forKey:"raw_source"
                    end if
                    payload's addObject:entry
                end if
            end repeat
        on error errMsg
            return "Error: " & errMsg
        end try
    end tell
    return my encodeJSON(payload)
    ''')


def _select(items, message_id=None, internet_message_id=None, draft_subject=None):
    if message_id is not None:
        items = [x for x in items if x["message_id"] == str(int(message_id))]
    elif internet_message_id:
        target = internet_message_id.strip().strip("<>")
        items = [x for x in items if x["internet_message_id"].strip("<>") == target]
    elif draft_subject:
        items = [x for x in items if draft_subject.casefold() in x["subject"].casefold()]
    else:
        raise DraftError("Provide message_id, internet_message_id, or a unique draft_subject")
    if not items:
        raise DraftError("No matching draft found")
    if len(items) != 1:
        ids = ", ".join(x["message_id"] for x in items)
        raise DraftError(f"Ambiguous draft selection; specify a numeric message_id from: {ids}")
    return items[0]


def _addresses(value):
    return [addr for _, addr in getaddresses([value or ""]) if addr]


def _norm(value):
    return " ".join(value.replace("\ufffc", "").split())


class _BodyText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored = 0
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag in {"head", "style", "script", "object"}:
            self.ignored += 1
        if not self.ignored and tag in {"br", "p", "div", "li"}:
            self.text.append(" ")

    def handle_endtag(self, tag):
        if tag in {"head", "style", "script", "object"}:
            self.ignored = max(0, self.ignored - 1)
        if not self.ignored:
            self.text.append(" ")

    def handle_data(self, data):
        if not self.ignored:
            self.text.append(data)


def _html_text(value):
    parser = _BodyText()
    parser.feed(value)
    return "".join(parser.text)


class _MailFragment(HTMLParser):
    """Unwrap only Mail's generated share scaffolding; retain authored markup."""
    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.nodes = []
        self.stack = [("root", {}, "", self.nodes)]

    def handle_starttag(self, tag, attrs):
        node = (tag, dict(attrs), self.get_starttag_text(), [])
        self.stack[-1][3].append(node)
        if tag not in self._VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1][3].append((tag, dict(attrs), self.get_starttag_text(), []))

    def handle_endtag(self, tag):
        if tag in self._VOID:
            return
        if len(self.stack) == 1 or self.stack[-1][0] != tag:
            raise DraftError("Unbalanced HTML cannot be rebuilt safely")
        self.stack.pop()

    def handle_data(self, value):
        self.stack[-1][3].append(value)

    def handle_entityref(self, name):
        self.handle_data("&" + name + ";")

    def handle_charref(self, name):
        self.handle_data("&#" + name + ";")

    def handle_comment(self, value):
        self.handle_data("<!--" + value + "-->")

    def render(self, nodes, in_share=False):
        result = []
        for node in nodes:
            if isinstance(node, str):
                result.append(node)
                continue
            tag, attrs, opening, children = node
            classes = (attrs.get("class") or "").split()
            share = "Apple-Mail-URLShareWrapperClass" in classes
            top = "Apple-Mail-URLShareUserContentTopClass" in classes
            if tag == "head":
                if self.render(children).strip():
                    raise DraftError("HTML head styling cannot be rebuilt safely")
                continue
            if tag == "body":
                styles = set(x.strip().replace(" ", "").lower() for x in (attrs.get("style") or "").split(";") if x.strip())
                if styles - {"overflow-wrap:break-word", "-webkit-nbsp-mode:space", "line-break:after-white-space"}:
                    raise DraftError("HTML document styling cannot be rebuilt safely")
            if tag in {"html", "body"} or share or top or (in_share and tag == "blockquote" and attrs.get("type") == "cite"):
                fragment = self.render(children, in_share=share)
                if not top or _norm(_html_text(fragment)):
                    result.append(fragment)
            else:
                result.append(opening + self.render(children) + ("" if tag in self._VOID or opening.endswith("/>") else f"</{tag}>"))
        return "".join(result)


def _mail_fragment(value):
    parser = _MailFragment()
    parser.feed(value)
    parser.close()
    if len(parser.stack) != 1:
        raise DraftError("Unbalanced HTML cannot be rebuilt safely")
    return parser.render(parser.nodes).strip()


def _parts(raw):
    if not raw.strip():
        raise DraftError("Draft source is unavailable; original left unchanged")
    msg = message_from_string(raw, policy=policy.default)
    if msg.defects:
        raise DraftError("Draft MIME source is incomplete; original left unchanged")
    text, html, attachments = None, None, []
    for part in msg.walk():
        kind = part.get_content_type()
        if kind in {"multipart/signed", "multipart/encrypted", "application/pkcs7-mime", "application/x-pkcs7-mime"}:
            raise DraftError("Signed or encrypted drafts cannot be rebuilt safely")
        if part.get("Content-ID") and (not part.get_filename() or part.get_content_maintype() == "image"):
            raise DraftError("Inline MIME parts cannot be rebuilt safely; original left unchanged")
        if part.get_content_disposition() == "attachment" or part.get_filename():
            data = part.get_payload(decode=True)
            if data is None:
                raise DraftError("An attachment is unavailable; original left unchanged")
            name = part.get_filename() or "attachment"
            if name != Path(name).name or name in {".", ".."} or any(c in name for c in ("\0", ":", "\\")):
                raise DraftError("An attachment has an unsafe filename")
            attachments.append((name, data))
        elif kind == "text/plain" and text is None:
            text = part.get_content()
        elif kind == "text/html" and html is None:
            html = part.get_content()
        if part.defects:
            raise DraftError("Draft MIME data could not be decoded safely; original left unchanged")
    if text is None and html is None:
        raise DraftError("Draft has no supported text body")
    return msg, text if text and text.strip() else (_html_text(html) if html else ""), html, attachments


def _attachment_hashes(parts):
    return Counter((name, hashlib.sha256(data).hexdigest()) for name, data in parts)


def _verify(saved, expected):
    for field in ("subject",):
        if saved[field] != expected[field]:
            raise DraftError(f"Saved {field} differs; original left unchanged")
    for field in ("to", "cc", "bcc"):
        if sorted(x.casefold() for x in saved[field]) != sorted(x.casefold() for x in expected[field]):
            raise DraftError(f"Saved {field} recipients differ; original left unchanged")
    if sorted(x.casefold() for x in _addresses(saved["sender"])) != sorted(x.casefold() for x in _addresses(expected["sender"])):
        raise DraftError("Saved sender differs; original left unchanged")
    _, text, html, attachments = _parts(saved["raw_source"])
    if _attachment_hashes(attachments) != _attachment_hashes(expected["attachment_data"]):
        raise DraftError("Saved attachment contents differ; original left unchanged")
    if expected["body_html"] is not None:
        # Refuse lossy HTML rebuilds rather than retiring the only rich copy.
        if html is None or _mail_fragment(expected["body_html"]) != _mail_fragment(html):
            raise DraftError("Saved HTML formatting could not be verified; original left unchanged")
    elif _norm(text) != _norm(expected["body"]):
        raise DraftError("Saved body differs; original left unchanged")


def _retire(account, item, expected_source=None):
    guard = ""
    if expected_source is not None:
        canonical = expected_source.replace("\r\n", "\n").replace("\r", "\n")
        guard = f'''set sourceText to current application's NSString's stringWithString:(source of targetDraft as text)
            set sourceText to sourceText's stringByReplacingOccurrencesOfString:(return & linefeed) withString:linefeed
            set sourceText to sourceText's stringByReplacingOccurrencesOfString:return withString:linefeed
            considering case
                if (sourceText as text) is not "{escape_applescript(canonical)}" then
                    error "Original draft changed during the update; both versions retained"
                end if
            end considering'''
    script = f'''
    tell application "Mail"
        try
            {_mailbox(account)}
            set targetDraft to «class mssg» id {int(item['message_id'])} of targetMailbox
            {guard}
            delete targetDraft
            return "deleted"
        on error errMsg
            return "Error: " & errMsg
        end try
    end tell
    '''
    result = run_applescript(_JSON_HANDLERS + script)
    if result != "deleted":
        raise DraftError(result)


def _save_replacement(account, expected, paths, visible):
    recipients = ""
    for field, kind in (("to", "to"), ("cc", "cc"), ("bcc", "bcc")):
        for address in expected[field]:
            recipients += f'\nmake new {kind} recipient at end of {kind} recipients of newDraft with properties {{address:"{escape_applescript(address)}"}}'
    attachments = ""
    for path in paths:
        attachments += f'''\ntell newDraft
                set attachmentFile to POSIX file "{escape_applescript(str(path))}"
                make new attachment with properties {{file name:attachmentFile}} at after the last paragraph
            end tell'''
    html = ""
    if expected["body_html"] is not None:
        html = f'set html content of newDraft to "{escape_applescript(_mail_fragment(expected["body_html"]))}"'
    close = "" if visible else "close newDraft saving yes"
    return _run_json(f'''
    tell application "Mail"
        try
            {_mailbox(account)}
            set priorIDs to id of every message of targetMailbox
            set existingComposers to every outgoing message whose subject is "{escape_applescript(expected['old_subject'])}" and visible is true
            if (count of existingComposers) > 0 then error "A composer for this subject is already open; save and close it before editing the saved draft"
            set newDraft to make new outgoing message with properties {{visible:{str(visible).lower()}}}
            set sender of newDraft to "{escape_applescript(expected['sender'])}"
            set message signature of newDraft to missing value
            set subject of newDraft to "{escape_applescript(expected['subject'])}"
            set content of newDraft to "{escape_applescript(expected['body'])}"
            {recipients}
            {attachments}
            {html}
            save newDraft
            if {str(visible).lower()} then set visible of newDraft to true
            set outgoingID to id of newDraft
            {close}
            repeat 20 times
                set newIDs to {{}}
                repeat with candidate in (every message of targetMailbox whose subject is "{escape_applescript(expected['subject'])}")
                    set candidateID to id of candidate
                    if priorIDs does not contain candidateID and not (deleted status of candidate) then set end of newIDs to candidateID as text
                end repeat
                if (count of newIDs) > 0 then exit repeat
                delay 0.25
            end repeat
            set payload to current application's NSMutableDictionary's dictionary()
            payload's setObject:newIDs forKey:"message_ids"
            payload's setObject:(outgoingID as text) forKey:"outgoing_id"
        on error errMsg
            return "Error: " & errMsg
        end try
    end tell
    return my encodeJSON(payload)
    ''')


def _replace(account, original, subject=None, to=None, body=None, cc=None, bcc=None, from_address=None, body_html=None, visible=False):
    msg, old_text, old_html, attachments = _parts(original["raw_source"])
    if msg.get("In-Reply-To") or msg.get("References"):
        raise DraftError("Mail cannot preserve reply headers when rebuilding this threaded draft; original left unchanged")
    if old_html and "cid:" in old_html.lower() and body is None and body_html is None:
        raise DraftError("The stored HTML refers to inline MIME parts; supply a replacement body or leave the original unchanged")
    if len(attachments) != len(original["attachments"]):
        raise DraftError("Not all existing attachments are available in the source; original left unchanged")
    if from_address is not None and _addresses(from_address) != _addresses(original["sender"]):
        raise DraftError("Changing the sender during a draft rebuild is unsupported; original left unchanged")
    expected = dict(original, old_subject=original["subject"], attachment_data=attachments)
    expected["subject"] = original["subject"] if subject is None else subject
    expected["body"] = old_text if body is None else body
    expected["body_html"] = body_html if body_html is not None else (old_html if body is None else None)
    for field, value in (("to", to), ("cc", cc), ("bcc", bcc)):
        if value is not None:
            addresses = _addresses(value)
            parsed = getaddresses([value])
            if value.strip() and (not parsed or any("@" not in addr for _, addr in parsed)):
                raise DraftError(f"Invalid {field} recipients")
            expected[field] = addresses
    with tempfile.TemporaryDirectory(prefix="mail-draft-edit-") as folder:
        paths = []
        for index, (name, data) in enumerate(attachments):
            path = Path(folder) / str(index) / name
            path.parent.mkdir()
            path.write_bytes(data)
            paths.append(path)
        try:
            created = _save_replacement(account, expected, paths, visible)
        except Exception as exc:
            raise DraftError(f"Could not save replacement: {exc}. Original retained; inspect Drafts before retrying") from exc
        ids = created["message_ids"]
        if len(ids) != 1:
            raise DraftError(f"Replacement identity is ambiguous ({ids}); original retained. Inspect drafts before retrying")
        replacement_id = ids[0]
        try:
            replacement = _select(_query(account, replacement_id, include_source=True), message_id=replacement_id)
            _verify(replacement, expected)
            _retire(account, original, expected_source=original["raw_source"])
        except DraftError as exc:
            raise DraftError(f"{exc}. Replacement message_id={replacement_id}; inspect it before retrying") from exc
    replacement.pop("raw_source", None)
    return {"status": "editing" if visible else "updated", "original_message_id": original["message_id"], "draft": replacement, "verified": True, "outgoing_id": created["outgoing_id"]}


def _format(result, output_format):
    if output_format == "json":
        return json.dumps(result, ensure_ascii=False)
    lines = [f"Draft operation: {result['status']}"]
    for item in result.get("items", [result["draft"]] if "draft" in result else []):
        lines.extend([f"Subject: {item['subject']}", f"Message ID: {item['message_id']}", f"Internet Message-ID: {item['internet_message_id']}", f"Mailbox: {item['mailbox']}", f"From: {item['sender']}", f"To: {', '.join(item['to'])}", f"Cc: {', '.join(item['cc'])}", f"Bcc: {', '.join(item['bcc'])}", f"Attachments: {len(item['attachments'])}"])
        if "body" in item:
            lines.extend(["Body:", item["body"]])
            if item.get("body_truncated"):
                lines.append("[Body truncated at max_chars]")
    if "remaining_draft_ids" in result:
        lines.append("Remaining Draft IDs: " + ", ".join(result["remaining_draft_ids"]))
    if result.get("verified"):
        lines.append("Saved replacement verification: passed")
    if "original_message_id" in result:
        lines.append("Retired original ID: " + result["original_message_id"])
    if result.get("note"):
        lines.append(result["note"])
    return "\n".join(lines)


def manage_existing_drafts(account, action, *, message_id=None, internet_message_id=None, draft_subject=None, subject=None, to=None, body=None, cc=None, bcc=None, from_address=None, body_html=None, output_format="text", max_chars=20000):
    if action not in {"list", "read", "update", "edit", "open", "send", "delete", "verify_sent"}:
        return f"Error: Invalid action '{action}'. Use: list, create, read, update, edit, open, send, delete, verify_sent"
    if action == "send" and server.READ_ONLY:
        return "Error: Sending drafts is disabled in read-only mode."
    if message_id is not None and (not isinstance(message_id, str) or not re.fullmatch(r"[0-9]+", message_id)):
        return "Error: message_id must contain only ASCII digits"
    if output_format not in {"text", "json"}:
        return "Error: output_format must be text or json"
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars <= 0:
        return "Error: max_chars must be a positive integer"
    if message_id is not None and internet_message_id:
        return "Error: provide only one exact identifier"
    if internet_message_id:
        internet_message_id = internet_message_id.strip().strip("<>")
    try:
        if action == "verify_sent":
            if not internet_message_id:
                raise DraftError("internet_message_id is required for Sent verification")
            found = _query(account, sent=True, internet_message_id=internet_message_id.strip().strip("<>"))
            remaining = _query(account, internet_message_id=internet_message_id.strip().strip("<>"))
            return _format({"status": "sent_verified" if found else "not_confirmed", "items": found, "remaining_draft_ids": [x["message_id"] for x in remaining], "note": "No drafts were removed. Inspect remaining IDs before cleanup."}, output_format)
        items = _query(account, message_id, internet_message_id=internet_message_id)
        if action == "list":
            return _format({"status": "listed", "items": items, "note": "Use numeric message_id for exact operations. Same-subject drafts are not assumed to be duplicates."}, output_format)
        selected = _select(items, message_id, internet_message_id, draft_subject)
        if action in {"read", "update", "edit"}:
            selected = _select(_query(account, selected["message_id"], include_source=True), message_id=selected["message_id"])
        if action in {"update", "edit"}:
            if action == "update" and all(x is None for x in (subject, to, body, cc, bcc, from_address, body_html)):
                raise DraftError("Provide at least one field to update")
            result = _replace(account, selected, subject, to, body, cc, bcc, from_address, body_html, visible=action == "edit")
        elif action == "read":
            selected.pop("raw_source", None)
            selected["body_truncated"] = len(selected["body"]) > max_chars
            selected["body"] = selected["body"][:max_chars]
            result = {"status": "read", "draft": selected}
        elif action == "delete":
            _retire(account, selected)
            result = {"status": "deleted", "draft": selected}
        else:
            command = f"open targetDraft" if action == "open" else "set accepted to send targetDraft\nif not accepted then error \"Mail did not accept the send request\""
            raw = run_applescript(f'''tell application "Mail"
                try
                    {_mailbox(account)}
                    set targetDraft to «class mssg» id {int(selected['message_id'])} of targetMailbox
                    {command}
                    return "accepted"
                on error errMsg
                    return "Error: " & errMsg
                end try
            end tell''')
            if raw != "accepted":
                raise DraftError(raw)
            result = {"status": "viewer_opened" if action == "open" else "send_requested", "draft": selected, "note": ("Mail opened a message viewer, not an editable composer. Use read/update, or edit for a verified editable replacement." if action == "open" else "Delivery is not yet verified. Use verify_sent with this Internet Message-ID before retrying or removing any leftover draft.")}
        return _format(result, output_format)
    except Exception as exc:
        return f"Error: {exc}"

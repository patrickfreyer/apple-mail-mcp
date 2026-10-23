"""Read one message by Mail's internal numeric id, without a mailbox scan."""

import json
import re

from apple_mail_mcp.server import mcp
from apple_mail_mcp.core import (
    build_mailbox_ref, escape_applescript, inject_preferences, run_applescript,
)


# Escape percent before pipe, and decode in reverse order. Unlike line-based
# records this preserves newlines, literal escape sequences and empty fields.
_FIELD_HANDLER = '''
on encodeField(value)
    if value is missing value then set value to ""
    set value to value as text
    set oldDelimiters to AppleScript's text item delimiters
    set AppleScript's text item delimiters to "%"
    set pieces to text items of value
    set AppleScript's text item delimiters to "%25"
    set value to pieces as text
    set AppleScript's text item delimiters to "|"
    set pieces to text items of value
    set AppleScript's text item delimiters to "%7C"
    set value to pieces as text
    set AppleScript's text item delimiters to oldDelimiters
    return value & "|"
end encodeField

on attachmentField(anAttachment, which)
    tell application "Mail"
        try
            if which is "name" then return my encodeField(name of anAttachment)
            if which is "mime" then return my encodeField(MIME type of anAttachment)
            return my encodeField(file size of anAttachment)
        on error
            return my encodeField("")
        end try
    end tell
end attachmentField
'''


def _size(value: str):
    """Mail reports `missing value` for some attachments; keep the rest readable."""
    return int(value) if value.isdigit() else None


@mcp.tool()
@inject_preferences
def read_email(
    account: str, message_id: str, mailbox: str = "INBOX",
    max_chars: int = 20000, output_format: str = "text",
) -> str:
    """Read headers, plain-text body and attachment metadata for one message.

    Use the numeric message_id returned by search_emails, not the RFC
    Message-ID header. The lookup never scans messages. max_chars caps only
    the body, with explicit truncation metadata. output_format is text or json.
    Attachment contents are never returned.
    """
    message_id = message_id.strip()
    if not re.fullmatch(r"[0-9]+", message_id):
        return "Error: message_id must contain only digits"
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars <= 0:
        return "Error: max_chars must be a positive integer"
    if output_format not in {"text", "json"}:
        return "Error: output_format must be text or json"

    mailbox_resolution = build_mailbox_ref(mailbox, account_var="targetAccount")
    not_found = (
        f"Error: message {message_id} not found in mailbox {mailbox} of account {account}"
    )
    script = _FIELD_HANDLER + f'''
    tell application "Mail"
        try
            set targetAccount to account "{escape_applescript(account)}"
            {mailbox_resolution}
            set targetMessage to «class mssg» id {message_id} of targetMailbox
            set internalID to id of targetMessage
        on error
            return "{escape_applescript(not_found)}"
        end try
        set outputText to my encodeField(subject of targetMessage)
        set outputText to outputText & my encodeField(sender of targetMessage)
        set outputText to outputText & my encodeField(date received of targetMessage)
        set outputText to outputText & my encodeField(internalID)
        set outputText to outputText & my encodeField(message id of targetMessage)
        set recipientGroups to {{to recipients of targetMessage, cc recipients of targetMessage}}
        set groupIndex to 1
        repeat until groupIndex > 2
            set recipientGroup to item groupIndex of recipientGroups
            set outputText to outputText & my encodeField(count of recipientGroup)
            set recipientIndex to 1
            repeat until recipientIndex > (count of recipientGroup)
                set outputText to outputText & my encodeField(address of item recipientIndex of recipientGroup)
                set recipientIndex to recipientIndex + 1
            end repeat
            set groupIndex to groupIndex + 1
        end repeat
        set attachmentList to mail attachments of targetMessage
        set outputText to outputText & my encodeField(count of attachmentList)
        set attachmentIndex to 1
        repeat until attachmentIndex > (count of attachmentList)
            set anAttachment to item attachmentIndex of attachmentList
            -- Each property on its own: Mail raises -10000 for `MIME type`
            -- on some Exchange attachments while name and size still answer.
            set outputText to outputText & my attachmentField(anAttachment, "name")
            set outputText to outputText & my attachmentField(anAttachment, "mime")
            set outputText to outputText & my attachmentField(anAttachment, "size")
            set attachmentIndex to attachmentIndex + 1
        end repeat
        return outputText & my encodeField(content of targetMessage)
    end tell
    '''
    try:
        raw = run_applescript(script)
    except Exception as exc:
        return f"Error: could not read message {message_id}: {exc}"
    if raw.startswith("Error:"):
        return raw
    try:
        if not raw.endswith("|"):
            raise ValueError("missing field terminator")
        fields = iter(part.replace("%7C", "|").replace("%25", "%")
                      for part in raw[:-1].split("|"))
        data = dict(zip(
            ("subject", "sender", "date_received", "message_id", "internet_message_id"),
            (next(fields) for _ in range(5)),
        ))
        for key in ("to", "cc"):
            data[key] = [next(fields) for _ in range(int(next(fields))) ]
        data["attachments"] = [
            {"name": next(fields), "mime_type": next(fields) or None,
             "file_size": _size(next(fields))}
            for _ in range(int(next(fields)))
        ]
        body = next(fields)
        if list(fields):
            raise ValueError("unexpected fields")
    except (ValueError, StopIteration, RuntimeError) as exc:
        return f"Error: could not parse message {message_id}: {exc}"
    data.update(account=account, mailbox=mailbox, body=body[:max_chars],
                body_truncated=len(body) > max_chars, body_total_chars=len(body))
    if output_format == "json":
        return json.dumps(data, ensure_ascii=False)
    lines = [f"Subject: {data['subject']}", f"From: {data['sender']}",
             f"To: {', '.join(data['to'])}", f"Cc: {', '.join(data['cc'])}",
             f"Date received: {data['date_received']}", f"ID: {data['message_id']}",
             f"Message-ID: {data['internet_message_id']}", "Attachments:"]
    lines.extend(
        f"- {a['name']} ({a['mime_type'] or 'unknown type'}, "
        f"{'unknown size' if a['file_size'] is None else str(a['file_size']) + ' bytes'})"
        for a in data['attachments'])
    if not data['attachments']:
        lines.append("(none)")
    lines.extend(["", data['body']])
    if data['body_truncated']:
        lines.append(f"[truncated at {max_chars} of {len(body)} characters]")
    return "\n".join(lines)

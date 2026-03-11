"""Composition tools: sending, replying, forwarding, and drafts."""

import os
import subprocess
import tempfile
from typing import Optional, List, Tuple


from apple_mail_mcp.server import mcp
from apple_mail_mcp.core import inject_preferences, escape_applescript, run_applescript, inbox_mailbox_script


def _send_html_email(
    account: str,
    to: str,
    subject: str,
    body_plain: str,
    body_html: str,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    attachments_script: str = "",
    mode: str = "send",
) -> str:
    """Send an HTML-formatted email via NSPasteboard clipboard injection.

    Uses AppleScriptObjC to place HTML on the clipboard with the proper
    pasteboard type, creates a compose window, tabs into the body, and
    pastes.  Then sends, saves as draft, or leaves open for review.
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

    # Mode-specific behaviour after paste
    if mode == "send":
        post_paste_script = '''
            -- Send via keyboard shortcut
            keystroke "d" using {command down, shift down}
        '''
        success_text = "Email sent successfully (HTML)"
    elif mode == "draft":
        post_paste_script = '''
            -- Save as draft: Cmd+S then close
            keystroke "s" using command down
            delay 0.5
        '''
        success_text = "Email saved as draft (HTML)"
    else:  # open
        post_paste_script = "-- Leaving open for review"
        success_text = "Email opened in Mail for review (HTML). Edit and send when ready."

    # Write HTML to temp file so the AppleScript can read it without
    # worrying about escaping quotes/special chars in the HTML string.
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", prefix="mail_html_",
        delete=False, encoding="utf-8",
    )
    tmp.write(body_html)
    tmp.close()
    html_temp_path = tmp.name

    script = f'''
use framework "Foundation"
use framework "AppKit"
use scripting additions

-- Step 1: Read HTML from temp file and place on clipboard
set htmlString to do shell script "cat '{html_temp_path}'"
set pb to current application's NSPasteboard's generalPasteboard()

-- Save current clipboard for restoration
set oldClip to pb's stringForType:(current application's NSPasteboardTypeString)

pb's clearContents()
set htmlData to (current application's NSString's stringWithString:htmlString)'s dataUsingEncoding:(current application's NSUTF8StringEncoding)
pb's setData:htmlData forType:(current application's NSPasteboardTypeHTML)

-- Step 2: Create compose window (empty body so signature doesn't interfere)
tell application "Mail"
    set newMsg to make new outgoing message with properties {{subject:"{escaped_subject}", content:"", visible:true}}
    set emailAddrs to email addresses of account "{safe_account}"
    set senderAddress to item 1 of emailAddrs
    set sender of newMsg to senderAddress
    tell newMsg
        {to_lines}
        {cc_lines}
        {bcc_lines}
        {attachments_script}
    end tell
    activate
end tell

-- Step 3: Wait for compose window to render
delay 2.5

-- Step 4: Tab from header fields into body, then paste
tell application "System Events"
    set frontmost of process "Mail" to true
    delay 0.5
    tell process "Mail"
        -- Tab through: To -> Cc -> Bcc -> Subject -> Body
        -- 7 tabs covers all combinations of visible/hidden CC/BCC fields
        repeat 7 times
            key code 48
            delay 0.1
        end repeat
        delay 0.3

        -- Select all in body and paste HTML
        keystroke "a" using command down
        delay 0.2
        keystroke "v" using command down
        delay 0.5

        {post_paste_script}
    end tell
end tell

-- Step 5: Clean up temp file
do shell script "rm -f '{html_temp_path}'"

-- Step 6: Restore clipboard
if oldClip is not missing value then
    pb's clearContents()
    pb's setString:oldClip forType:(current application's NSPasteboardTypeString)
end if

return "{success_text}"
'''

    try:
        result = subprocess.run(
            ["osascript", "-"],
            input=script.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            return f"Error sending HTML email: {stderr}"
        output = result.stdout.decode("utf-8", errors="replace").strip()
        # Build confirmation message
        confirm = f"{output}\n\nFrom: {account}\nTo: {to}\nSubject: {subject}"
        if cc:
            confirm += f"\nCC: {cc}"
        if bcc:
            confirm += f"\nBCC: {bcc}"
        return confirm
    except subprocess.TimeoutExpired:
        return "Error: HTML email script timed out"
    finally:
        if os.path.exists(html_temp_path):
            os.unlink(html_temp_path)


def _validate_attachment_paths(attachments: str) -> Tuple[List[str], Optional[str]]:
    """Validate and resolve attachment file paths.

    Splits comma-separated paths, expands tildes, resolves symlinks,
    and enforces security constraints (home-dir-only, no sensitive dirs,
    file must exist).

    Returns:
        A tuple of (resolved_paths, error_message).
        If error_message is not None, resolved_paths should be ignored.
    """
    home_dir = os.path.expanduser('~')
    sensitive_dirs = [
        os.path.join(home_dir, '.ssh'),
        os.path.join(home_dir, '.gnupg'),
        os.path.join(home_dir, '.config'),
        os.path.join(home_dir, '.aws'),
        os.path.join(home_dir, '.claude'),
        os.path.join(home_dir, 'Library', 'LaunchAgents'),
        os.path.join(home_dir, 'Library', 'LaunchDaemons'),
        os.path.join(home_dir, 'Library', 'Keychains'),
    ]

    resolved_paths: List[str] = []
    raw_paths = [p.strip() for p in attachments.split(',')]

    for raw_path in raw_paths:
        if not raw_path:
            continue

        # Expand tilde and resolve symlinks
        expanded = os.path.expanduser(raw_path)
        resolved = os.path.realpath(expanded)

        # Must be under the user's home directory
        if not resolved.startswith(home_dir + os.sep) and resolved != home_dir:
            return [], f"Error: Attachment path must be under your home directory ({home_dir}). Got: {resolved}"

        # Block sensitive directories
        for sensitive_dir in sensitive_dirs:
            if resolved.startswith(sensitive_dir + os.sep) or resolved == sensitive_dir:
                return [], f"Error: Cannot attach files from sensitive directory: {sensitive_dir}"

        # File must exist
        if not os.path.isfile(resolved):
            return [], f"Error: Attachment file does not exist: {resolved}"

        resolved_paths.append(resolved)

    if not resolved_paths:
        return [], "Error: No valid attachment paths provided."

    return resolved_paths, None


@mcp.tool()
@inject_preferences
def reply_to_email(
    account: str,
    subject_keyword: str,
    reply_body: str,
    reply_to_all: bool = False,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    send: bool = True,
    mode: Optional[str] = None,
    attachments: Optional[str] = None
) -> str:
    """
    Reply to an email matching a subject keyword.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        subject_keyword: Keyword to search for in email subjects
        reply_body: The body text of the reply
        reply_to_all: If True, reply to all recipients; if False, reply only to sender (default: False)
        cc: Optional CC recipients, comma-separated for multiple
        bcc: Optional BCC recipients, comma-separated for multiple
        send: If True (default), send immediately; if False, save as draft. Ignored if mode is set.
        mode: Delivery mode — "send" (send immediately), "draft" (save silently), or "open" (open compose window for review). Overrides send parameter when set.
        attachments: Optional file paths to attach, comma-separated for multiple (e.g., "/path/to/file1.png,/path/to/file2.pdf")

    Returns:
        Confirmation message with details of the reply sent, saved draft, or opened draft
    """

    # Escape all user inputs for AppleScript
    safe_account = escape_applescript(account)
    safe_subject_keyword = escape_applescript(subject_keyword)
    escaped_body = escape_applescript(reply_body)

    # Build the reply command based on reply_to_all flag
    if reply_to_all:
        reply_command = 'set replyMessage to reply foundMessage with opening window reply to all'
    else:
        reply_command = 'set replyMessage to reply foundMessage with opening window'

    # Build CC recipients if provided
    cc_script = ''
    if cc:
        cc_addresses = [addr.strip() for addr in cc.split(',')]
        for addr in cc_addresses:
            safe_addr = escape_applescript(addr)
            cc_script += f'''
            make new cc recipient at end of cc recipients of replyMessage with properties {{address:"{safe_addr}"}}
            '''

    # Build BCC recipients if provided
    bcc_script = ''
    if bcc:
        bcc_addresses = [addr.strip() for addr in bcc.split(',')]
        for addr in bcc_addresses:
            safe_addr = escape_applescript(addr)
            bcc_script += f'''
            make new bcc recipient at end of bcc recipients of replyMessage with properties {{address:"{safe_addr}"}}
            '''

    # Build attachment script if provided
    attachment_script = ''
    attachment_info = ''
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
            attachment_info += f'  {path}\n'

    safe_cc = escape_applescript(cc) if cc else ""
    safe_bcc = escape_applescript(bcc) if bcc else ""
    safe_attachment_info = escape_applescript(attachment_info) if attachment_info else ""

    # Resolve delivery mode: mode parameter takes precedence over send boolean
    if mode is not None:
        if mode not in ("send", "draft", "open"):
            return f"Error: Invalid mode '{mode}'. Use: send, draft, open"
        effective_mode = mode
    else:
        effective_mode = "send" if send else "draft"

    # Determine behavior per mode
    if effective_mode == "send":
        header_text = "SENDING REPLY"
        send_or_draft_command = "send replyMessage"
        success_text = "✓ Reply sent successfully!"
        # For send, Mail handles the quoted original via the HTML layer
        set_content_script = f'set content of replyMessage to "{escaped_body}"'
    elif effective_mode == "open":
        header_text = "OPENING REPLY FOR REVIEW"
        # For open, we make the window visible and use System Events keystroke
        # to type the reply. This preserves Mail.app's native quoted original
        # (setting content via AppleScript overwrites the async HTML layer).
        _keystroke_lines = reply_body.split('\n')
        _keystroke_script = ''
        for i, line in enumerate(_keystroke_lines):
            safe_line = escape_applescript(line)
            _keystroke_script += f'keystroke "{safe_line}"\n                        '
            if i < len(_keystroke_lines) - 1:
                _keystroke_script += 'keystroke return\n                        '
        send_or_draft_command = f'''
                set visible of replyMessage to true
                activate
                delay 1.5
                tell application "System Events"
                    tell process "Mail"
                        {_keystroke_script}
                    end tell
                end tell'''
        success_text = "✓ Reply opened in Mail for review. Edit and send when ready."
        set_content_script = '-- content set via keystroke'
    else:  # draft
        header_text = "SAVING REPLY AS DRAFT"
        send_or_draft_command = "close window 1 saving yes"
        success_text = "✓ Reply saved as draft!"
        # For draft, we must manually build the quoted original because
        # close-window-saving-yes saves the content property literally
        # and the reply message's content property is initially empty
        set_content_script = f'''set origContent to content of foundMessage
                set origSender to sender of foundMessage
                set origDate to date received of foundMessage
                set quotedText to "On " & (origDate as string) & ", " & origSender & " wrote:" & return & return & origContent
                set content of replyMessage to "{escaped_body}" & return & return & quotedText'''

    script = f'''
    tell application "Mail"
        set outputText to "{header_text}" & return & return

        try
            set targetAccount to account "{safe_account}"
            {inbox_mailbox_script("inboxMailbox", "targetAccount")}
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

                -- Ensure the reply is from the correct account
                set emailAddrs to email addresses of targetAccount
                set senderAddress to item 1 of emailAddrs
                set sender of replyMessage to senderAddress

                -- Set reply content
                {set_content_script}
                delay 0.5

                -- Add CC/BCC recipients
                {cc_script}
                {bcc_script}

                -- Add attachments
                {attachment_script}

                -- Send or save as draft
                {send_or_draft_command}

                set outputText to outputText & "{success_text}" & return & return
                set outputText to outputText & "Original email:" & return
                set outputText to outputText & "  Subject: " & messageSubject & return
                set outputText to outputText & "  From: " & messageSender & return
                set outputText to outputText & "  Date: " & (messageDate as string) & return & return
                set outputText to outputText & "Reply body:" & return
                set outputText to outputText & "  " & "{escaped_body}" & return
    '''

    if cc:
        script += f'''
                set outputText to outputText & "CC: {safe_cc}" & return
    '''

    if bcc:
        script += f'''
                set outputText to outputText & "BCC: {safe_bcc}" & return
    '''

    if attachments:
        script += f'''
                set outputText to outputText & "Attachments:" & return & "{safe_attachment_info}" & return
    '''

    script += f'''
            else
                set outputText to outputText & "⚠ No email found matching: {safe_subject_keyword}" & return
            end if

        on error errMsg
            return "Error: " & errMsg & return & "Please check that the account name is correct and the email exists."
        end try

        return outputText
    end tell
    '''

    result = run_applescript(script)
    return result


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
    body_html: Optional[str] = None
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
        body_html: Optional HTML body for rich formatting (bold, headings, links, colors). When provided, the email is sent as HTML. The plain 'body' field is still required as fallback text.

    Returns:
        Confirmation message with details of the email
    """

    # Validate mode
    if mode not in ("send", "draft", "open"):
        return f"Error: Invalid mode '{mode}'. Use: send, draft, open"

    # Validate and resolve attachments early
    attachment_script = ''
    attachment_info = ''
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
            attachment_info += f'  {path}\n'

    # --- HTML path: use NSPasteboard clipboard injection ---
    if body_html:
        return _send_html_email(
            account=account,
            to=to,
            subject=subject,
            body_plain=body,
            body_html=body_html,
            cc=cc,
            bcc=bcc,
            attachments_script=attachment_script,
            mode=mode,
        )

    # --- Plain-text path: existing AppleScript approach ---
    safe_account = escape_applescript(account)
    escaped_subject = escape_applescript(subject)
    escaped_body = escape_applescript(body)

    # Build TO recipients (split comma-separated addresses)
    to_script = ''
    to_addresses = [addr.strip() for addr in to.split(',')]
    for addr in to_addresses:
        safe_addr = escape_applescript(addr)
        to_script += f'''
                make new to recipient at end of to recipients with properties {{address:"{safe_addr}"}}
        '''

    # Build CC recipients if provided
    cc_script = ''
    if cc:
        cc_addresses = [addr.strip() for addr in cc.split(',')]
        for addr in cc_addresses:
            safe_addr = escape_applescript(addr)
            cc_script += f'''
                make new cc recipient at end of cc recipients with properties {{address:"{safe_addr}"}}
            '''

    # Build BCC recipients if provided
    bcc_script = ''
    if bcc:
        bcc_addresses = [addr.strip() for addr in bcc.split(',')]
        for addr in bcc_addresses:
            safe_addr = escape_applescript(addr)
            bcc_script += f'''
                make new bcc recipient at end of bcc recipients with properties {{address:"{safe_addr}"}}
            '''

    safe_to = escape_applescript(to)
    safe_cc = escape_applescript(cc) if cc else ""
    safe_bcc = escape_applescript(bcc) if bcc else ""
    safe_attachment_info = escape_applescript(attachment_info) if attachment_info else ""

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
        send_command = "close window 1 saving yes"
        success_text = "✓ Email saved as draft!"

    script = f'''
    tell application "Mail"
        set outputText to "{header_text}" & return & return

        try
            set targetAccount to account "{safe_account}"

            -- Create new outgoing message
            set newMessage to make new outgoing message with properties {{subject:"{escaped_subject}", content:"{escaped_body}", visible:{visible}}}

            -- Set the sender account
            set emailAddrs to email addresses of targetAccount
            set senderAddress to item 1 of emailAddrs
            set sender of newMessage to senderAddress

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

            set outputText to outputText & "{success_text}" & return & return
            set outputText to outputText & "From: " & name of targetAccount & return
            set outputText to outputText & "To: {safe_to}" & return
    '''

    if cc:
        script += f'''
            set outputText to outputText & "CC: {safe_cc}" & return
    '''

    if bcc:
        script += f'''
            set outputText to outputText & "BCC: {safe_bcc}" & return
    '''

    if attachments:
        script += f'''
            set outputText to outputText & "Attachments:" & return & "{safe_attachment_info}" & return
    '''

    script += f'''
            set outputText to outputText & "Subject: {escaped_subject}" & return
            set outputText to outputText & "Body: " & "{escaped_body}" & return

        on error errMsg
            return "Error: " & errMsg & return & "Please check that the account name and email addresses are correct."
        end try

        return outputText
    end tell
    '''

    result = run_applescript(script)
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
    bcc: Optional[str] = None
) -> str:
    """
    Forward an email to one or more recipients.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        subject_keyword: Keyword to search for in email subjects
        to: Recipient email address(es), comma-separated for multiple
        message: Optional message to add before forwarded content
        mailbox: Mailbox to search in (default: "INBOX")
        cc: Optional CC recipients, comma-separated for multiple
        bcc: Optional BCC recipients, comma-separated for multiple

    Returns:
        Confirmation message with details of forwarded email
    """

    # Escape all user inputs for AppleScript
    safe_account = escape_applescript(account)
    safe_subject_keyword = escape_applescript(subject_keyword)
    safe_to = escape_applescript(to)
    safe_mailbox = escape_applescript(mailbox)
    escaped_message = escape_applescript(message) if message else ""

    # Build CC recipients if provided
    cc_script = ''
    if cc:
        cc_addresses = [addr.strip() for addr in cc.split(',')]
        for addr in cc_addresses:
            safe_addr = escape_applescript(addr)
            cc_script += f'''
            make new cc recipient at end of cc recipients of forwardMessage with properties {{address:"{safe_addr}"}}
            '''

    # Build BCC recipients if provided
    bcc_script = ''
    if bcc:
        bcc_addresses = [addr.strip() for addr in bcc.split(',')]
        for addr in bcc_addresses:
            safe_addr = escape_applescript(addr)
            bcc_script += f'''
            make new bcc recipient at end of bcc recipients of forwardMessage with properties {{address:"{safe_addr}"}}
            '''

    safe_cc = escape_applescript(cc) if cc else ""
    safe_bcc = escape_applescript(bcc) if bcc else ""

    # Build TO recipients (split comma-separated)
    to_script = ''
    to_addresses = [addr.strip() for addr in to.split(',')]
    for addr in to_addresses:
        safe_addr = escape_applescript(addr)
        to_script += f'''
                make new to recipient at end of to recipients of forwardMessage with properties {{address:"{safe_addr}"}}
        '''

    script = f'''
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

            set mailboxMessages to every message of targetMailbox
            set foundMessage to missing value

            -- Find the first matching message
            repeat with aMessage in mailboxMessages
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

                -- Create forward
                set forwardMessage to forward foundMessage with opening window

                -- Set sender account
                set emailAddrs to email addresses of targetAccount
                set senderAddress to item 1 of emailAddrs
                set sender of forwardMessage to senderAddress

                -- Add recipients
                {to_script}

                -- Add CC/BCC recipients
                {cc_script}
                {bcc_script}

                -- Add optional message
                if "{escaped_message}" is not "" then
                    set content of forwardMessage to "{escaped_message}" & return & return & content of forwardMessage
                end if

                -- Send the forward
                send forwardMessage

                set outputText to outputText & "✓ Email forwarded successfully!" & return & return
                set outputText to outputText & "Original email:" & return
                set outputText to outputText & "  Subject: " & messageSubject & return
                set outputText to outputText & "  From: " & messageSender & return
                set outputText to outputText & "  Date: " & (messageDate as string) & return & return
                set outputText to outputText & "Forwarded to: {safe_to}" & return
    '''

    if cc:
        script += f'''
                set outputText to outputText & "CC: {safe_cc}" & return
    '''

    if bcc:
        script += f'''
                set outputText to outputText & "BCC: {safe_bcc}" & return
    '''

    script += f'''
            else
                set outputText to outputText & "⚠ No email found matching: {safe_subject_keyword}" & return
            end if

        on error errMsg
            return "Error: " & errMsg
        end try

        return outputText
    end tell
    '''

    result = run_applescript(script)
    return result


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
    draft_subject: Optional[str] = None
) -> str:
    """
    Manage draft emails - list, create, send, open, or delete drafts.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        action: Action to perform: "list", "create", "send", "open", "delete". Use "open" to open a draft in a visible compose window for review before sending.
        subject: Email subject (required for create)
        to: Recipient email(s) for create (comma-separated)
        body: Email body (required for create)
        cc: Optional CC recipients for create
        bcc: Optional BCC recipients for create
        draft_subject: Subject keyword to find draft (required for send/open/delete)

    Returns:
        Formatted output based on action
    """

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

        escaped_subject = escape_applescript(subject)
        escaped_body = escape_applescript(body)
        safe_to = escape_applescript(to)

        # Build TO recipients (split comma-separated)
        to_script = ''
        to_addresses = [addr.strip() for addr in to.split(',')]
        for addr in to_addresses:
            safe_addr = escape_applescript(addr)
            to_script += f'''
                    make new to recipient at end of to recipients with properties {{address:"{safe_addr}"}}
            '''

        # Build CC recipients if provided
        cc_script = ''
        if cc:
            cc_addresses = [addr.strip() for addr in cc.split(',')]
            for addr in cc_addresses:
                safe_addr = escape_applescript(addr)
                cc_script += f'''
                    make new cc recipient at end of cc recipients with properties {{address:"{safe_addr}"}}
                '''

        # Build BCC recipients if provided
        bcc_script = ''
        if bcc:
            bcc_addresses = [addr.strip() for addr in bcc.split(',')]
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

                -- Set the sender account
                set emailAddrs to email addresses of targetAccount
                set senderAddress to item 1 of emailAddrs
                set sender of newDraft to senderAddress

                -- Add recipients
                tell newDraft
                    {to_script}
                    {cc_script}
                    {bcc_script}
                end tell

                -- Save to drafts (don't send)
                -- The draft is automatically saved to Drafts folder

                set outputText to outputText & "✓ Draft created successfully!" & return & return
                set outputText to outputText & "Subject: {escaped_subject}" & return
                set outputText to outputText & "To: {safe_to}" & return

            on error errMsg
                return "Error: " & errMsg
            end try

            return outputText
        end tell
        '''

    elif action == "send":
        if not draft_subject:
            return "Error: 'draft_subject' is required for sending drafts"

        safe_draft_subject = escape_applescript(draft_subject)

        script = f'''
        tell application "Mail"
            set outputText to "SENDING DRAFT" & return & return

            try
                set targetAccount to account "{safe_account}"
                set draftsMailbox to mailbox "Drafts" of targetAccount
                set draftMessages to every message of draftsMailbox
                set foundDraft to missing value

                -- Find the draft
                repeat with aDraft in draftMessages
                    try
                        set draftSubject to subject of aDraft

                        if draftSubject contains "{safe_draft_subject}" then
                            set foundDraft to aDraft
                            exit repeat
                        end if
                    end try
                end repeat

                if foundDraft is not missing value then
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
                set draftMessages to every message of draftsMailbox
                set foundDraft to missing value

                -- Find the draft
                repeat with aDraft in draftMessages
                    try
                        set draftSubject to subject of aDraft

                        if draftSubject contains "{safe_draft_subject}" then
                            set foundDraft to aDraft
                            exit repeat
                        end if
                    end try
                end repeat

                if foundDraft is not missing value then
                    set draftSubject to subject of foundDraft

                    -- Open the draft in a visible compose window
                    set draftWindow to open foundDraft
                    activate

                    set outputText to outputText & "✓ Draft opened in Mail for review!" & return
                    set outputText to outputText & "Subject: " & draftSubject & return
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
                set draftMessages to every message of draftsMailbox
                set foundDraft to missing value

                -- Find the draft
                repeat with aDraft in draftMessages
                    try
                        set draftSubject to subject of aDraft

                        if draftSubject contains "{safe_draft_subject}" then
                            set foundDraft to aDraft
                            exit repeat
                        end if
                    end try
                end repeat

                if foundDraft is not missing value then
                    set draftSubject to subject of foundDraft

                    -- Delete the draft
                    delete foundDraft

                    set outputText to outputText & "✓ Draft deleted successfully!" & return
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
        return f"Error: Invalid action '{action}'. Use: list, create, send, open, delete"

    result = run_applescript(script)
    return result

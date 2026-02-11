"""Composition tools: sending, replying, forwarding, and drafts."""

from typing import Optional

from apple_mail_mcp.server import mcp
from apple_mail_mcp.core import inject_preferences, escape_applescript, run_applescript, inbox_mailbox_script


@mcp.tool()
@inject_preferences
def reply_to_email(
    account: str,
    subject_keyword: str,
    reply_body: str,
    reply_to_all: bool = False,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
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
        attachments: Optional file paths to attach, comma-separated for multiple (e.g., "/path/to/file1.png,/path/to/file2.pdf")

    Returns:
        Confirmation message with details of the reply sent
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
        attachment_paths = [p.strip() for p in attachments.split(',')]
        for path in attachment_paths:
            safe_path = escape_applescript(path)
            attachment_script += f'''
                set theFile to "{safe_path}" as POSIX file
                tell replyMessage
                    make new attachment with properties {{file name:theFile}} at after the last paragraph
                end tell
                delay 1
            '''
            attachment_info += f'  📎 {path}\n'

    safe_cc = escape_applescript(cc) if cc else ""
    safe_bcc = escape_applescript(bcc) if bcc else ""
    safe_attachment_info = escape_applescript(attachment_info) if attachment_info else ""

    script = f'''
    tell application "Mail"
        set outputText to "SENDING REPLY" & return & return

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

                -- Ensure the reply is from the correct account
                set emailAddrs to email addresses of targetAccount
                set senderAddress to item 1 of emailAddrs
                set sender of replyMessage to senderAddress

                -- Set reply content
                set content of replyMessage to "{escaped_body}"

                -- Add CC/BCC recipients
                {cc_script}
                {bcc_script}

                -- Add attachments
                {attachment_script}

                -- Send the reply
                send replyMessage

                set outputText to outputText & "✓ Reply sent successfully!" & return & return
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
    attachments: Optional[str] = None
) -> str:
    """
    Compose and send a new email from a specific account.

    Args:
        account: Account name to send from (e.g., "Gmail", "Work", "Personal")
        to: Recipient email address(es), comma-separated for multiple
        subject: Email subject line
        body: Email body text
        cc: Optional CC recipients, comma-separated for multiple
        bcc: Optional BCC recipients, comma-separated for multiple
        attachments: Optional file paths to attach, comma-separated for multiple (e.g., "/path/to/file1.png,/path/to/file2.pdf")

    Returns:
        Confirmation message with details of the sent email
    """

    # Escape all user inputs for AppleScript
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

    # Build attachment script if provided
    attachment_script = ''
    attachment_info = ''
    if attachments:
        attachment_paths = [p.strip() for p in attachments.split(',')]
        for path in attachment_paths:
            safe_path = escape_applescript(path)
            attachment_script += f'''
                set theFile to POSIX file "{safe_path}"
                tell content of newMessage
                    make new attachment at after last paragraph with properties {{file name:theFile}}
                end tell
            '''
            attachment_info += f'  📎 {path}\n'

    safe_to = escape_applescript(to)
    safe_cc = escape_applescript(cc) if cc else ""
    safe_bcc = escape_applescript(bcc) if bcc else ""
    safe_attachment_info = escape_applescript(attachment_info) if attachment_info else ""

    script = f'''
    tell application "Mail"
        set outputText to "COMPOSING EMAIL" & return & return

        try
            set targetAccount to account "{safe_account}"

            -- Create new outgoing message
            set newMessage to make new outgoing message with properties {{subject:"{escaped_subject}", content:"{escaped_body}", visible:false}}

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
            {attachment_script}

            -- Send the message
            send newMessage

            set outputText to outputText & "✓ Email sent successfully!" & return & return
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
    Manage draft emails - list, create, send, or delete drafts.

    Args:
        account: Account name (e.g., "Gmail", "Work")
        action: Action to perform: "list", "create", "send", "delete"
        subject: Email subject (required for create)
        to: Recipient email(s) for create (comma-separated)
        body: Email body (required for create)
        cc: Optional CC recipients for create
        bcc: Optional BCC recipients for create
        draft_subject: Subject keyword to find draft (required for send/delete)

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
        return f"Error: Invalid action '{action}'. Use: list, create, send, delete"

    result = run_applescript(script)
    return result

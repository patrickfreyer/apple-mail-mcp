
    tell application "Mail"
        set outputText to ""

        try
            set targetAccount to account "Work"
            try
                set targetMailbox to mailbox "Archive" of targetAccount
            on error
                if "Archive" is "INBOX" then
                    set targetMailbox to mailbox "Inbox" of targetAccount
                else
                    error "Mailbox not found: Archive"
                end if
            end try
            set mailboxMessages to every message of targetMailbox
            set foundAttachment to false

            repeat with aMessage in mailboxMessages
                try
                    set messageSubject to subject of aMessage

                    -- Check if subject contains keyword
                    if messageSubject contains "Invoice" then
                        set msgAttachments to mail attachments of aMessage

                        repeat with anAttachment in msgAttachments
                            set attachmentFileName to name of anAttachment

                            if attachmentFileName contains "invoice.pdf" then
                                -- Save the attachment
                                save anAttachment in POSIX file "/private/tmp/invoice.pdf"

                                set outputText to "✓ Attachment saved successfully!" & return & return
                                set outputText to outputText & "Email: " & messageSubject & return
                                set outputText to outputText & "Attachment: " & attachmentFileName & return
                                set outputText to outputText & "Saved to: /private/tmp/invoice.pdf" & return

                                set foundAttachment to true
                                exit repeat
                            end if
                        end repeat

                        if foundAttachment then exit repeat
                    end if
                end try
            end repeat

            if not foundAttachment then
                set outputText to "⚠ Attachment not found" & return
                set outputText to outputText & "Email keyword: Invoice" & return
                set outputText to outputText & "Attachment name: invoice.pdf" & return
                set outputText to outputText & "Searched mailbox: Archive" & return
            end if

        on error errMsg
            return "Error: " & errMsg
        end try

        return outputText
    end tell
    
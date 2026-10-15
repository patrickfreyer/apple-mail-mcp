"""Smart inbox tools: follow-up tracking, actionable email detection, and sender analytics."""

from typing import Optional

from apple_mail_mcp.server import mcp
from apple_mail_mcp.core import (
    inject_preferences,
    escape_applescript,
    read_flag_index_script,
    run_applescript,
    inbox_mailbox_script,
    date_cutoff_script,
    LOWERCASE_HANDLER,
)
from apple_mail_mcp.constants import (
    NEWSLETTER_PLATFORM_PATTERNS,
    NEWSLETTER_KEYWORD_PATTERNS,
    THREAD_PREFIXES,
    FLAG_COLOR_NAMES,
)

# AppleScript list literal of color names indexed by flag index, e.g.
# {"red", "orange", ...} — item (flagIndex + 1) of this list is the name.
_FLAG_COLOR_NAME_LIST = ", ".join(
    f'"{FLAG_COLOR_NAMES[i]}"' for i in sorted(FLAG_COLOR_NAMES)
)

# --- Bounds for the get_awaiting_reply inbox cross-reference scan ----------
# Hard ceiling on how many inbox messages are walked. This bounds *cost*, not
# correctness, and it is sized to fit the run_applescript default timeout
# (120s): an in-window message costs ~3 Mail round-trips plus 2 `lowercase`
# shell calls, ~45-50ms, so a saturated scan is ~45-50s and leaves headroom for
# the sent scan that follows. Measured reference: a 9k-message Gmail inbox
# holds ~410 messages in a 14-day window (walking 1200 costs ~12s), so this is
# ~2.4x the real fortnightly volume. Truncation is disclosed in the output
# rather than silently narrowing the cross-reference, because a silently
# truncated cross-reference yields false "awaiting reply" entries.
#
# Note this caps the *inbox* side only. On days_back=0 the sent loop below has
# no date cutoff either and is bounded only by max_results; that is
# pre-existing and not addressed here.
INBOX_SCAN_CAP = 1000

# Mail returns messages newest-first, so the first message older than the
# cutoff normally means the rest are too. Exiting on the *first* old message
# would silently truncate the whole scan if that ordering ever failed to hold
# (yielding "everything is awaiting reply"), so require a short consecutive
# run before believing we are past the window.
INBOX_STALE_RUN_LIMIT = 10

# Fetch subject+sender for in-window inbox messages only; out-of-window ones
# cost a single `date received` round-trip and are skipped.
#
# inboxSubjects and inboxSenders are parallel lists indexed in lockstep by the
# matching loop, so every operation that can throw runs BEFORE either append.
# Appending the subject and then throwing on the sender would shift every
# later index by one, silently pairing each subject with the next message's
# sender — which loses genuine reply matches and reports answered mail as
# awaiting reply. (`lowercase` throws on `missing value`, so this is reachable
# whenever Mail returns a message with no sender.)
_INBOX_COLLECT_PROPS = """                        set msgSubject to subject of aMessage
                        set msgSender to sender of aMessage
                        set baseSubject to my stripPrefixes(msgSubject)
                        set lowerBase to my lowercase(baseSubject)
                        set lowerSender to my lowercase(msgSender)
                        set end of inboxSubjects to lowerBase
                        set end of inboxSenders to lowerSender"""


def _strip_subject_prefixes_script() -> str:
    """Return AppleScript handler to strip Re:/Fwd:/etc prefixes from a subject."""
    # Build a list of prefixes to strip
    prefix_checks = ""
    for prefix in THREAD_PREFIXES:
        escaped = escape_applescript(prefix)
        prefix_checks += f'''
                if baseSubj starts with "{escaped}" then
                    set baseSubj to text {len(prefix) + 1} thru -1 of baseSubj
                    -- trim leading space
                    repeat while baseSubj starts with " "
                        set baseSubj to text 2 thru -1 of baseSubj
                    end repeat
                    set didStrip to true
                end if
'''
    return f'''
    on stripPrefixes(subj)
        set baseSubj to subj
        set didStrip to true
        repeat while didStrip
            set didStrip to false
            {prefix_checks}
        end repeat
        return baseSubj
    end stripPrefixes
'''


def _newsletter_filter_condition(sender_var: str = "lowerSender") -> str:
    """Return AppleScript condition that evaluates to true if email is a newsletter."""
    platform_checks = " or ".join(
        f'{sender_var} contains "{escape_applescript(p)}"'
        for p in NEWSLETTER_PLATFORM_PATTERNS
    )
    keyword_checks = " or ".join(
        f'{sender_var} contains "{escape_applescript(k)}"'
        for k in NEWSLETTER_KEYWORD_PATTERNS
    )
    return f"({platform_checks} or {keyword_checks})"


@mcp.tool()
@inject_preferences
def get_awaiting_reply(
    account: str,
    days_back: int = 7,
    exclude_noreply: bool = True,
    max_results: int = 20,
) -> str:
    """Find sent emails that haven't received a reply yet.

    Scans the Sent mailbox for outgoing emails and cross-references with
    the Inbox to see if a reply (matching subject) was received from the
    same recipient. Useful for follow-up tracking.

    Args:
        account: Account name (e.g., "Gmail", "Work", "Personal")
        days_back: How many days back to check sent emails (default: 7, 0 = all time)
        exclude_noreply: Skip emails sent to noreply/no-reply addresses (default: True)
        max_results: Maximum results to return (default: 20)

    Returns:
        List of sent emails still awaiting a reply with subject, recipient, and date sent
    """
    escaped_account = escape_applescript(account)

    # Body of the inbox-collection loop. Unbounded, this loop fetched two
    # properties for EVERY inbox message (~9k on a long-lived Gmail account
    # => ~18k AppleEvent round-trips) and the tool timed out before returning
    # anything. `get_needs_response` below uses the same bounded-scan idiom.
    #
    # Bounding the inbox to the same window as the sent scan never hides a
    # genuine reply: a reply to something sent within `days_back` must itself
    # have arrived within `days_back`. It does change one case. The matcher
    # below places no ordering constraint between the sent message and the
    # inbox message it matches, and both sides are prefix-stripped, so a
    # thread OPENER older than the window used to satisfy the match as well —
    # a sent "Re: Budget" was suppressed by the correspondent's original
    # "Budget" from 30 days ago, even where they never actually replied.
    # Those sent messages are now reported. The set of QUALIFYING messages
    # only grows, never shrinks — but the returned list is still capped at
    # max_results, so a newly-unsuppressed message can push a previously
    # returned one past the cap. The new entries are true positives for the
    # question this tool asks: you sent last, so the reply is owed to you.
    if days_back > 0:
        inbox_collect_body = f"""
                    set msgDate to date received of aMessage
                    if msgDate < cutoffDate then
                        set staleRun to staleRun + 1
                        if staleRun > {INBOX_STALE_RUN_LIMIT} then exit repeat
                    else
                        set staleRun to 0
{_INBOX_COLLECT_PROPS}
                    end if"""
        stale_run_init = "\n            set staleRun to 0"
    else:
        # days_back=0 means "all time": no cutoff variable exists, so the
        # count cap is the only bound. (Indentation here is cosmetic.)
        inbox_collect_body = f"""
{_INBOX_COLLECT_PROPS}"""
        stale_run_init = ""

    noreply_filter = ""
    if exclude_noreply:
        noreply_filter = '''
                            set lowerRecip to my lowercase(recipAddr)
                            if lowerRecip contains "noreply" or lowerRecip contains "no-reply" or lowerRecip contains "do-not-reply" or lowerRecip contains "donotreply" then
                                set skipThis to true
                            end if
'''

    script = f'''
    tell application "Mail"
        set outputText to "EMAILS AWAITING REPLY" & return
        set outputText to outputText & "Account: {escaped_account} | Last {days_back} days" & return
        set outputText to outputText & "========================================" & return & return

        {date_cutoff_script(days_back, "cutoffDate")}

        try
            set targetAccount to account "{escaped_account}"

            -- Get Sent mailbox
            set sentMailbox to missing value
            try
                set sentMailbox to mailbox "Sent Messages" of targetAccount
            on error
                try
                    set sentMailbox to mailbox "Sent" of targetAccount
                on error
                    try
                        set sentMailbox to mailbox "Sent Items" of targetAccount
                    on error
                        return "Error: Could not find Sent mailbox for account {escaped_account}"
                    end try
                end try
            end try

            -- Get Inbox mailbox
            {inbox_mailbox_script("inboxMailbox", "targetAccount")}

            -- Collect subjects from inbox for matching (bounded scan)
            set inboxSubjects to {{}}
            set inboxSenders to {{}}
            set inboxMessages to every message of inboxMailbox
            set inboxScanned to 0{stale_run_init}
            set inboxCapHit to false

            repeat with aMessage in inboxMessages
                set inboxScanned to inboxScanned + 1
                if inboxScanned > {INBOX_SCAN_CAP} then
                    set inboxCapHit to true
                    exit repeat
                end if

                try
                    {inbox_collect_body}
                end try
            end repeat

            -- Now scan sent emails
            set sentMessages to every message of sentMailbox
            set resultCount to 0

            repeat with aMessage in sentMessages
                if resultCount >= {max_results} then exit repeat

                try
                    set messageDate to date sent of aMessage
                    {"if messageDate < cutoffDate then exit repeat" if days_back > 0 else ""}

                    set messageSubject to subject of aMessage
                    set messageRecipients to every to recipient of aMessage

                    if (count of messageRecipients) > 0 then
                        set recipAddr to address of item 1 of messageRecipients
                        set recipName to ""
                        try
                            set recipName to name of item 1 of messageRecipients
                        end try

                        set skipThis to false
                        {noreply_filter}

                        if not skipThis then
                            -- Strip prefixes from sent subject and check inbox
                            set baseSubject to my stripPrefixes(messageSubject)
                            set lowerBase to my lowercase(baseSubject)
                            set lowerRecipAddr to my lowercase(recipAddr)

                            -- Check if there is a reply in inbox from this recipient about this subject.
                            -- Sender is the more selective of the two tests, so it
                            -- gates the O(idx) indexing into inboxSubjects. Same
                            -- conjunction as before, just the cheaper order.
                            set foundReply to false
                            set idx to 1
                            repeat with inboxSender in inboxSenders
                                if inboxSender contains lowerRecipAddr then
                                    set inboxSubj to item idx of inboxSubjects
                                    if inboxSubj contains lowerBase or lowerBase contains inboxSubj then
                                        set foundReply to true
                                        exit repeat
                                    end if
                                end if
                                set idx to idx + 1
                            end repeat

                            if not foundReply then
                                set resultCount to resultCount + 1
                                set displayRecip to recipAddr
                                if recipName is not "" then
                                    set displayRecip to recipName & " <" & recipAddr & ">"
                                end if
                                set outputText to outputText & resultCount & ". " & messageSubject & return
                                set outputText to outputText & "   To: " & displayRecip & return
                                set outputText to outputText & "   Sent: " & (messageDate as string) & return & return
                            end if
                        end if
                    end if
                end try
            end repeat

            set outputText to outputText & "========================================" & return
            set outputText to outputText & "Found " & resultCount & " sent email(s) awaiting reply." & return
            if inboxCapHit then
                set outputText to outputText & "NOTE: inbox scan stopped at {INBOX_SCAN_CAP} messages; older inbox mail was not cross-referenced, so some entries above may already have replies." & return
            end if

        on error errMsg
            return "Error: " & errMsg
        end try

        return outputText
    end tell

    {LOWERCASE_HANDLER}
    {_strip_subject_prefixes_script()}
    '''

    return run_applescript(script)


@mcp.tool()
@inject_preferences
def get_needs_response(
    account: str,
    mailbox: str = "INBOX",
    days_back: int = 7,
    max_results: int = 20,
) -> str:
    """Identify unread emails that likely need a response from you.

    Filters out newsletters, automated emails, and noreply senders.
    Prioritises direct emails (To: you) with question marks as likely
    needing a reply.

    Args:
        account: Account name (e.g., "Gmail", "Work", "Personal")
        mailbox: Mailbox to scan (default: "INBOX")
        days_back: How many days back to look (default: 7)
        max_results: Maximum results to return (default: 20)

    Returns:
        Ranked list of emails likely needing a response, with priority hints
    """
    escaped_account = escape_applescript(account)
    escaped_mailbox = escape_applescript(mailbox)

    newsletter_condition = _newsletter_filter_condition("lowerSender")

    script = f'''
    tell application "Mail"
        set outputText to "EMAILS NEEDING RESPONSE" & return
        set outputText to outputText & "Account: {escaped_account} | Mailbox: {escaped_mailbox} | Last {days_back} days" & return
        set outputText to outputText & "========================================" & return & return

        {date_cutoff_script(days_back, "cutoffDate")}

        try
            set targetAccount to account "{escaped_account}"

            -- Get target mailbox
            try
                set targetMailbox to mailbox "{escaped_mailbox}" of targetAccount
            on error
                if "{escaped_mailbox}" is "INBOX" then
                    set targetMailbox to mailbox "Inbox" of targetAccount
                else
                    error "Mailbox not found: {escaped_mailbox}"
                end if
            end try

            -- Collect sent subjects for "already replied" detection
            set sentSubjects to {{}}
            set sentMailbox to missing value
            try
                set sentMailbox to mailbox "Sent Messages" of targetAccount
            on error
                try
                    set sentMailbox to mailbox "Sent" of targetAccount
                on error
                    try
                        set sentMailbox to mailbox "Sent Items" of targetAccount
                    end try
                end try
            end try

            if sentMailbox is not missing value then
                set sentMessages to every message of sentMailbox
                set sentIdx to 0
                repeat with aMessage in sentMessages
                    set sentIdx to sentIdx + 1
                    if sentIdx > 200 then exit repeat
                    try
                        set sentSubj to subject of aMessage
                        set baseSent to my stripPrefixes(sentSubj)
                        set end of sentSubjects to my lowercase(baseSent)
                    end try
                end repeat
            end if

            -- Scan target mailbox
            set mailboxMessages to every message of targetMailbox
            set highPriority to {{}}
            set normalPriority to {{}}
            set totalChecked to 0
            set flagColorNames to {{{_FLAG_COLOR_NAME_LIST}}}

            repeat with aMessage in mailboxMessages
                if (count of highPriority) + (count of normalPriority) >= {max_results} then exit repeat

                try
                    set messageDate to date received of aMessage
                    {"if messageDate < cutoffDate then exit repeat" if days_back > 0 else ""}

                    -- Only look at unread emails
                    if not (read status of aMessage) then
                        set messageSender to sender of aMessage
                        set messageSubject to subject of aMessage
                        set lowerSender to my lowercase(messageSender)

                        -- Filter out newsletters and automated senders
                        set isNewsletter to {newsletter_condition}
                        set isAutomated to (lowerSender contains "noreply" or lowerSender contains "no-reply" or lowerSender contains "donotreply" or lowerSender contains "do-not-reply" or lowerSender contains "notifications@" or lowerSender contains "mailer-daemon" or lowerSender contains "postmaster@")

                        if not isNewsletter and not isAutomated then
                            -- Check if user already replied
                            set baseSubject to my stripPrefixes(messageSubject)
                            set lowerBase to my lowercase(baseSubject)
                            set alreadyReplied to false
                            repeat with sentSubj in sentSubjects
                                if sentSubj contains lowerBase or lowerBase contains sentSubj then
                                    set alreadyReplied to true
                                    exit repeat
                                end if
                            end repeat

                            if not alreadyReplied then
                                -- Determine priority
                                set hasQuestion to (messageSubject contains "?")
                                try
                                    set msgContent to content of aMessage
                                    if length of msgContent > 500 then
                                        set msgContent to text 1 thru 500 of msgContent
                                    end if
                                    if msgContent contains "?" then set hasQuestion to true
                                end try

                                {read_flag_index_script("flagIndex")}
                                set isFlagged to (flagIndex is not -1)
                                set flagLabel to "flagged"
                                if flagIndex >= 0 and flagIndex < 7 then
                                    set flagLabel to "flagged " & item (flagIndex + 1) of flagColorNames
                                end if

                                set emailEntry to messageSubject & "|||" & messageSender & "|||" & (messageDate as string) & "|||"
                                if hasQuestion or isFlagged then
                                    if hasQuestion and isFlagged then
                                        set emailEntry to emailEntry & "HIGH (" & flagLabel & " + question)"
                                    else if isFlagged then
                                        set emailEntry to emailEntry & "HIGH (" & flagLabel & ")"
                                    else
                                        set emailEntry to emailEntry & "MEDIUM (contains question)"
                                    end if
                                    set end of highPriority to emailEntry
                                else
                                    set emailEntry to emailEntry & "NORMAL"
                                    set end of normalPriority to emailEntry
                                end if
                            end if
                        end if
                    end if
                end try
            end repeat

            -- Format output: high priority first, then normal
            set resultCount to 0
            repeat with entry in highPriority
                set resultCount to resultCount + 1
                set AppleScript's text item delimiters to "|||"
                set parts to text items of entry
                set AppleScript's text item delimiters to ""
                set outputText to outputText & resultCount & ". [" & item 4 of parts & "] " & item 1 of parts & return
                set outputText to outputText & "   From: " & item 2 of parts & return
                set outputText to outputText & "   Date: " & item 3 of parts & return & return
            end repeat

            repeat with entry in normalPriority
                set resultCount to resultCount + 1
                set AppleScript's text item delimiters to "|||"
                set parts to text items of entry
                set AppleScript's text item delimiters to ""
                set outputText to outputText & resultCount & ". [" & item 4 of parts & "] " & item 1 of parts & return
                set outputText to outputText & "   From: " & item 2 of parts & return
                set outputText to outputText & "   Date: " & item 3 of parts & return & return
            end repeat

            set outputText to outputText & "========================================" & return
            set outputText to outputText & "Found " & resultCount & " email(s) needing response." & return

        on error errMsg
            return "Error: " & errMsg
        end try

        return outputText
    end tell

    {LOWERCASE_HANDLER}
    {_strip_subject_prefixes_script()}
    '''

    return run_applescript(script)


@mcp.tool()
@inject_preferences
def get_top_senders(
    account: str,
    mailbox: str = "INBOX",
    days_back: int = 30,
    top_n: int = 10,
    group_by_domain: bool = False,
) -> str:
    """Analyse a mailbox to find the most frequent senders.

    Useful for identifying key contacts, high-volume senders to filter,
    or newsletter sources to unsubscribe from.

    Args:
        account: Account name (e.g., "Gmail", "Work", "Personal")
        mailbox: Mailbox to analyse (default: "INBOX")
        days_back: How many days back to look (default: 30, 0 = all time)
        top_n: Number of top senders to return (default: 10)
        group_by_domain: Group results by domain instead of individual sender (default: False)

    Returns:
        Ranked list of senders (or domains) with email counts
    """
    escaped_account = escape_applescript(account)
    escaped_mailbox = escape_applescript(mailbox)

    date_cutoff = date_cutoff_script(days_back, "cutoffDate")
    date_check = "if messageDate < cutoffDate then exit repeat" if days_back > 0 else ""

    # Build the extraction key: either full sender or domain
    if group_by_domain:
        # Extract domain from email address
        extract_key = '''
                            -- Extract domain from sender address
                            set senderKey to ""
                            set atPos to 0
                            set senderLen to length of messageSender
                            repeat with i from 1 to senderLen
                                if character i of messageSender is "@" then
                                    set atPos to i
                                end if
                            end repeat
                            if atPos > 0 then
                                -- Find the closing > if present
                                set endPos to senderLen
                                repeat with i from atPos to senderLen
                                    if character i of messageSender is ">" then
                                        set endPos to i - 1
                                        exit repeat
                                    end if
                                end repeat
                                set senderKey to text (atPos + 1) thru endPos of messageSender
                            else
                                set senderKey to messageSender
                            end if
'''
        title_label = "TOP SENDER DOMAINS"
    else:
        extract_key = '''
                            set senderKey to messageSender
'''
        title_label = "TOP SENDERS"

    script = f'''
    tell application "Mail"
        set outputText to "{title_label}" & return
        set outputText to outputText & "Account: {escaped_account} | Mailbox: {escaped_mailbox} | Last {days_back} days" & return
        set outputText to outputText & "========================================" & return & return

        {date_cutoff}

        try
            set targetAccount to account "{escaped_account}"

            -- Get target mailbox
            try
                set targetMailbox to mailbox "{escaped_mailbox}" of targetAccount
            on error
                if "{escaped_mailbox}" is "INBOX" then
                    set targetMailbox to mailbox "Inbox" of targetAccount
                else
                    error "Mailbox not found: {escaped_mailbox}"
                end if
            end try

            set mailboxMessages to every message of targetMailbox
            set senderKeys to {{}}
            set senderCounts to {{}}
            set totalAnalysed to 0

            repeat with aMessage in mailboxMessages
                try
                    set messageDate to date received of aMessage
                    {date_check}

                    set messageSender to sender of aMessage
                    set totalAnalysed to totalAnalysed + 1

                    {extract_key}

                    -- Update count
                    set foundSender to false
                    set idx to 1
                    repeat with existingKey in senderKeys
                        if existingKey as string is senderKey then
                            set item idx of senderCounts to (item idx of senderCounts) + 1
                            set foundSender to true
                            exit repeat
                        end if
                        set idx to idx + 1
                    end repeat
                    if not foundSender then
                        set end of senderKeys to senderKey
                        set end of senderCounts to 1
                    end if
                end try
            end repeat

            -- Sort by count (simple selection sort, we only need top N)
            set topN to {top_n}
            repeat with i from 1 to (count of senderCounts)
                if i > topN then exit repeat
                -- Find max from i to end
                set maxIdx to i
                set maxVal to item i of senderCounts
                repeat with j from (i + 1) to (count of senderCounts)
                    if item j of senderCounts > maxVal then
                        set maxIdx to j
                        set maxVal to item j of senderCounts
                    end if
                end repeat
                -- Swap
                if maxIdx is not i then
                    set tmpCount to item i of senderCounts
                    set item i of senderCounts to item maxIdx of senderCounts
                    set item maxIdx of senderCounts to tmpCount
                    set tmpKey to item i of senderKeys as string
                    set item i of senderKeys to (item maxIdx of senderKeys as string)
                    set item maxIdx of senderKeys to tmpKey
                end if
            end repeat

            -- Format output
            set displayCount to topN
            if (count of senderKeys) < displayCount then
                set displayCount to (count of senderKeys)
            end if

            repeat with i from 1 to displayCount
                set senderKey to item i of senderKeys
                set sCount to item i of senderCounts
                set pctText to ""
                if totalAnalysed > 0 then
                    set pct to round ((sCount / totalAnalysed) * 100)
                    set pctText to " (" & pct & "%)"
                end if
                set outputText to outputText & i & ". " & senderKey & ": " & sCount & " emails" & pctText & return
            end repeat

            set outputText to outputText & return & "========================================" & return
            set outputText to outputText & "Total emails analysed: " & totalAnalysed & return
            set outputText to outputText & "Unique senders: " & (count of senderKeys) & return

        on error errMsg
            return "Error: " & errMsg
        end try

        return outputText
    end tell
    '''

    return run_applescript(script)

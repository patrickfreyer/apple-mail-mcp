"""Shared constants for Apple Mail MCP tools."""

# Newsletter detection patterns (sender-based)
NEWSLETTER_PLATFORM_PATTERNS = [
    "substack.com", "beehiiv.com", "mailchimp", "sendgrid",
    "convertkit", "buttondown", "ghost.io", "revue.co", "mailgun",
]

NEWSLETTER_KEYWORD_PATTERNS = [
    "newsletter", "digest", "weekly", "daily",
    "bulletin", "briefing", "news@", "updates@",
]

# Folders to skip during broad searches.
# Includes localized variants so non-English Mail.app accounts (Exchange,
# Outlook, Gmail in non-English locales) skip system folders correctly.
SKIP_FOLDERS = [
    # English / IMAP standards
    "Trash", "Junk", "Junk Email", "Deleted Items",
    "Sent", "Sent Items", "Sent Messages", "Drafts",
    "Spam", "Deleted Messages",
    # French (Exchange/Outlook + Gmail FR)
    "Corbeille", "Courrier indésirable", "Indésirables",
    "Éléments supprimés", "Éléments envoyés", "Messages envoyés",
    "Brouillons", "Boîte d'envoi",
    # German
    "Papierkorb", "Gesendet", "Entwürfe", "Werbung",
    # Spanish
    "Papelera", "Enviados", "Borradores", "Correo no deseado",
]

# Thread subject prefixes to strip when matching threads
THREAD_PREFIXES = ["Re:", "Fwd:", "FW:", "RE:", "Fw:"]

# Human-friendly time range mappings (name -> days)
TIME_RANGES = {
    "today": 1,
    "yesterday": 2,
    "week": 7,
    "month": 30,
    "all": 0,
}

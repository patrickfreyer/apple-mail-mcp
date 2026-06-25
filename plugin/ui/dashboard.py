"""
Apple Mail MCP Dashboard UI Module

Provides functions to create UI resources for the inbox dashboard.
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Any

from mcp_ui_server import create_ui_resource


def _json_for_script(obj: Any) -> str:
    """Serialize ``obj`` to JSON safe to embed inside an HTML ``<script>`` block.

    json.dumps does not escape '<', '>', '&' or the JS line separators
    U+2028/U+2029. Inside a <script> element, a value containing "</script>"
    (e.g. an attacker-controlled email subject or sender) would close the
    script element early and inject arbitrary HTML -- a stored XSS. Escaping
    these as \\uXXXX keeps the output valid JSON that parses to the identical
    value, but it can no longer break out of the script context.
    """
    return (
        json.dumps(obj, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def create_inbox_dashboard_ui(
    accounts_data: Dict[str, int],
    recent_emails: List[Dict[str, Any]]
) -> Any:
    """
    Create a UI resource for the Apple Mail inbox dashboard.

    Args:
        accounts_data: Dictionary mapping account names to unread email counts.
                      Example: {"Gmail": 5, "Work": 12, "Personal": 3}
        recent_emails: List of recent email dictionaries with keys:
                      - subject: Email subject line
                      - sender: Sender name/email
                      - date: Date string
                      - is_read: Boolean indicating read status
                      - account: (optional) Account name
                      - preview: (optional) Email preview text

    Returns:
        UIResource with uri "ui://apple-mail/inbox-dashboard"
    """
    # Get the template file path
    template_path = Path(__file__).parent / "templates" / "dashboard.html"

    # Read the HTML template
    with open(template_path, "r", encoding="utf-8") as f:
        template_content = f.read()

    # Serialize the data for injection into the template
    # Escaped for the HTML <script> context (see _json_for_script): email
    # subjects/senders are attacker-controlled and could otherwise break out
    # via "</script>" and inject HTML (stored XSS).
    accounts_json = _json_for_script(accounts_data)
    emails_json = _json_for_script(recent_emails)

    # Inject data into the template
    html_content = template_content.replace(
        "/* ACCOUNTS_DATA_PLACEHOLDER */",
        f"const accountsData = {accounts_json};"
    ).replace(
        "/* EMAILS_DATA_PLACEHOLDER */",
        f"const recentEmails = {emails_json};"
    )

    # Create and return the UI resource
    return create_ui_resource({
        "uri": "ui://apple-mail/inbox-dashboard",
        "content": {
            "type": "rawHtml",
            "htmlString": html_content
        },
        "encoding": "text"
    })

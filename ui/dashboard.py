"""
Apple Mail MCP Dashboard UI Module

Provides functions to create UI resources for the inbox dashboard.
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Any

from mcp_ui_server import create_ui_resource


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
    accounts_json = json.dumps(accounts_data, ensure_ascii=False)
    emails_json = json.dumps(recent_emails, ensure_ascii=False)

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

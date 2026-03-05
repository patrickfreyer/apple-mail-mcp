"""IMAP-based inbox sorting tools (fast direct IMAP, ideal for Proton Bridge)."""

import json
import os
from collections import defaultdict
from typing import Optional

from apple_mail_mcp.server import mcp
from apple_mail_mcp.core import inject_preferences
from apple_mail_mcp import imap as imap_backend


# Default rules config path
DEFAULT_RULES_PATH = os.path.expanduser(
    "~/.config/apple-mail-mcp/sort_rules.json"
)


def _load_rules(rules_path: Optional[str] = None) -> list[tuple[str, str]]:
    """Load sorting rules from a JSON config file.

    Expected format:
    {
      "rules": [
        {"match": "@amazon.de", "folder": "Shopping/Amazon"},
        {"match": "@github.com", "folder": "IT/Github"},
        {"match": "@facebook.com", "folder": "Trash"}
      ]
    }
    """
    path = rules_path or DEFAULT_RULES_PATH
    if not os.path.exists(path):
        return []

    with open(path) as f:
        data = json.load(f)

    return [(r["match"], r["folder"]) for r in data.get("rules", [])]


def _match_rule(from_header: str, rules: list[tuple[str, str]]) -> Optional[str]:
    """Return the destination folder for a From header, or None."""
    for pattern, destination in rules:
        if pattern.lower() in from_header:
            return destination
    return None


@mcp.tool()
@inject_preferences
def sort_inbox(
    dry_run: bool = True,
    max_emails: int = 0,
    rules_path: Optional[str] = None,
    create_folders: bool = True,
) -> str:
    """
    Sort inbox emails into folders by sender using IMAP (fast, for Proton Bridge).

    Reads sorting rules from ~/.config/apple-mail-mcp/sort_rules.json.
    Each rule maps a sender pattern to a destination folder.

    Requires env vars: PROTON_BRIDGE_USER, PROTON_BRIDGE_PASSWORD

    Args:
        dry_run: If True, only show what would happen without moving (default: True)
        max_emails: Maximum emails to process (0 = all)
        rules_path: Optional custom path to sort_rules.json
        create_folders: Auto-create destination folders that don't exist (default: True)

    Returns:
        Summary of emails scanned, matched, and moved
    """
    config = imap_backend.get_imap_config()
    if not config["user"] or not config["password"]:
        return (
            "Error: PROTON_BRIDGE_USER and PROTON_BRIDGE_PASSWORD environment "
            "variables must be set.\n\n"
            "Find your Bridge IMAP password in the Proton Bridge app: "
            "click your account → IMAP/SMTP settings."
        )

    rules = _load_rules(rules_path)
    if not rules:
        path = rules_path or DEFAULT_RULES_PATH
        return (
            f"No sorting rules found at {path}\n\n"
            "Create it with format:\n"
            '{"rules": [{"match": "@amazon.de", "folder": "Shopping/Amazon"}, ...]}'
        )

    lines = []
    lines.append("INBOX SORT" + (" (DRY RUN)" if dry_run else ""))
    lines.append("")

    try:
        conn = imap_backend.connect(
            config["host"], config["port"], config["user"], config["password"]
        )
    except Exception as e:
        return f"Error connecting to IMAP: {e}"

    try:
        # Create missing folders
        if create_folders:
            existing = imap_backend.list_folders(conn)
            destinations = {dest for _, dest in rules if dest != "Trash"}
            missing = destinations - existing
            if missing:
                lines.append("── Folder creation ──")
                for folder in sorted(missing):
                    if dry_run:
                        lines.append(f"  + would create: {folder}")
                    else:
                        ok = imap_backend.create_folder(conn, folder)
                        lines.append(
                            f"  {'✓ created' if ok else '✗ failed'}: {folder}"
                        )
                lines.append("")

        # Scan inbox
        conn.select("INBOX", readonly=dry_run)
        headers = imap_backend.batch_fetch_from_headers(conn)
        total = len(headers)

        if max_emails and max_emails < total:
            headers = headers[:max_emails]

        lines.append(f"── Scanned {total} messages in INBOX ──")
        if max_emails:
            lines.append(f"   (processing first {max_emails})")
        lines.append("")

        # Match rules
        plan: dict[str, list[bytes]] = defaultdict(list)
        unmatched = 0

        for uid, from_header in headers:
            dest = _match_rule(from_header, rules)
            if dest:
                plan[dest].append(uid)
            else:
                unmatched += 1

        # Summary
        lines.append("── Plan ──")
        trash_count = 0
        move_count = 0
        for dest in sorted(plan.keys()):
            count = len(plan[dest])
            if dest == "Trash":
                trash_count = count
                lines.append(f"  {count:>5}  🗑 trash")
            else:
                move_count += count
                lines.append(f"  {count:>5}  → {dest}")

        lines.append("")
        lines.append(f"  {move_count:>5}  to move")
        lines.append(f"  {trash_count:>5}  to trash")
        lines.append(f"  {unmatched:>5}  no match (stay in INBOX)")

        if dry_run:
            lines.append("")
            lines.append("Dry run complete. Set dry_run=False to execute.")
            return "\n".join(lines)

        # Execute moves
        lines.append("")
        lines.append("── Moving ──")

        # Re-select as read-write for moves
        conn.select("INBOX", readonly=False)

        for dest in sorted(plan.keys()):
            dest_uids = plan[dest]
            succeeded = 0
            failed = 0
            for uid in dest_uids:
                if imap_backend.move_message(conn, uid, dest):
                    succeeded += 1
                else:
                    failed += 1
            label = "🗑 trash" if dest == "Trash" else f"→ {dest}"
            status = f"✓ {succeeded}"
            if failed:
                status += f"  ✗ {failed} failed"
            lines.append(f"  {label:40} {status}")

        conn.expunge()

        lines.append("")
        lines.append(f"✓ Done! Moved {move_count} + trashed {trash_count} emails.")

    finally:
        try:
            conn.logout()
        except Exception:
            pass

    return "\n".join(lines)


@mcp.tool()
@inject_preferences
def imap_bulk_move(
    from_mailbox: str,
    to_mailbox: str,
    sender: Optional[str] = None,
    max_moves: int = 100,
    dry_run: bool = True,
) -> str:
    """
    Move emails between IMAP folders directly (fast, for Proton Bridge).

    Much faster than AppleScript for large mailboxes. Optionally filter by sender.

    Requires env vars: PROTON_BRIDGE_USER, PROTON_BRIDGE_PASSWORD

    Args:
        from_mailbox: Source mailbox (e.g., "INBOX", "Rechnungen", "IT/Netflix")
        to_mailbox: Destination mailbox (e.g., "Finanzen/Rechnungen")
        sender: Optional sender pattern to filter by (case-insensitive substring)
        max_moves: Maximum emails to move (safety limit, default: 100)
        dry_run: If True, only count matches without moving (default: True)

    Returns:
        Summary of moved emails
    """
    config = imap_backend.get_imap_config()
    if not config["user"] or not config["password"]:
        return (
            "Error: PROTON_BRIDGE_USER and PROTON_BRIDGE_PASSWORD "
            "environment variables must be set."
        )

    try:
        conn = imap_backend.connect(
            config["host"], config["port"], config["user"], config["password"]
        )
    except Exception as e:
        return f"Error connecting to IMAP: {e}"

    lines = []
    lines.append(f"IMAP BULK MOVE{' (DRY RUN)' if dry_run else ''}")
    lines.append(f"{from_mailbox} → {to_mailbox}")

    try:
        # Ensure destination exists
        existing = imap_backend.list_folders(conn)
        if to_mailbox not in existing and to_mailbox != "Trash":
            if dry_run:
                lines.append(f"Note: folder '{to_mailbox}' does not exist (would create)")
            else:
                imap_backend.create_folder(conn, to_mailbox)
                lines.append(f"Created folder: {to_mailbox}")

        conn.select(f'"{from_mailbox}"', readonly=dry_run)
        headers = imap_backend.batch_fetch_from_headers(conn)
        lines.append(f"Found {len(headers)} message(s) in {from_mailbox}")

        # Filter by sender if specified
        if sender:
            sender_lower = sender.lower()
            matched = [(uid, fh) for uid, fh in headers if sender_lower in fh]
            lines.append(f"Matched {len(matched)} by sender '{sender}'")
        else:
            matched = headers

        to_move = matched[:max_moves] if max_moves else matched

        if dry_run:
            lines.append(f"\nWould move {len(to_move)} email(s).")
            lines.append("Set dry_run=False to execute.")
            return "\n".join(lines)

        # Re-select as read-write
        conn.select(f'"{from_mailbox}"', readonly=False)

        moved = 0
        failed = 0
        for uid, _ in to_move:
            if imap_backend.move_message(conn, uid, to_mailbox):
                moved += 1
            else:
                failed += 1

        conn.expunge()

        lines.append(f"\n✓ Moved {moved} email(s)")
        if failed:
            lines.append(f"✗ {failed} failed")

    finally:
        try:
            conn.logout()
        except Exception:
            pass

    return "\n".join(lines)

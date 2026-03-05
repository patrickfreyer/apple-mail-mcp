"""IMAP backend for direct mailbox operations (faster than AppleScript for IMAP accounts)."""

import email
import imaplib
import os
import ssl
import socket
from email.header import decode_header, make_header
from typing import Optional


# Default connection settings (overridable via env vars)
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 1143
SOCKET_TIMEOUT = 30  # seconds


def get_imap_config() -> dict:
    """Read IMAP connection config from environment variables."""
    return {
        "host": os.environ.get("PROTON_BRIDGE_HOST", DEFAULT_HOST),
        "port": int(os.environ.get("PROTON_BRIDGE_PORT", DEFAULT_PORT)),
        "user": os.environ.get("PROTON_BRIDGE_USER", ""),
        "password": os.environ.get("PROTON_BRIDGE_PASSWORD", ""),
    }


def connect(host: str, port: int, user: str, password: str) -> imaplib.IMAP4:
    """Connect and authenticate to an IMAP server.

    Tries SSL first (Proton Bridge v3 default), then STARTTLS, then plain.
    """
    socket.setdefaulttimeout(SOCKET_TIMEOUT)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # Bridge uses a self-signed cert

    imap = None
    # 1. SSL
    try:
        imap = imaplib.IMAP4_SSL(host, port, ssl_context=ctx)
    except Exception:
        pass

    # 2. STARTTLS
    if imap is None:
        try:
            imap = imaplib.IMAP4(host, port)
            imap.starttls(ssl_context=ctx)
        except Exception:
            imap = None

    # 3. Plain (localhost only)
    if imap is None:
        imap = imaplib.IMAP4(host, port)

    imap.login(user, password)
    return imap


def list_folders(imap: imaplib.IMAP4) -> set[str]:
    """Return a set of existing folder names."""
    _, folders = imap.list()
    existing = set()
    for f in folders:
        if f:
            decoded = f.decode() if isinstance(f, bytes) else f
            parts = decoded.split('"')
            if len(parts) >= 2:
                existing.add(parts[-2].strip())
    return existing


def batch_fetch_from_headers(imap: imaplib.IMAP4) -> list[tuple[bytes, str]]:
    """Fetch From headers for ALL messages in the currently selected mailbox.

    Returns list of (uid, from_header) tuples.
    Much faster than fetching one-by-one (~50x for large mailboxes).
    """
    _, data = imap.uid("search", None, "ALL")
    if not data or not data[0]:
        return []

    uids = data[0].split()
    if not uids:
        return []

    # Batch fetch all From headers in one IMAP call
    uid_range = b",".join(uids)
    _, fetch_data = imap.uid("fetch", uid_range, "(BODY.PEEK[HEADER.FIELDS (FROM)])")

    results = []
    # fetch_data comes as pairs: (b'UID FLAGS ...', b'From: ...\r\n'), b')', ...
    i = 0
    while i < len(fetch_data):
        item = fetch_data[i]
        if isinstance(item, tuple) and len(item) == 2:
            # Parse UID from the response line
            meta = item[0].decode() if isinstance(item[0], bytes) else item[0]
            raw_header = item[1]

            uid = _extract_uid(meta)
            if uid is not None:
                msg = email.message_from_bytes(raw_header)
                from_val = msg.get("From", "")
                try:
                    from_decoded = str(make_header(decode_header(from_val))).lower()
                except Exception:
                    from_decoded = from_val.lower()
                results.append((uid, from_decoded))
        i += 1

    return results


def _extract_uid(meta_line: str) -> Optional[bytes]:
    """Extract UID from an IMAP FETCH response line like '1 (UID 123 ...'."""
    # Look for UID followed by a number
    upper = meta_line.upper()
    idx = upper.find("UID ")
    if idx == -1:
        return None
    rest = meta_line[idx + 4:].strip()
    uid_str = rest.split()[0].rstrip(")")
    return uid_str.encode()


def move_message(imap: imaplib.IMAP4, uid: bytes, destination: str) -> bool:
    """Move a single UID to destination folder.

    Uses MOVE (RFC 6851) if available, falls back to COPY+DELETE.
    """
    dest_quoted = f'"{destination}"'
    typ, _ = imap.uid("move", uid, dest_quoted)
    if typ == "OK":
        return True
    # Fallback
    typ, _ = imap.uid("copy", uid, dest_quoted)
    if typ != "OK":
        return False
    imap.uid("store", uid, "+FLAGS", r"(\Deleted)")
    return True


def create_folder(imap: imaplib.IMAP4, name: str) -> bool:
    """Create an IMAP folder. Returns True on success."""
    typ, _ = imap.create(f'"{name}"')
    return typ == "OK"

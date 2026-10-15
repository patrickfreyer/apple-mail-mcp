"""Shared filesystem path guard for tools that write or attach files.

Attachment content is attacker-controlled (anyone can email the user a file)
and tool arguments can be steered by prompt injection, so every tool that
touches the filesystem goes through one of the two validators here instead of
keeping its own list (#19, #103).

Writes use an allowlist: ``~/Downloads``, ``~/Desktop``, ``~/Documents``, the
tool's own cache dir, the system temp dir, plus any directories the user opts
into via the ``APPLE_MAIL_MCP_WRITE_DIRS`` environment variable
(``os.pathsep``-separated). Anything else, including dotfiles and dot-dirs
inside an allowed root (``.git/hooks``, ``.envrc``, ...), is rejected.

Reads (files to attach to outgoing mail) stay broad, since users attach files
from anywhere in their home folder, but hidden entries and ``~/Library``
internals (Keychains, browser profiles, app data) are rejected. iCloud Drive
and ``~/Library/CloudStorage`` remain readable.

Paths are resolved with ``realpath`` (so ``..`` and symlinks cannot escape)
and compared case-insensitively, because APFS is case-insensitive by default.
"""

import os
import tempfile
from typing import List, Optional, Tuple

EXTRA_WRITE_DIRS_ENV = "APPLE_MAIL_MCP_WRITE_DIRS"

# Relative to $HOME.
_SAFE_WRITE_SUBDIRS = (
    ("Downloads",),
    ("Desktop",),
    ("Documents",),
    ("Library", "Caches", "apple-mail-mcp"),
)

# Relative to $HOME; the only parts of ~/Library that attachments may come from.
_READABLE_LIBRARY_SUBDIRS = (
    ("Library", "Mobile Documents"),
    ("Library", "CloudStorage"),
)


def _home() -> str:
    return os.path.realpath(os.path.expanduser("~"))


def _resolve(path: str) -> str:
    return os.path.realpath(os.path.expanduser(path.strip()))


def _temp_roots() -> List[str]:
    """System temp dirs (``/tmp`` and ``$TMPDIR``), resolved."""
    roots = {os.path.realpath(tempfile.gettempdir())}
    if os.path.isdir("/tmp"):
        roots.add(os.path.realpath("/tmp"))
    return sorted(roots)


def _relative_parts(path: str, root: str) -> Optional[List[str]]:
    """Components of ``path`` below ``root`` (case-insensitive), or None if
    ``path`` is not ``root`` or inside it. Returned parts keep their case."""
    path_parts = [p for p in path.split(os.sep) if p]
    root_parts = [p for p in root.split(os.sep) if p]
    if len(path_parts) < len(root_parts):
        return None
    for a, b in zip(path_parts, root_parts):
        if a.casefold() != b.casefold():
            return None
    return path_parts[len(root_parts):]


def _has_hidden_part(parts: List[str]) -> bool:
    return any(part.startswith(".") for part in parts)


def allowed_write_roots() -> List[str]:
    """Directories file-writing tools may write into, resolved."""
    home = _home()
    roots = [os.path.realpath(os.path.join(home, *sub)) for sub in _SAFE_WRITE_SUBDIRS]
    roots.extend(_temp_roots())
    for extra in os.environ.get(EXTRA_WRITE_DIRS_ENV, "").split(os.pathsep):
        if extra.strip():
            roots.append(_resolve(extra))
    return roots


def validate_write_path(path: str) -> Tuple[Optional[str], Optional[str]]:
    """Validate a destination for a file write.

    Returns ``(resolved_path, None)`` when allowed, else ``(None, error)``.
    """
    if not path or not path.strip():
        return None, "Error: A destination path is required."

    resolved = _resolve(path)
    roots = allowed_write_roots()
    for root in roots:
        rel = _relative_parts(resolved, root)
        if rel is None:
            continue
        if _has_hidden_part(rel):
            return None, (
                "Error: Cannot write to hidden files or directories "
                f"(dotfiles such as .git or .envrc). Got: {resolved}"
            )
        return resolved, None

    home = _home()
    shown = ", ".join(
        "~" + r[len(home):] if _relative_parts(r, home) is not None else r
        for r in roots
    )
    return None, (
        f"Error: Destination is outside the allowed folders ({shown}). Got: {resolved}. "
        f"To allow another folder, set {EXTRA_WRITE_DIRS_ENV} in the server's environment."
    )


def validate_read_path(path: str) -> Tuple[Optional[str], Optional[str]]:
    """Validate a file to be attached to an outgoing email.

    Returns ``(resolved_path, None)`` when allowed, else ``(None, error)``.
    Does not check that the file exists.
    """
    if not path or not path.strip():
        return None, "Error: A file path is required."

    resolved = _resolve(path)
    home = _home()

    # Anything the server may write is also fine to attach (e.g. /tmp).
    for root in allowed_write_roots():
        rel = _relative_parts(resolved, root)
        if rel is not None and not _has_hidden_part(rel):
            return resolved, None

    rel = _relative_parts(resolved, home)
    if rel is None:
        return None, (
            f"Error: Attachment path must be under your home directory ({home}). Got: {resolved}"
        )
    if _has_hidden_part(rel):
        return None, (
            f"Error: Cannot attach hidden files or files from hidden directories. Got: {resolved}"
        )
    if rel and rel[0].casefold() == "library":
        readable = any(
            _relative_parts(resolved, os.path.join(home, *sub)) is not None
            for sub in _READABLE_LIBRARY_SUBDIRS
        )
        if not readable:
            return None, (
                "Error: Cannot attach files from ~/Library (app data, keychains, "
                f"browser profiles). Got: {resolved}"
            )
    return resolved, None

"""Shared filesystem path guard for tools that write or attach files.

Attachment content is attacker-controlled (anyone can email the user a file)
and tool arguments can be steered by prompt injection, so every tool that
touches the filesystem goes through one of the two validators here instead of
keeping its own list (#19, #103).

Default (broad): writes and attachments may use any path the user can access,
except a hardened denylist of genuinely dangerous targets:

- Writes: shell startup and auth files (any dotfile or dot-folder directly in
  ``$HOME``, e.g. ``~/.zshrc``, ``~/.ssh``, ``~/.gitconfig``, ``~/.config``),
  ``~/bin``, ``.git/hooks``, ``.git/config`` and ``.envrc`` anywhere, macOS
  autostart and persistence locations (``~/Library/LaunchAgents``,
  ``/Library/LaunchDaemons``, ``~/Library/Application Support``,
  ``~/Library/Preferences``, ...) and directories on ``PATH`` such as
  ``/usr/local/bin``.
- Attachments: secrets only (``~/.ssh``, ``~/.gnupg``, ``~/.aws``,
  ``~/.netrc``, credential files, ``~/Library/Keychains``, browser profiles
  and cookie stores).

Opt-in restriction: set ``APPLE_MAIL_MCP_WRITE_DIRS`` and/or
``APPLE_MAIL_MCP_ATTACH_DIRS`` (``os.pathsep``-separated), or pass
``--write-dir`` / ``--attach-dir`` on the command line, to turn that side into
an allowlist of only those folders. The denylist still applies inside them.

Paths are resolved with ``realpath`` (so ``..`` and symlinks cannot escape)
and compared case-insensitively, because APFS is case-insensitive by default.
"""

import os
from typing import Iterable, List, Optional, Sequence, Tuple

WRITE_DIRS_ENV = "APPLE_MAIL_MCP_WRITE_DIRS"
ATTACH_DIRS_ENV = "APPLE_MAIL_MCP_ATTACH_DIRS"
# Backwards-compatible alias.
EXTRA_WRITE_DIRS_ENV = WRITE_DIRS_ENV

# The tool's own cache dir (default rich-draft location); always writable,
# even when an allowlist is configured.
_CACHE_SUBDIR = ("Library", "Caches", "apple-mail-mcp")

# --- Write denylist -------------------------------------------------------
# Every hidden entry directly in $HOME is also denied (see _is_denied_write),
# which covers shell rc files, ~/.ssh, ~/.gnupg, ~/.aws, ~/.config, ~/.netrc,
# ~/.gitconfig, ~/.local/bin, ~/.claude and any rc file not listed here.

# Relative to $HOME.
_DENIED_WRITE_HOME = (
    ("bin",),
    ("Library", "LaunchAgents"),
    ("Library", "LaunchDaemons"),
    ("Library", "StartupItems"),
    ("Library", "Application Support"),  # incl. com.apple.backgroundtaskmanagementagent
    ("Library", "Application Scripts"),  # Mail rule AppleScripts
    ("Library", "Scripts"),
    ("Library", "Preferences"),
    ("Library", "Keychains"),
    ("Library", "Mail"),
    ("Library", "Services"),
    ("Library", "Containers"),
    ("Library", "Group Containers"),
    ("Library", "Input Methods"),
    ("Library", "PreferencePanes"),
    ("Library", "QuickLook"),
    ("Library", "Spotlight"),
)

# Absolute system locations (autostart, config, PATH dirs).
_DENIED_WRITE_ABS = (
    "/Library/LaunchAgents",
    "/Library/LaunchDaemons",
    "/Library/StartupItems",
    "/Library/Application Support",
    "/Library/Preferences",
    "/Library/Scripts",
    "/etc",
    "/private/etc",
    "/usr/local/bin",
    "/usr/local/sbin",
    "/opt/homebrew/bin",
    "/opt/homebrew/sbin",
)

# Basenames rejected anywhere (direnv runs .envrc on cd).
_DENIED_WRITE_NAMES = (".envrc",)

# --- Attachment (read) denylist ------------------------------------------
# Relative to $HOME.
_DENIED_READ_HOME = (
    (".ssh",),
    (".gnupg",),
    (".aws",),
    (".azure",),
    (".kube",),
    (".docker",),
    (".netrc",),
    (".git-credentials",),
    (".npmrc",),
    (".pypirc",),
    (".password-store",),
    (".config", "gh"),
    (".config", "gcloud"),
    (".claude", ".credentials.json"),
    ("Library", "Keychains"),
    ("Library", "Cookies"),
    ("Library", "Safari"),
    ("Library", "Application Support", "Google", "Chrome"),
    ("Library", "Application Support", "Chromium"),
    ("Library", "Application Support", "BraveSoftware"),
    ("Library", "Application Support", "Microsoft Edge"),
    ("Library", "Application Support", "Arc"),
    ("Library", "Application Support", "Vivaldi"),
    ("Library", "Application Support", "Firefox"),
    ("Library", "Application Support", "1Password"),
    ("Library", "Group Containers", "2BUA8C4S2C.com.1password"),
    ("Library", "Containers", "com.apple.Safari"),
)

# Basenames rejected anywhere (dotenv secrets).
_DENIED_READ_NAMES = (".env",)

# Directories added with --write-dir / --attach-dir (see configure()).
_cli_write_dirs: List[str] = []
_cli_attach_dirs: List[str] = []


def configure(write_dirs: Optional[Iterable[str]] = None,
              attach_dirs: Optional[Iterable[str]] = None) -> None:
    """Set allowlist folders from the command line (in addition to the env)."""
    _cli_write_dirs[:] = [d for d in (write_dirs or []) if d and d.strip()]
    _cli_attach_dirs[:] = [d for d in (attach_dirs or []) if d and d.strip()]


def _home() -> str:
    return os.path.realpath(os.path.expanduser("~"))


def _resolve(path: str) -> str:
    return os.path.realpath(os.path.expanduser(path.strip()))


def _split(path: str) -> List[str]:
    return [p for p in path.split(os.sep) if p]


def _relative_parts(path: str, root: str) -> Optional[List[str]]:
    """Components of ``path`` below ``root`` (case-insensitive), or None if
    ``path`` is not ``root`` or inside it. Returned parts keep their case."""
    path_parts = _split(path)
    root_parts = _split(root)
    if len(path_parts) < len(root_parts):
        return None
    for a, b in zip(path_parts, root_parts):
        if a.casefold() != b.casefold():
            return None
    return path_parts[len(root_parts):]


def _under_any(path: str, roots: Iterable[str]) -> bool:
    return any(_relative_parts(path, root) is not None for root in roots)


def _with_resolved(paths_: Iterable[str]) -> List[str]:
    """Each path plus its realpath (e.g. /etc and /private/etc on macOS)."""
    roots = []
    for p in paths_:
        roots.append(p)
        resolved = os.path.realpath(p)
        if resolved != p:
            roots.append(resolved)
    return roots


def _home_roots(home: str, subs: Sequence[Tuple[str, ...]]) -> List[str]:
    return _with_resolved(os.path.join(home, *sub) for sub in subs)


def _configured_dirs(env_name: str, cli_dirs: List[str]) -> List[str]:
    dirs = [d for d in os.environ.get(env_name, "").split(os.pathsep) if d.strip()]
    dirs.extend(cli_dirs)
    return [_resolve(d) for d in dirs]


def allowed_write_roots() -> Optional[List[str]]:
    """Allowlisted write folders, or None when writes are unrestricted."""
    dirs = _configured_dirs(WRITE_DIRS_ENV, _cli_write_dirs)
    if not dirs:
        return None
    dirs.append(os.path.realpath(os.path.join(_home(), *_CACHE_SUBDIR)))
    return dirs


def allowed_attach_roots() -> Optional[List[str]]:
    """Allowlisted attachment folders, or None when attachments are unrestricted."""
    dirs = _configured_dirs(ATTACH_DIRS_ENV, _cli_attach_dirs)
    return dirs or None


def _is_denied_write(resolved: str) -> Optional[str]:
    """Reason ``resolved`` is a dangerous write target, or None."""
    parts = _split(resolved)
    folded = [p.casefold() for p in parts]

    for i, part in enumerate(folded[:-1]):
        if part == ".git" and folded[i + 1] in ("hooks", "config"):
            return "git hooks and git config run code"
    if folded and folded[-1] in _DENIED_WRITE_NAMES:
        return f"{parts[-1]} files run code"

    home = _home()
    rel = _relative_parts(resolved, home)
    if rel and rel[0].startswith("."):
        return "shell startup, config and credential files in your home folder"
    if _under_any(resolved, _home_roots(home, _DENIED_WRITE_HOME)):
        return "autostart, app-config and PATH folders"
    if _under_any(resolved, _with_resolved(_DENIED_WRITE_ABS)):
        return "system autostart, config and PATH folders"
    return None


def _is_denied_read(resolved: str) -> Optional[str]:
    """Reason ``resolved`` is a secret that must not be attached, or None."""
    if os.path.basename(resolved).casefold() in _DENIED_READ_NAMES:
        return ".env secrets files"
    if _under_any(resolved, _home_roots(_home(), _DENIED_READ_HOME)):
        return "SSH/GPG keys, cloud and git credentials, keychains and browser profiles"
    return None


def _show(path: str) -> str:
    rel = _relative_parts(path, _home())
    if rel is None:
        return path
    return "~" + (os.sep + os.sep.join(rel) if rel else "")


def validate_write_path(path: str) -> Tuple[Optional[str], Optional[str]]:
    """Validate a destination for a file write.

    Returns ``(resolved_path, None)`` when allowed, else ``(None, error)``.
    """
    if not path or not path.strip():
        return None, "Error: A destination path is required."

    resolved = _resolve(path)
    # Check the path as given as well as where it resolves to: a symlink that
    # sits in a protected folder (e.g. /opt/homebrew/bin/python3) points
    # outside it, but writing through it still replaces what it runs.
    requested = os.path.normpath(os.path.abspath(os.path.expanduser(path.strip())))
    reason = _is_denied_write(requested) or _is_denied_write(resolved)
    if reason:
        return None, (
            f"Error: Refusing to write to a protected location ({reason}). Got: {resolved}"
        )

    roots = allowed_write_roots()
    if roots is not None and not _under_any(resolved, roots):
        shown = ", ".join(_show(r) for r in roots)
        return None, (
            f"Error: Destination is outside the allowed folders ({shown}), set via "
            f"{WRITE_DIRS_ENV} or --write-dir. Got: {resolved}"
        )
    return resolved, None


def validate_read_path(path: str) -> Tuple[Optional[str], Optional[str]]:
    """Validate a file to be attached to an outgoing email.

    Returns ``(resolved_path, None)`` when allowed, else ``(None, error)``.
    Does not check that the file exists.
    """
    if not path or not path.strip():
        return None, "Error: A file path is required."

    resolved = _resolve(path)
    reason = _is_denied_read(resolved)
    if reason:
        return None, f"Error: Cannot attach protected files ({reason}). Got: {resolved}"

    roots = allowed_attach_roots()
    if roots is not None and not _under_any(resolved, roots):
        shown = ", ".join(_show(r) for r in roots)
        return None, (
            f"Error: Attachment is outside the allowed folders ({shown}), set via "
            f"{ATTACH_DIRS_ENV} or --attach-dir. Got: {resolved}"
        )
    return resolved, None

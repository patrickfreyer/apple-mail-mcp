"""MCP tool annotations (safety hints) shared by every tool.

Every tool states all four hints explicitly so clients and plugin
directories can tell reads from writes and irreversible actions apart.
"""

from mcp.types import ToolAnnotations


def read_only(title: str) -> ToolAnnotations:
    """Reads local Mail.app data only; changes nothing."""
    return ToolAnnotations(
        title=title,
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )


def local_write(title: str, *, destructive: bool = False, idempotent: bool = False) -> ToolAnnotations:
    """Changes local mail state or files; nothing leaves the Mac."""
    return ToolAnnotations(
        title=title,
        readOnlyHint=False,
        destructiveHint=destructive,
        idempotentHint=idempotent,
        openWorldHint=False,
    )


def syncs_with_server(title: str) -> ToolAnnotations:
    """Asks Mail.app to contact the account's mail server; changes no mail."""
    return ToolAnnotations(
        title=title,
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )


def sends_mail(title: str) -> ToolAnnotations:
    """Can send email to other people, which cannot be undone."""
    return ToolAnnotations(
        title=title,
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=True,
    )

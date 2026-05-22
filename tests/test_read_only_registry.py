"""Tests for --read-only tool registry behavior and MCP tool annotations."""

import unittest
from unittest.mock import MagicMock

import apple_mail_mcp  # noqa: F401 — registers tools
from apple_mail_mcp.server import (
    DESTRUCTIVE_TOOL_ANNOTATIONS,
    IDEMPOTENT_WRITE_TOOL_ANNOTATIONS,
    READ_ONLY_TOOL_ANNOTATIONS,
    SEND_TOOLS,
    WRITE_TOOL_ANNOTATIONS,
    mcp,
)

READ_ONLY_TOOLS = {
    "list_accounts",
    "list_account_addresses",
    "list_mailboxes",
    "list_inbox_emails",
    "get_mailbox_unread_counts",
    "get_inbox_overview",
    "search_emails",
    "get_email_by_id",
    "get_email_thread",
    "get_awaiting_reply",
    "get_needs_response",
    "get_top_senders",
    "list_email_attachments",
    "get_statistics",
    "inbox_dashboard",
}

WRITE_TOOLS = {
    "export_emails",
    "save_email_attachment",
    "move_email",
    "create_mailbox",
    "create_rich_email_draft",
}

IDEMPOTENT_WRITE_TOOLS = {
    "update_email_status",
    "synchronize_account",
}

DESTRUCTIVE_TOOLS = {
    "manage_trash",
    "compose_email",
    "reply_to_email",
    "forward_email",
    "manage_drafts",
}


class ReadOnlyRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.by_name = {tool.name: tool for tool in mcp._tool_manager.list_tools()}

    def test_send_tools_registered_by_default(self):
        names = set(self.by_name)
        self.assertTrue(set(SEND_TOOLS).issubset(names))
        self.assertGreaterEqual(len(names), 27)

    def test_remove_send_tools_drops_only_send_tools(self):
        mock_mcp = MagicMock()
        mock_mcp.remove_tool = MagicMock()

        for name in SEND_TOOLS:
            try:
                mock_mcp.remove_tool(name)
            except (KeyError, ValueError):
                pass

        self.assertEqual(mock_mcp.remove_tool.call_count, len(SEND_TOOLS))
        removed = {call.args[0] for call in mock_mcp.remove_tool.call_args_list}
        self.assertEqual(removed, set(SEND_TOOLS))

    def test_all_tools_have_annotations(self):
        for name, tool in self.by_name.items():
            with self.subTest(tool=name):
                self.assertIsNotNone(tool.annotations, f"{name} missing annotations")

    def test_read_only_tools_annotated(self):
        for name in READ_ONLY_TOOLS:
            tool = self.by_name[name]
            self.assertEqual(tool.annotations, READ_ONLY_TOOL_ANNOTATIONS, name)

    def test_write_tools_annotated(self):
        for name in WRITE_TOOLS:
            tool = self.by_name[name]
            self.assertEqual(tool.annotations, WRITE_TOOL_ANNOTATIONS, name)

    def test_idempotent_write_tools_annotated(self):
        for name in IDEMPOTENT_WRITE_TOOLS:
            tool = self.by_name[name]
            self.assertEqual(tool.annotations, IDEMPOTENT_WRITE_TOOL_ANNOTATIONS, name)

    def test_destructive_tools_annotated(self):
        for name in DESTRUCTIVE_TOOLS:
            tool = self.by_name[name]
            self.assertEqual(tool.annotations, DESTRUCTIVE_TOOL_ANNOTATIONS, name)

    def test_annotation_matrix_covers_all_tools(self):
        covered = (
            READ_ONLY_TOOLS
            | WRITE_TOOLS
            | IDEMPOTENT_WRITE_TOOLS
            | DESTRUCTIVE_TOOLS
        )
        self.assertEqual(covered, set(self.by_name.keys()))


if __name__ == "__main__":
    unittest.main()

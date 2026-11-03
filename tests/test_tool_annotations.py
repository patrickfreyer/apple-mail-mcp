"""Every tool must state its safety hints explicitly (plugin directory policy)."""

import asyncio
import unittest

from apple_mail_mcp import mcp

# Tools that can send email to other people.
SENDING_TOOLS = {"compose_email", "reply_to_email", "forward_email", "manage_drafts"}

# Tools that can delete mail or overwrite files.
DESTRUCTIVE_TOOLS = SENDING_TOOLS | {
    "manage_trash",
    "save_email_attachment",
    "export_emails",
    "create_rich_email_draft",
}


class ToolAnnotationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tools = {t.name: t for t in asyncio.run(mcp.list_tools())}

    def test_every_tool_has_title_and_all_hints(self):
        for name, tool in self.tools.items():
            with self.subTest(tool=name):
                a = tool.annotations
                self.assertIsNotNone(a, "missing annotations")
                self.assertTrue(a.title, "missing title")
                for hint in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
                    self.assertIsNotNone(getattr(a, hint), f"{hint} not set")

    def test_destructive_tools_are_marked(self):
        for name in DESTRUCTIVE_TOOLS & self.tools.keys():
            with self.subTest(tool=name):
                a = self.tools[name].annotations
                self.assertFalse(a.readOnlyHint)
                self.assertTrue(a.destructiveHint)

    def test_only_sending_tools_reach_other_people(self):
        for name, tool in self.tools.items():
            if name == "synchronize_account":
                continue  # contacts the user's own mail server, sends nothing
            with self.subTest(tool=name):
                self.assertEqual(tool.annotations.openWorldHint, name in SENDING_TOOLS)

    def test_read_only_tools_are_not_destructive(self):
        for name, tool in self.tools.items():
            if tool.annotations.readOnlyHint:
                with self.subTest(tool=name):
                    self.assertFalse(tool.annotations.destructiveHint)


if __name__ == "__main__":
    unittest.main()

"""Tests for the --read-only tool removal in __main__."""

import asyncio
import unittest

from fastmcp import FastMCP

from apple_mail_mcp.__main__ import _remove_tool


def _tool_names(server: FastMCP) -> set[str]:
    return {t.name for t in asyncio.run(server.list_tools())}


class RemoveToolTests(unittest.TestCase):
    def setUp(self):
        # A private server instance so the package-level singleton is untouched.
        self.server = FastMCP("test")

        @self.server.tool
        def send_it() -> str:
            return "sent"

        @self.server.tool
        def read_it() -> str:
            return "read"

    def test_removes_registered_tool(self):
        _remove_tool(self.server, "send_it")
        self.assertEqual(_tool_names(self.server), {"read_it"})

    def test_ignores_unknown_tool(self):
        _remove_tool(self.server, "does_not_exist")
        self.assertEqual(_tool_names(self.server), {"send_it", "read_it"})


if __name__ == "__main__":
    unittest.main()

"""Tests for the shared file-path guard (#103).

Writes are confined to an allowlist of safe roots (~/Downloads, ~/Desktop,
~/Documents, the tool's own cache dir, the system temp dir, plus any extra
dirs the user opts into via APPLE_MAIL_MCP_WRITE_DIRS). Attachment reads are
confined to $HOME minus hidden entries and ~/Library internals.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from apple_mail_mcp import paths
from apple_mail_mcp.tools import analytics as analytics_tools
from apple_mail_mcp.tools import compose as compose_tools
from apple_mail_mcp.tools import manage as manage_tools


class _FakeHomeTestCase(unittest.TestCase):
    """Point $HOME at a throwaway dir and the temp roots at a separate one.

    The fake home itself lives under the system temp dir, so the real temp
    roots are swapped out; otherwise every path under the fake home would be
    accepted via the temp-dir allowance and the tests would prove nothing.
    """

    def setUp(self):
        self._home_tmp = tempfile.TemporaryDirectory()
        self._scratch_tmp = tempfile.TemporaryDirectory()
        self.home = os.path.realpath(self._home_tmp.name)
        self.scratch = os.path.realpath(self._scratch_tmp.name)
        for sub in ("Downloads", "Desktop", "Documents", "bin", "Library"):
            os.makedirs(os.path.join(self.home, sub), exist_ok=True)

        env = {k: v for k, v in os.environ.items() if k != paths.EXTRA_WRITE_DIRS_ENV}
        env["HOME"] = self.home
        self._patches = [
            patch.dict(os.environ, env, clear=True),
            patch.object(paths, "_temp_roots", return_value=[self.scratch]),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        self._home_tmp.cleanup()
        self._scratch_tmp.cleanup()

    def h(self, *parts):
        return os.path.join(self.home, *parts)

    def assertWriteRejected(self, path):
        resolved, error = paths.validate_write_path(path)
        self.assertIsNone(resolved, f"expected {path!r} to be rejected")
        self.assertTrue(error and error.startswith("Error:"), error)

    def assertWriteAllowed(self, path):
        resolved, error = paths.validate_write_path(path)
        self.assertIsNone(error, f"expected {path!r} to be allowed, got {error}")
        return resolved


class WritePathTests(_FakeHomeTestCase):
    def test_shell_startup_files_are_rejected(self):
        for name in (".zshrc", ".zprofile", ".zshenv", ".zlogin", ".bashrc",
                     ".bash_profile", ".profile"):
            with self.subTest(name=name):
                self.assertWriteRejected("~/" + name)

    def test_dot_directories_are_rejected(self):
        for rel in (".ssh/authorized_keys", ".gnupg/gpg.conf", ".aws/credentials",
                    ".config/fish/config.fish", ".claude/settings.json",
                    ".local/bin/git", ".gitconfig", ".git-credentials"):
            with self.subTest(rel=rel):
                self.assertWriteRejected("~/" + rel)

    def test_library_and_bin_are_rejected(self):
        for rel in ("Library/LaunchAgents/evil.plist",
                    "Library/LaunchDaemons/evil.plist",
                    "Library/Application Support/Code/User/tasks.json",
                    "Library/Preferences/com.apple.Terminal.plist",
                    "Library/Keychains/login.keychain-db",
                    "bin/ls"):
            with self.subTest(rel=rel):
                self.assertWriteRejected("~/" + rel)

    def test_home_root_and_paths_outside_home_are_rejected(self):
        self.assertWriteRejected("~")
        self.assertWriteRejected("~/notes.txt")
        self.assertWriteRejected("/etc/periodic/daily/evil")
        self.assertWriteRejected("")

    def test_hidden_components_inside_safe_roots_are_rejected(self):
        # A git repo in ~/Documents is a common case: its hooks run code.
        self.assertWriteRejected("~/Documents/repo/.git/hooks/pre-commit")
        self.assertWriteRejected("~/Documents/project/.envrc")
        self.assertWriteRejected("~/Desktop/.vscode/tasks.json")

    def test_dot_dot_traversal_is_rejected(self):
        self.assertWriteRejected("~/Downloads/../.zshrc")
        self.assertWriteRejected("~/Documents/../../../../etc/hosts")

    def test_symlink_escaping_safe_root_is_rejected(self):
        os.symlink(self.h(".zshrc"), self.h("Downloads", "invoice.pdf"))
        self.assertWriteRejected("~/Downloads/invoice.pdf")
        os.symlink(self.h("Library", "LaunchAgents"), self.h("Desktop", "agents"))
        self.assertWriteRejected("~/Desktop/agents/evil.plist")

    def test_case_variants_are_handled(self):
        # APFS is case-insensitive by default: ~/.ZSHRC *is* ~/.zshrc.
        self.assertWriteRejected("~/.ZSHRC")
        self.assertWriteRejected("~/LIBRARY/LaunchAgents/evil.plist")
        resolved = self.assertWriteAllowed("~/downloads/report.pdf")
        self.assertTrue(resolved.endswith(os.path.join("downloads", "report.pdf")))

    def test_safe_roots_are_allowed(self):
        for rel in ("Downloads/invoice.pdf", "Desktop/export", "Documents/Mail/a.txt",
                    "Downloads", "Desktop",
                    "Library/Caches/apple-mail-mcp/rich-drafts/x.eml"):
            with self.subTest(rel=rel):
                resolved = self.assertWriteAllowed("~/" + rel)
                self.assertEqual(resolved, self.h(*rel.split("/")))

    def test_temp_dir_is_allowed(self):
        target = os.path.join(self.scratch, "out.txt")
        self.assertEqual(self.assertWriteAllowed(target), target)

    def test_extra_write_dirs_env_opt_in(self):
        self.assertWriteRejected("~/Projects/mail/a.txt")
        extra = os.pathsep.join([self.h("Projects"), "~/Archive"])
        with patch.dict(os.environ, {paths.EXTRA_WRITE_DIRS_ENV: extra}):
            self.assertWriteAllowed("~/Projects/mail/a.txt")
            self.assertWriteAllowed("~/Archive/b.txt")
            self.assertWriteRejected("~/Projects/repo/.git/config")
            self.assertWriteRejected("~/.zshrc")

    def test_error_names_the_allowed_roots_and_opt_in(self):
        _, error = paths.validate_write_path("~/.zshrc")
        self.assertIn("Downloads", error)
        self.assertIn(paths.EXTRA_WRITE_DIRS_ENV, error)


class ReadPathTests(_FakeHomeTestCase):
    def _touch(self, *parts):
        path = self.h(*parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write("x")
        return path

    def test_secrets_are_rejected(self):
        for parts in ((".ssh", "id_ed25519"), (".aws", "credentials"), (".netrc",),
                      (".zsh_history",), (".config", "gh", "hosts.yml"),
                      ("Documents", "app", ".env"),
                      ("Library", "Keychains", "login.keychain-db"),
                      ("Library", "Application Support", "Google", "Chrome", "Cookies")):
            with self.subTest(parts=parts):
                self._touch(*parts)
                resolved, error = paths.validate_read_path(self.h(*parts))
                self.assertIsNone(resolved)
                self.assertTrue(error.startswith("Error:"), error)

    def test_symlink_to_secret_is_rejected(self):
        secret = self._touch(".ssh", "id_rsa")
        os.symlink(secret, self.h("Desktop", "harmless.txt"))
        resolved, error = paths.validate_read_path("~/Desktop/harmless.txt")
        self.assertIsNone(resolved)
        self.assertIsNotNone(error)

    def test_regular_files_are_allowed(self):
        for parts in (("Documents", "report.pdf"), ("Projects", "deck.key"),
                      ("Library", "Mobile Documents", "com~apple~CloudDocs", "a.pdf"),
                      ("Library", "CloudStorage", "OneDrive", "b.docx")):
            with self.subTest(parts=parts):
                path = self._touch(*parts)
                resolved, error = paths.validate_read_path(path)
                self.assertIsNone(error)
                self.assertEqual(resolved, path)

    def test_outside_home_is_rejected(self):
        resolved, error = paths.validate_read_path("/etc/hosts")
        self.assertIsNone(resolved)
        self.assertIsNotNone(error)


class ToolWiringTests(_FakeHomeTestCase):
    """Every file-touching tool must go through the shared guard."""

    def test_save_email_attachment_rejects_zshrc(self):
        with patch("apple_mail_mcp.tools.manage.run_applescript") as mock_run:
            result = manage_tools.save_email_attachment(
                account="Work", subject_keyword="Invoice",
                attachment_name="payload", save_path="~/.zshrc",
            )
        self.assertTrue(result.startswith("Error:"), result)
        mock_run.assert_not_called()

    def test_save_email_attachment_allows_downloads(self):
        with patch("apple_mail_mcp.tools.manage.run_applescript",
                   return_value="ok") as mock_run:
            manage_tools.save_email_attachment(
                account="Work", subject_keyword="Invoice",
                attachment_name="invoice.pdf", save_path="~/Downloads/invoice.pdf",
            )
        mock_run.assert_called_once()
        self.assertIn(self.h("Downloads", "invoice.pdf"), mock_run.call_args[0][0])

    def test_export_emails_rejects_library(self):
        with patch("apple_mail_mcp.tools.analytics.run_applescript") as mock_run:
            result = analytics_tools.export_emails(
                account="Work", scope="single_email", subject_keyword="x",
                save_directory="~/Library/Application Support/Code/User",
            )
        self.assertTrue(result.startswith("Error:"), result)
        mock_run.assert_not_called()

    def test_export_emails_allows_default_desktop(self):
        with patch("apple_mail_mcp.tools.analytics.run_applescript",
                   return_value="ok") as mock_run:
            analytics_tools.export_emails(
                account="Work", scope="single_email", subject_keyword="x",
            )
        mock_run.assert_called_once()

    def test_compose_attachment_rejects_ssh_key(self):
        key = self.h(".ssh", "id_rsa")
        os.makedirs(os.path.dirname(key))
        with open(key, "w") as fh:
            fh.write("PRIVATE")
        paths_out, error = compose_tools._validate_attachment_paths("~/.ssh/id_rsa")
        self.assertEqual(paths_out, [])
        self.assertTrue(error.startswith("Error:"), error)

    def test_rich_draft_output_path_rejects_zshrc(self):
        with (
            patch("apple_mail_mcp.tools.compose.run_applescript", return_value=""),
            patch("apple_mail_mcp.tools.compose.subprocess.run") as mock_open,
        ):
            result = compose_tools.create_rich_email_draft(
                account="Work", subject="Hi", text_body="echo pwned",
                output_path="~/.zshrc",
            )
        self.assertTrue(result.startswith("Error:"), result)
        self.assertFalse(os.path.exists(self.h(".zshrc")))
        mock_open.assert_not_called()

    def test_rich_draft_default_path_still_works(self):
        with (
            patch("apple_mail_mcp.tools.compose.run_applescript", return_value=""),
            patch("apple_mail_mcp.tools.compose.subprocess.run"),
        ):
            result = compose_tools.create_rich_email_draft(
                account="Work", subject="Hi", text_body="body", open_in_mail=False,
            )
        expected = self.h("Library", "Caches", "apple-mail-mcp", "rich-drafts", "Hi.eml")
        self.assertIn(expected, result)
        self.assertTrue(os.path.exists(expected))


if __name__ == "__main__":
    unittest.main()

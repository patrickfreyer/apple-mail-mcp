"""Tests for the shared file-path guard (#103).

Default is broad: writes go anywhere except a hardened denylist (shell startup
and auth files, dot-folders in $HOME, .git/hooks, autostart and PATH folders);
attachments may come from anywhere except secrets (keys, credentials,
keychains, browser profiles). APPLE_MAIL_MCP_WRITE_DIRS / ATTACH_DIRS (or the
--write-dir / --attach-dir flags) turn either side into an allowlist, with the
denylist still applied inside it.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from apple_mail_mcp import paths
from apple_mail_mcp.tools import analytics as analytics_tools
from apple_mail_mcp.tools import compose as compose_tools
from apple_mail_mcp.tools import manage as manage_tools


class _FakeHomeTestCase(unittest.TestCase):
    """Point $HOME at a throwaway dir and clear any configured allowlists."""

    def setUp(self):
        self._home_tmp = tempfile.TemporaryDirectory()
        self._other_tmp = tempfile.TemporaryDirectory()
        self.home = os.path.realpath(self._home_tmp.name)
        self.other = os.path.realpath(self._other_tmp.name)
        for sub in ("Downloads", "Desktop", "Documents", "Projects", "bin", "Library"):
            os.makedirs(os.path.join(self.home, sub), exist_ok=True)

        env = {k: v for k, v in os.environ.items()
               if k not in (paths.WRITE_DIRS_ENV, paths.ATTACH_DIRS_ENV)}
        env["HOME"] = self.home
        self._env_patch = patch.dict(os.environ, env, clear=True)
        self._env_patch.start()
        paths.configure()

    def tearDown(self):
        paths.configure()
        self._env_patch.stop()
        self._home_tmp.cleanup()
        self._other_tmp.cleanup()

    def h(self, *parts):
        return os.path.join(self.home, *parts)

    def _touch(self, *parts):
        path = self.h(*parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write("x")
        return path

    def assertWriteRejected(self, path):
        resolved, error = paths.validate_write_path(path)
        self.assertIsNone(resolved, f"expected {path!r} to be rejected")
        self.assertTrue(error and error.startswith("Error:"), error)
        return error

    def assertWriteAllowed(self, path):
        resolved, error = paths.validate_write_path(path)
        self.assertIsNone(error, f"expected {path!r} to be allowed, got {error}")
        return resolved

    def assertReadRejected(self, path):
        resolved, error = paths.validate_read_path(path)
        self.assertIsNone(resolved, f"expected {path!r} to be rejected")
        self.assertTrue(error and error.startswith("Error:"), error)
        return error

    def assertReadAllowed(self, path):
        resolved, error = paths.validate_read_path(path)
        self.assertIsNone(error, f"expected {path!r} to be allowed, got {error}")
        return resolved


class WriteDenylistTests(_FakeHomeTestCase):
    def test_shell_startup_files_are_rejected(self):
        for name in (".zshrc", ".zprofile", ".zshenv", ".zlogin", ".bashrc",
                     ".bash_profile", ".profile", ".vimrc", ".tmux.conf"):
            with self.subTest(name=name):
                self.assertWriteRejected("~/" + name)

    def test_auth_files_and_dot_dirs_are_rejected(self):
        for rel in (".ssh/authorized_keys", ".gnupg/gpg.conf", ".aws/credentials",
                    ".config/git/config", ".config/fish/config.fish",
                    ".claude/settings.json", ".local/bin/git", ".gitconfig",
                    ".git-credentials", ".netrc", ".envrc"):
            with self.subTest(rel=rel):
                self.assertWriteRejected("~/" + rel)

    def test_git_hooks_config_and_envrc_anywhere_are_rejected(self):
        for path in ("~/Documents/repo/.git/hooks/pre-commit",
                     "~/Projects/repo/.git/config",
                     "~/Desktop/project/.envrc",
                     os.path.join(self.other, "repo", ".git", "hooks", "post-merge")):
            with self.subTest(path=path):
                self.assertWriteRejected(path)

    def test_autostart_and_persistence_locations_are_rejected(self):
        for rel in ("Library/LaunchAgents/evil.plist",
                    "Library/LaunchDaemons/evil.plist",
                    "Library/Application Support/com.apple.backgroundtaskmanagementagent/x",
                    "Library/Application Support/Code/User/tasks.json",
                    "Library/Application Scripts/com.apple.mail/rule.scpt",
                    "Library/Preferences/com.apple.Terminal.plist",
                    "Library/Keychains/login.keychain-db",
                    "bin/ls"):
            with self.subTest(rel=rel):
                self.assertWriteRejected("~/" + rel)
        for path in ("/Library/LaunchAgents/evil.plist",
                     "/Library/LaunchDaemons/evil.plist",
                     "/etc/periodic/daily/evil",
                     "/usr/local/bin/git",
                     "/opt/homebrew/bin/python3"):
            with self.subTest(path=path):
                self.assertWriteRejected(path)

    def test_dot_dot_traversal_is_rejected(self):
        self.assertWriteRejected("~/Downloads/../.zshrc")
        self.assertWriteRejected("~/Documents/../Library/LaunchAgents/x.plist")

    def test_symlink_inside_protected_location_is_rejected(self):
        # The other direction: a link that lives in a protected folder but
        # points outside it. Writing through ~/bin/tool replaces what the
        # tool runs, yet only the resolved target used to be checked. This
        # is the /opt/homebrew/bin/python3 case above, without depending on
        # how the machine running the tests lays out Homebrew.
        os.makedirs(self.h("bin"), exist_ok=True)
        os.makedirs(self.h("Tools"), exist_ok=True)
        open(self.h("Tools", "real"), "w").close()
        os.symlink(self.h("Tools", "real"), self.h("bin", "tool"))
        self.assertWriteRejected("~/bin/tool")

    def test_symlink_into_protected_location_is_rejected(self):
        os.symlink(self.h(".zshrc"), self.h("Downloads", "invoice.pdf"))
        self.assertWriteRejected("~/Downloads/invoice.pdf")
        os.makedirs(self.h("Library", "LaunchAgents"))
        os.symlink(self.h("Library", "LaunchAgents"), self.h("Desktop", "agents"))
        self.assertWriteRejected("~/Desktop/agents/evil.plist")

    def test_case_variants_are_handled(self):
        # APFS is case-insensitive by default: ~/.ZSHRC *is* ~/.zshrc.
        self.assertWriteRejected("~/.ZSHRC")
        self.assertWriteRejected("~/LIBRARY/LaunchAgents/evil.plist")
        self.assertWriteRejected("~/Documents/repo/.GIT/Hooks/pre-commit")

    def test_error_names_the_reason(self):
        error = self.assertWriteRejected("~/.zshrc")
        self.assertIn("protected location", error)


class WriteDefaultBroadTests(_FakeHomeTestCase):
    def test_ordinary_locations_are_allowed(self):
        for rel in ("Downloads/invoice.pdf", "Desktop/export", "Documents/Mail/a.txt",
                    "Projects/mail/a.txt", "notes.txt", "Archive/2026/b.eml",
                    "Library/Caches/apple-mail-mcp/rich-drafts/x.eml",
                    "Library/Mobile Documents/com~apple~CloudDocs/a.pdf",
                    "Library/CloudStorage/OneDrive/b.docx",
                    "Documents/repo/.git/objects/readme.txt",
                    "Documents/project/.vscode/notes.md"):
            with self.subTest(rel=rel):
                resolved = self.assertWriteAllowed("~/" + rel)
                self.assertEqual(resolved, self.h(*rel.split("/")))

    def test_home_root_and_outside_home_are_allowed(self):
        self.assertWriteAllowed("~")
        target = os.path.join(self.other, "out.txt")
        self.assertEqual(self.assertWriteAllowed(target), target)

    def test_empty_path_is_rejected(self):
        self.assertWriteRejected("")
        self.assertWriteRejected("   ")


class WriteAllowlistTests(_FakeHomeTestCase):
    def test_env_turns_writes_into_allowlist(self):
        extra = os.pathsep.join([self.h("Projects"), "~/Archive"])
        with patch.dict(os.environ, {paths.WRITE_DIRS_ENV: extra}):
            self.assertWriteAllowed("~/Projects/mail/a.txt")
            self.assertWriteAllowed("~/Archive/b.txt")
            # The tool's own cache dir (default rich-draft location) stays usable.
            self.assertWriteAllowed("~/Library/Caches/apple-mail-mcp/rich-drafts/x.eml")
            error = self.assertWriteRejected("~/Downloads/a.txt")
            self.assertIn(paths.WRITE_DIRS_ENV, error)
            self.assertWriteRejected(os.path.join(self.other, "out.txt"))

    def test_denylist_still_applies_inside_allowlist(self):
        with patch.dict(os.environ, {paths.WRITE_DIRS_ENV: self.home}):
            self.assertWriteAllowed("~/Documents/a.txt")
            self.assertWriteRejected("~/.zshrc")
            self.assertWriteRejected("~/Projects/repo/.git/config")
            self.assertWriteRejected("~/Library/LaunchAgents/evil.plist")

    def test_symlink_out_of_allowlist_is_rejected(self):
        os.symlink(self.h("Documents"), self.h("Projects", "docs"))
        with patch.dict(os.environ, {paths.WRITE_DIRS_ENV: self.h("Projects")}):
            self.assertWriteRejected("~/Projects/docs/a.txt")
            self.assertWriteRejected("~/Projects/../Documents/a.txt")

    def test_cli_write_dirs(self):
        paths.configure(write_dirs=["~/Projects"])
        self.assertWriteAllowed("~/Projects/a.txt")
        error = self.assertWriteRejected("~/Desktop/a.txt")
        self.assertIn("--write-dir", error)


class ReadPathTests(_FakeHomeTestCase):
    def test_secrets_are_rejected(self):
        for parts in ((".ssh", "id_ed25519"), (".gnupg", "secring.gpg"),
                      (".aws", "credentials"), (".netrc",), (".git-credentials",),
                      (".config", "gh", "hosts.yml"),
                      ("Documents", "app", ".env"),
                      ("Library", "Keychains", "login.keychain-db"),
                      ("Library", "Cookies", "Cookies.binarycookies"),
                      ("Library", "Application Support", "Google", "Chrome",
                       "Default", "Cookies"),
                      ("Library", "Application Support", "Firefox", "Profiles",
                       "x.default", "cookies.sqlite")):
            with self.subTest(parts=parts):
                self._touch(*parts)
                self.assertReadRejected(self.h(*parts))

    def test_case_variants_of_secrets_are_rejected(self):
        self._touch(".ssh", "id_rsa")
        self.assertReadRejected("~/.SSH/id_rsa")

    def test_symlink_to_secret_is_rejected(self):
        secret = self._touch(".ssh", "id_rsa")
        os.symlink(secret, self.h("Desktop", "harmless.txt"))
        self.assertReadRejected("~/Desktop/harmless.txt")
        self.assertReadRejected("~/Desktop/../.ssh/id_rsa")

    def test_ordinary_files_are_allowed_broadly(self):
        # Hidden files and ~/Library are fine to attach unless they hold secrets.
        for parts in (("Documents", "report.pdf"), ("Projects", "deck.key"),
                      (".zshrc",), (".config", "app", "settings.json"),
                      ("Documents", "repo", ".gitignore"),
                      ("Library", "Mobile Documents", "com~apple~CloudDocs", "a.pdf"),
                      ("Library", "CloudStorage", "OneDrive", "b.docx"),
                      ("Library", "Application Support", "MyApp", "export.csv")):
            with self.subTest(parts=parts):
                path = self._touch(*parts)
                self.assertEqual(self.assertReadAllowed(path), path)

    def test_outside_home_is_allowed(self):
        path = os.path.join(self.other, "scan.pdf")
        with open(path, "w") as fh:
            fh.write("x")
        self.assertEqual(self.assertReadAllowed(path), path)

    def test_attach_dirs_env_turns_reads_into_allowlist(self):
        ok = self._touch("Documents", "a.pdf")
        other = self._touch("Projects", "b.pdf")
        with patch.dict(os.environ, {paths.ATTACH_DIRS_ENV: "~/Documents"}):
            self.assertEqual(self.assertReadAllowed(ok), ok)
            error = self.assertReadRejected(other)
            self.assertIn(paths.ATTACH_DIRS_ENV, error)

    def test_denylist_applies_inside_attach_allowlist(self):
        self._touch(".ssh", "id_rsa")
        paths.configure(attach_dirs=[self.home])
        self.assertReadRejected("~/.ssh/id_rsa")
        self.assertReadAllowed(self._touch("Documents", "a.pdf"))


class CliFlagTests(unittest.TestCase):
    def test_main_passes_dir_flags_to_paths(self):
        from apple_mail_mcp import __main__ as entry
        argv = ["apple-mail-mcp", "--write-dir", "/a", "--write-dir", "/b",
                "--attach-dir", "/c"]
        with (
            patch.object(sys, "argv", argv),
            patch.object(entry, "_start_orphan_watcher"),
            patch.object(entry.paths, "configure") as mock_configure,
            patch("apple_mail_mcp.mcp.run"),
        ):
            entry.main()
        mock_configure.assert_called_once_with(write_dirs=["/a", "/b"],
                                               attach_dirs=["/c"])


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

    def test_save_email_attachment_allows_any_ordinary_folder(self):
        with patch("apple_mail_mcp.tools.manage.run_applescript",
                   return_value="ok") as mock_run:
            manage_tools.save_email_attachment(
                account="Work", subject_keyword="Invoice",
                attachment_name="invoice.pdf", save_path="~/Projects/acme/invoice.pdf",
            )
        mock_run.assert_called_once()
        self.assertIn(self.h("Projects", "acme", "invoice.pdf"), mock_run.call_args[0][0])

    def test_save_email_attachment_honours_write_allowlist(self):
        with (
            patch.dict(os.environ, {paths.WRITE_DIRS_ENV: "~/Downloads"}),
            patch("apple_mail_mcp.tools.manage.run_applescript") as mock_run,
        ):
            result = manage_tools.save_email_attachment(
                account="Work", subject_keyword="Invoice",
                attachment_name="invoice.pdf", save_path="~/Projects/invoice.pdf",
            )
        self.assertTrue(result.startswith("Error:"), result)
        mock_run.assert_not_called()

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

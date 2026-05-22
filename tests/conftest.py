"""Shared pytest hooks for apple-mail-mcp tests."""

import pytest


@pytest.fixture(autouse=True)
def _pass_through_known_test_accounts(monkeypatch):
    """Most tool tests pass account='Work' without mocking Mail account listing."""

    def _validate(account, timeout=30):
        if account == "Missing":
            return (
                f"Error: account_not_found — '{account}' is not configured in Mail. "
                "Available accounts: Work"
            )
        return None

    monkeypatch.setattr("apple_mail_mcp.core.validate_account_name", _validate)
    monkeypatch.setattr("apple_mail_mcp.tools.inbox.validate_account_name", _validate)
    monkeypatch.setattr("apple_mail_mcp.tools.search.validate_account_name", _validate)
    monkeypatch.setattr("apple_mail_mcp.tools.manage.validate_account_name", _validate)
    monkeypatch.setattr("apple_mail_mcp.tools.analytics.validate_account_name", _validate)
    monkeypatch.setattr("apple_mail_mcp.tools.smart_inbox.validate_account_name", _validate)
    monkeypatch.setattr("apple_mail_mcp.tools.compose.validate_account_name", _validate)

"""Tests for bulk.py pure-Python helper functions (no Mail.app interaction)."""

import sys
import os

# Ensure package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from apple_mail_mcp.tools.bulk import (
    _build_filter_conditions,
    _date_filter_script,
    _mailbox_fallback_script,
    _validate_filters,
)
from apple_mail_mcp.core import escape_applescript


def test_escape_applescript_quotes():
    assert escape_applescript('hello "world"') == 'hello \\"world\\"'


def test_escape_applescript_backslash():
    assert escape_applescript("path\\to\\file") == "path\\\\to\\\\file"


def test_build_filter_no_args():
    assert _build_filter_conditions() == "true"


def test_build_filter_subject_only():
    result = _build_filter_conditions(subject_keyword="invoice")
    assert 'messageSubject contains "invoice"' in result


def test_build_filter_sender_only():
    result = _build_filter_conditions(sender="alice@example.com")
    assert 'messageSender contains "alice@example.com"' in result


def test_build_filter_both():
    result = _build_filter_conditions(subject_keyword="hello", sender="bob")
    assert "and" in result
    assert "messageSubject" in result
    assert "messageSender" in result


def test_build_filter_escapes_injection():
    result = _build_filter_conditions(subject_keyword='"; do evil; "')
    assert '\\"' in result
    assert "do evil" in result  # still present but escaped


def test_date_filter_none():
    setup, cond = _date_filter_script(None)
    assert setup == ""
    assert cond == "true"


def test_date_filter_zero():
    setup, cond = _date_filter_script(0)
    assert setup == ""
    assert cond == "true"


def test_date_filter_positive():
    setup, cond = _date_filter_script(30)
    assert "cutoffDate" in setup
    assert "30" in setup
    assert "cutoffDate" in cond


def test_mailbox_fallback_inbox():
    script = _mailbox_fallback_script("myBox", "INBOX")
    assert '"INBOX"' in script
    assert '"Inbox"' in script  # fallback


def test_mailbox_fallback_custom():
    script = _mailbox_fallback_script("myBox", "Archive")
    assert '"Archive"' in script


def test_validate_filters_none():
    result = _validate_filters(None, None, None)
    assert result is not None
    assert "Error" in result


def test_validate_filters_subject():
    assert _validate_filters("test", None, None) is None


def test_validate_filters_sender():
    assert _validate_filters(None, "alice", None) is None


def test_validate_filters_older_than_days():
    assert _validate_filters(None, None, 30) is None


def test_validate_filters_zero_days_not_enough():
    result = _validate_filters(None, None, 0)
    assert result is not None
    assert "Error" in result


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

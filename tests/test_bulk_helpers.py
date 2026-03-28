"""Tests for core.py helper functions (no Mail.app interaction)."""

import sys
import os

# Ensure package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from apple_mail_mcp.core import (
    escape_applescript,
    build_filter_condition,
    build_date_filter,
    build_mailbox_ref,
)


def test_escape_applescript_quotes():
    assert escape_applescript('hello "world"') == 'hello \\"world\\"'


def test_escape_applescript_backslash():
    assert escape_applescript("path\\to\\file") == "path\\\\to\\\\file"


def test_build_filter_no_args():
    assert build_filter_condition() == "true"


def test_build_filter_subject_only():
    result = build_filter_condition(subject="invoice")
    assert 'messageSubject contains "invoice"' in result


def test_build_filter_sender_only():
    result = build_filter_condition(sender="alice@example.com")
    assert 'messageSender contains "alice@example.com"' in result


def test_build_filter_both():
    result = build_filter_condition(subject="hello", sender="bob")
    assert "and" in result
    assert "messageSubject" in result
    assert "messageSender" in result


def test_build_filter_escapes_injection():
    result = build_filter_condition(subject='"; do evil; "')
    assert '\\"' in result
    assert "do evil" in result  # still present but escaped


def test_date_filter_zero():
    setup, cond = build_date_filter(0)
    assert setup == ""
    assert cond == ""


def test_date_filter_positive():
    setup, cond = build_date_filter(30)
    assert "cutoffDate" in setup
    assert "30" in setup
    assert "cutoffDate" in cond


def test_mailbox_ref_inbox():
    script = build_mailbox_ref("INBOX")
    assert '"INBOX"' in script
    assert '"Inbox"' in script  # fallback


def test_mailbox_ref_custom():
    script = build_mailbox_ref("Archive")
    assert '"Archive"' in script


def test_mailbox_ref_nested():
    script = build_mailbox_ref("Projects/2024")
    assert '"2024"' in script
    assert '"Projects"' in script


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

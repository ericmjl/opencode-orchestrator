"""Unit tests for OpenCode HTTP helpers (no DB)."""

from opencode_orchestrator.opencode_client import (
    is_session_busy,
    session_summary_indicates_complete,
)


def test_is_session_busy() -> None:
    assert is_session_busy({"type": "busy"}) is True
    assert is_session_busy({"type": "idle"}) is False
    assert is_session_busy(None) is False
    assert is_session_busy({}) is False


def test_session_summary_indicates_complete() -> None:
    assert session_summary_indicates_complete({"summary": "done"}) is True
    assert session_summary_indicates_complete({"summary": {"files": 1}}) is True
    assert session_summary_indicates_complete({"summary": {"additions": 0, "files": 0}}) is True
    assert session_summary_indicates_complete({}) is False
    assert session_summary_indicates_complete({"summary": ""}) is False

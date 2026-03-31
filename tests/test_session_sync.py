"""Tests for OpenCode session status sync and client helpers."""

import asyncio
import json
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from opencode_orchestrator.models import execute, fetch_one, init_db, now


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    """Isolate SQLite and disable the OpenCode background sync loop during tests."""
    monkeypatch.setenv("OC_DISABLE_BACKGROUND_SYNC", "1")
    from opencode_orchestrator.models import database

    db_path = tmp_path / "test.db"
    monkeypatch.setattr(database, "DATABASE_PATH", db_path)
    asyncio.run(init_db())


from opencode_orchestrator.session_sync import sync_opencode_session_tasks_once
from opencode_orchestrator.session_sync import _import_session_history
from opencode_orchestrator.routers.tasks import send_task_to_agent_background


def _run(coro):
    return asyncio.run(coro)


def _seed_completed_task_with_session() -> None:
    ts = now()
    _run(execute(
        "INSERT INTO projects (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("p1", "Test", "/tmp/p1", ts, ts),
    ))
    _run(execute(
        """INSERT INTO agent_registry (id, name, command, port, cwd, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("ag1", "a", "opencode", 9999, "/tmp", "available", ts),
    ))
    _run(execute(
        """INSERT INTO tasks (id, project_id, title, description, status, priority, archived,
           is_new, created_at, updated_at, assigned_agent_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("t1", "p1", "T", "D", "completed", 0, 0, 0, ts, ts, "ag1"),
    ))
    _run(execute(
        """INSERT INTO sessions (id, project_id, task_id, agent_id, status, started_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("ses_1", "p1", "t1", "ag1", "completed", ts),
    ))


def test_sync_reopens_completed_task_when_busy() -> None:
    _seed_completed_task_with_session()

    mock_resp_status = MagicMock()
    mock_resp_status.status_code = 200
    mock_resp_status.json = lambda: {"ses_1": {"type": "busy"}}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_resp_status)

    with patch("opencode_orchestrator.session_sync.httpx.AsyncClient", return_value=mock_client):
        _run(sync_opencode_session_tasks_once())

    row = _run(fetch_one("SELECT status, completed_at FROM tasks WHERE id = ?", ("t1",)))
    assert row is not None
    assert row["status"] == "running"
    assert row["completed_at"] is None

    srow = _run(fetch_one("SELECT status, ended_at FROM sessions WHERE id = ?", ("ses_1",)))
    assert srow is not None
    assert srow["status"] == "running"
    assert srow["ended_at"] is None


def test_sync_completes_running_task_when_idle_with_summary() -> None:
    ts = now()
    _run(execute(
        "INSERT INTO projects (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("p2", "Test2", "/tmp/p2", ts, ts),
    ))
    _run(execute(
        """INSERT INTO agent_registry (id, name, command, port, cwd, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("ag2", "b", "opencode", 9998, "/tmp", "available", ts),
    ))
    _run(execute(
        """INSERT INTO tasks (id, project_id, title, description, status, priority, archived,
           is_new, created_at, updated_at, assigned_agent_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("t2", "p2", "T2", "D2", "running", 0, 0, 0, ts, ts, "ag2"),
    ))
    _run(execute(
        """INSERT INTO sessions (id, project_id, task_id, agent_id, status, started_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("ses_2", "p2", "t2", "ag2", "running", ts),
    ))

    async def fake_get(url: str, **_kwargs: object) -> MagicMock:
        r = MagicMock()
        if url.endswith("/session/status"):
            r.status_code = 200
            r.json = lambda: {"ses_2": {"type": "idle"}}
        elif "/session/ses_2" in url:
            r.status_code = 200
            r.json = lambda: {
                "id": "ses_2",
                "summary": {"files": 1, "additions": 0, "deletions": 0},
            }
        else:
            r.status_code = 404
            r.json = lambda: {}
        return r

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(side_effect=fake_get)

    with patch("opencode_orchestrator.session_sync.httpx.AsyncClient", return_value=mock_client):
        _run(sync_opencode_session_tasks_once())

    row = _run(fetch_one("SELECT status, completed_at FROM tasks WHERE id = ?", ("t2",)))
    assert row is not None
    assert row["status"] == "completed"
    assert row["completed_at"] is not None


def test_sync_skips_waiting_tasks() -> None:
    ts = now()
    _run(execute(
        "INSERT INTO projects (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("p3", "Test3", "/tmp/p3", ts, ts),
    ))
    _run(execute(
        """INSERT INTO agent_registry (id, name, command, port, cwd, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("ag3", "c", "opencode", 9997, "/tmp", "available", ts),
    ))
    _run(execute(
        """INSERT INTO tasks (id, project_id, title, description, status, priority, archived,
           is_new, created_at, updated_at, assigned_agent_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("t3", "p3", "T3", "D3", "waiting", 0, 0, 0, ts, ts, "ag3"),
    ))
    _run(execute(
        """INSERT INTO sessions (id, project_id, task_id, agent_id, status, started_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("ses_3", "p3", "t3", "ag3", "running", ts),
    ))

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock()

    with patch("opencode_orchestrator.session_sync.httpx.AsyncClient", return_value=mock_client):
        _run(sync_opencode_session_tasks_once())

    mock_client.get.assert_not_called()
    row = _run(fetch_one("SELECT status FROM tasks WHERE id = ?", ("t3",)))
    assert row is not None
    assert row["status"] == "waiting"


def test_import_session_history_skips_duplicate_user_messages(tmp_path) -> None:
    ts = now()
    _run(execute(
        "INSERT INTO projects (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("p4", "Test4", "/tmp/p4", ts, ts),
    ))
    _run(execute(
        """INSERT INTO tasks (id, project_id, title, description, status, priority, archived,
           is_new, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("t4", "p4", "T4", "D4", "running", 0, 0, 0, ts, ts),
    ))

    # Existing local user message from orchestrator send path.
    _run(execute(
        """INSERT INTO task_messages (id, task_id, role, content, source, timestamp)
           VALUES (?, ?, 'user', ?, 'orchestrator', ?)""",
        ("m_local", "t4", "duplicate me", "2026-03-30T12:19:01.687147+00:00"),
    ))

    opencode_db = tmp_path / "opencode.db"
    conn = sqlite3.connect(opencode_db)
    conn.execute(
        """
        CREATE TABLE message (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL,
            data TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE part (
            id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL,
            data TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?)",
        (
            "msg_user",
            "ses_sync",
            1774873142703,
            1774873142703,
            json.dumps({"role": "user"}),
        ),
    )
    conn.execute(
        "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "prt_user",
            "msg_user",
            "ses_sync",
            1774873142703,
            1774873142703,
            json.dumps({"type": "text", "text": "duplicate me"}),
        ),
    )
    conn.execute(
        "INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?)",
        (
            "msg_assistant",
            "ses_sync",
            1774873142708,
            1774873142708,
            json.dumps({"role": "assistant"}),
        ),
    )
    conn.execute(
        "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "prt_assistant",
            "msg_assistant",
            "ses_sync",
            1774873142708,
            1774873142708,
            json.dumps({"type": "text", "text": "assistant reply"}),
        ),
    )
    conn.commit()
    conn.close()

    _run(_import_session_history("t4", "ses_sync", str(opencode_db)))

    count_user = _run(fetch_one(
        "SELECT COUNT(*) AS cnt FROM task_messages WHERE task_id = ? AND role = 'user' AND content = ?",
        ("t4", "duplicate me"),
    ))
    assert count_user is not None
    assert count_user["cnt"] == 1

    assistant_row = _run(fetch_one(
        "SELECT role, content, source FROM task_messages WHERE task_id = ? AND role = 'assistant'",
        ("t4",),
    ))
    assert assistant_row is not None
    assert assistant_row["source"] == "opencode_sqlite"
    assert assistant_row["content"] == "assistant reply"


def test_import_session_history_backfills_when_cursor_message_missing(tmp_path) -> None:
    ts = now()
    _run(execute(
        "INSERT INTO projects (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("p5", "Test5", "/tmp/p5", ts, ts),
    ))
    _run(execute(
        """INSERT INTO tasks (id, project_id, title, description, status, priority, archived,
           is_new, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("t5", "p5", "T5", "D5", "running", 0, 0, 0, ts, ts),
    ))
    _run(execute(
        """
        INSERT INTO opencode_sync_cursor (session_id, last_time_created, last_message_id, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        ("ses_backfill", 1774873562780, "msg_assistant_error", ts),
    ))

    opencode_db = tmp_path / "opencode.db"
    conn = sqlite3.connect(opencode_db)
    conn.execute(
        """
        CREATE TABLE message (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL,
            data TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE part (
            id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL,
            data TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?)",
        (
            "msg_assistant_error",
            "ses_backfill",
            1774873562780,
            1774873563025,
            json.dumps(
                {
                    "role": "assistant",
                    "error": {
                        "name": "APIError",
                        "data": {"message": "Invalid API Key", "statusCode": 401},
                    },
                }
            ),
        ),
    )
    conn.commit()
    conn.close()

    _run(_import_session_history("t5", "ses_backfill", str(opencode_db)))

    row = _run(fetch_one(
        "SELECT role, source, content, opencode_message_id FROM task_messages WHERE task_id = ?",
        ("t5",),
    ))
    assert row is not None
    assert row["role"] == "assistant"
    assert row["source"] == "opencode_sqlite"
    assert row["opencode_message_id"] == "msg_assistant_error"
    assert "Invalid API Key" in row["content"]


def test_background_send_does_not_store_assistant_text_directly() -> None:
    """Assistant text should come from sqlite sync, not stream-parsing writes."""
    ts = now()
    _run(execute(
        "INSERT INTO projects (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("p6", "Test6", "/tmp/p6", ts, ts),
    ))
    _run(execute(
        """INSERT INTO tasks (id, project_id, title, description, status, priority, archived,
           is_new, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("t6", "p6", "T6", "D6", "running", 0, 0, 0, ts, ts),
    ))

    payload = json.dumps({"parts": [{"type": "text", "text": "Hello from agent"}]}).encode()

    class _MockStreamResponse:
        status_code = 200

        async def aiter_bytes(self):
            yield payload

    class _MockStreamContext:
        def __init__(self, response):
            self._response = response

        async def __aenter__(self):
            return self._response

        async def __aexit__(self, exc_type, exc, tb):
            return None

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.stream = MagicMock(return_value=_MockStreamContext(_MockStreamResponse()))

    with patch("httpx.AsyncClient", return_value=mock_client):
        _run(send_task_to_agent_background("p6", "t6", "ses_6", "hello", 9999))

    row = _run(fetch_one(
        "SELECT COUNT(*) AS cnt FROM task_messages WHERE task_id = ? AND role = 'assistant' AND source = 'orchestrator'",
        ("t6",),
    ))
    assert row is not None
    assert row["cnt"] == 0

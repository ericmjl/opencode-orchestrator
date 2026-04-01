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
from opencode_orchestrator.session_sync import _event_payload_should_trigger_sync
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


def test_sync_skips_completed_tasks() -> None:
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

    mock_client.get.assert_not_called()
    row = _run(fetch_one("SELECT status, completed_at FROM tasks WHERE id = ?", ("t1",)))
    assert row is not None
    assert row["status"] == "completed"

    srow = _run(fetch_one("SELECT status, ended_at FROM sessions WHERE id = ?", ("ses_1",)))
    assert srow is not None
    assert srow["status"] == "completed"


def test_event_payload_filter_ignores_server_connected() -> None:
    raw = json.dumps({"payload": {"type": "server.connected", "properties": {}}})
    assert _event_payload_should_trigger_sync(raw) is False


def test_event_payload_filter_triggers_on_non_connect_events() -> None:
    raw = json.dumps({"payload": {"type": "message.part.updated", "properties": {}}})
    assert _event_payload_should_trigger_sync(raw) is True


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


def test_sync_does_not_complete_when_user_turn_is_still_pending() -> None:
    ts = now()
    _run(execute(
        "INSERT INTO projects (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("p2b", "Test2b", "/tmp/p2b", ts, ts),
    ))
    _run(execute(
        """INSERT INTO agent_registry (id, name, command, port, cwd, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("ag2b", "bb", "opencode", 9996, "/tmp", "available", ts),
    ))
    _run(execute(
        """INSERT INTO tasks (id, project_id, title, description, status, priority, archived,
           is_new, created_at, updated_at, assigned_agent_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("t2b", "p2b", "T2b", "D2b", "running", 0, 0, 0, ts, ts, "ag2b"),
    ))
    _run(execute(
        """INSERT INTO sessions (id, project_id, task_id, agent_id, status, started_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("ses_2b", "p2b", "t2b", "ag2b", "running", ts),
    ))
    _run(execute(
        """INSERT INTO task_messages (id, task_id, role, content, source, timestamp)
           VALUES (?, ?, 'user', ?, 'orchestrator', ?)""",
        ("m2b-user", "t2b", "follow-up", "2026-04-01T00:10:00+00:00"),
    ))

    async def fake_get(url: str, **_kwargs: object) -> MagicMock:
        r = MagicMock()
        if url.endswith("/session/status"):
            r.status_code = 200
            r.json = lambda: {"ses_2b": {"type": "idle"}}
        elif "/session/ses_2b" in url:
            r.status_code = 200
            r.json = lambda: {
                "id": "ses_2b",
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

    row = _run(fetch_one("SELECT status FROM tasks WHERE id = ?", ("t2b",)))
    assert row is not None
    assert row["status"] == "running"

    srow = _run(fetch_one("SELECT status FROM sessions WHERE id = ?", ("ses_2b",)))
    assert srow is not None
    assert srow["status"] == "running"


def test_sync_is_single_flight_under_concurrent_triggers(monkeypatch) -> None:
    ts = now()
    _run(execute(
        "INSERT INTO projects (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("p_sf", "TestSF", "/tmp/p_sf", ts, ts),
    ))
    _run(execute(
        """INSERT INTO agent_registry (id, name, command, port, cwd, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("ag_sf", "sf", "opencode", 9995, "/tmp", "available", ts),
    ))
    _run(execute(
        """INSERT INTO tasks (id, project_id, title, description, status, priority, archived,
           is_new, created_at, updated_at, assigned_agent_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("t_sf", "p_sf", "TSF", "DSF", "running", 0, 0, 0, ts, ts, "ag_sf"),
    ))
    _run(execute(
        """INSERT INTO sessions (id, project_id, task_id, agent_id, status, started_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("ses_sf", "p_sf", "t_sf", "ag_sf", "running", ts),
    ))

    status_calls = 0

    async def _status_map(_client, _port: int):
        nonlocal status_calls
        status_calls += 1
        await asyncio.sleep(0.05)
        return {"ses_sf": {"type": "idle"}}

    async def _pending_permissions(_client, _port: int):
        return []

    async def _pending_questions(_client, _port: int):
        return []

    async def _path_info(_client, _port: int):
        return None

    async def _session_json(_client, _port: int, _session_id: str):
        return {"id": "ses_sf"}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr("opencode_orchestrator.session_sync.fetch_session_status_map", _status_map)
    monkeypatch.setattr(
        "opencode_orchestrator.session_sync.fetch_pending_permissions", _pending_permissions
    )
    monkeypatch.setattr("opencode_orchestrator.session_sync.fetch_pending_questions", _pending_questions)
    monkeypatch.setattr("opencode_orchestrator.session_sync.fetch_path_info", _path_info)
    monkeypatch.setattr("opencode_orchestrator.session_sync.fetch_session_json", _session_json)
    monkeypatch.setattr(
        "opencode_orchestrator.session_sync.httpx.AsyncClient", lambda *args, **kwargs: mock_client
    )

    async def _run_pair() -> None:
        await asyncio.gather(sync_opencode_session_tasks_once(), sync_opencode_session_tasks_once())

    _run(_run_pair())
    assert status_calls == 1


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

    _run(_import_session_history("p4", "t4", "ses_sync", str(opencode_db)))

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

    _run(_import_session_history("p5", "t5", "ses_backfill", str(opencode_db)))

    row = _run(fetch_one(
        "SELECT role, source, content, opencode_message_id FROM task_messages WHERE task_id = ?",
        ("t5",),
    ))
    assert row is not None
    assert row["role"] == "assistant"
    assert row["source"] == "opencode_sqlite"
    assert row["opencode_message_id"] == "msg_assistant_error"
    assert "Invalid API Key" in row["content"]


def test_import_session_history_does_not_publish_without_new_rows(tmp_path) -> None:
    """Realtime updates should emit only when new messages are inserted."""
    ts = now()
    _run(execute(
        "INSERT INTO projects (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("p7", "Test7", "/tmp/p7", ts, ts),
    ))
    _run(execute(
        """INSERT INTO tasks (id, project_id, title, description, status, priority, archived,
           is_new, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("t7", "p7", "T7", "D7", "running", 0, 0, 0, ts, ts),
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
            "msg_a1",
            "ses_publish_once",
            1774873142708,
            1774873142708,
            json.dumps({"role": "assistant"}),
        ),
    )
    conn.execute(
        "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "prt_a1",
            "msg_a1",
            "ses_publish_once",
            1774873142708,
            1774873142708,
            json.dumps({"type": "text", "text": "assistant once"}),
        ),
    )
    conn.commit()
    conn.close()

    with patch("opencode_orchestrator.session_sync._publish_task_updated", new_callable=AsyncMock) as mock_publish:
        _run(_import_session_history("p7", "t7", "ses_publish_once", str(opencode_db)))
        _run(_import_session_history("p7", "t7", "ses_publish_once", str(opencode_db)))

    assert mock_publish.await_count == 1


def test_import_session_history_does_not_truncate_long_assistant_messages(tmp_path) -> None:
    """Long assistant messages should be stored fully, without 10k truncation."""
    ts = now()
    _run(execute(
        "INSERT INTO projects (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("p8", "Test8", "/tmp/p8", ts, ts),
    ))
    _run(execute(
        """INSERT INTO tasks (id, project_id, title, description, status, priority, archived,
           is_new, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("t8", "p8", "T8", "D8", "running", 0, 0, 0, ts, ts),
    ))

    long_text = "A" * 12050
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
            "msg_long_1",
            "ses_long_1",
            1774873142708,
            1774873142708,
            json.dumps({"role": "assistant"}),
        ),
    )
    conn.execute(
        "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "prt_long_1",
            "msg_long_1",
            "ses_long_1",
            1774873142708,
            1774873142708,
            json.dumps({"type": "text", "text": long_text}),
        ),
    )
    conn.commit()
    conn.close()

    _run(_import_session_history("p8", "t8", "ses_long_1", str(opencode_db)))

    row = _run(fetch_one(
        "SELECT content FROM task_messages WHERE task_id = ? ORDER BY timestamp DESC LIMIT 1",
        ("t8",),
    ))
    assert row is not None
    assert row["content"] == long_text
    assert len(row["content"]) == 12050


def test_import_session_history_repairs_legacy_truncated_rows(tmp_path) -> None:
    """Existing 10k-capped rows should be repaired from OpenCode sqlite."""
    ts = now()
    _run(execute(
        "INSERT INTO projects (id, name, path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("p9", "Test9", "/tmp/p9", ts, ts),
    ))
    _run(execute(
        """INSERT INTO tasks (id, project_id, title, description, status, priority, archived,
           is_new, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("t9", "p9", "T9", "D9", "running", 0, 0, 0, ts, ts),
    ))
    _run(execute(
        """INSERT INTO task_messages
           (id, task_id, role, content, source, opencode_message_id, timestamp)
           VALUES (?, ?, 'assistant', ?, 'opencode_sqlite', ?, ?)""",
        ("legacy-msg", "t9", "X" * 10000, "msg_fix_1", ts),
    ))
    _run(execute(
        """
        INSERT INTO opencode_sync_cursor (session_id, last_time_created, last_message_id, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        ("ses_fix_1", 1774873142708, "msg_fix_1", ts),
    ))

    full_text = "Y" * 12050
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
            "msg_fix_1",
            "ses_fix_1",
            1774873142708,
            1774873142708,
            json.dumps({"role": "assistant"}),
        ),
    )
    conn.execute(
        "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "prt_fix_1",
            "msg_fix_1",
            "ses_fix_1",
            1774873142708,
            1774873142708,
            json.dumps({"type": "text", "text": full_text}),
        ),
    )
    conn.commit()
    conn.close()

    _run(_import_session_history("p9", "t9", "ses_fix_1", str(opencode_db)))

    row = _run(fetch_one(
        "SELECT content FROM task_messages WHERE task_id = ? AND opencode_message_id = ?",
        ("t9", "msg_fix_1"),
    ))
    assert row is not None
    assert row["content"] == full_text
    assert len(row["content"]) == 12050


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

    mock_import_history = AsyncMock()
    mock_publish_updated = AsyncMock()
    with (
        patch("httpx.AsyncClient", return_value=mock_client),
        patch(
            "opencode_orchestrator.routers.tasks._import_latest_task_session_history",
            new=mock_import_history,
        ),
        patch(
            "opencode_orchestrator.routers.tasks.publish_task_updated",
            new=mock_publish_updated,
        ),
    ):
        _run(send_task_to_agent_background("p6", "t6", "ses_6", "hello", 9999))

    row = _run(fetch_one(
        "SELECT COUNT(*) AS cnt FROM task_messages WHERE task_id = ? AND role = 'assistant' AND source = 'orchestrator'",
        ("t6",),
    ))
    assert row is not None
    assert row["cnt"] == 0
    mock_import_history.assert_awaited_once_with("p6", "t6")
    mock_publish_updated.assert_awaited_once_with("p6", "t6")

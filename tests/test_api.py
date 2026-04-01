import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from opencode_orchestrator.models import execute, fetch_one, init_db


@pytest_asyncio.fixture(autouse=True)
async def setup_db(tmp_path, monkeypatch):
    """Isolate SQLite and disable the OpenCode background sync loop during tests."""
    monkeypatch.setenv("OC_DISABLE_BACKGROUND_SYNC", "1")
    from opencode_orchestrator.models import database

    db_path = tmp_path / "test.db"
    monkeypatch.setattr(database, "DATABASE_PATH", db_path)
    await init_db()


@pytest_asyncio.fixture
async def client():
    from opencode_orchestrator.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _seed_project(client: AsyncClient, tmp_path) -> str:
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    resp = await client.post(
        "/api/projects",
        json={"name": "Test Project", "path": str(project_dir)},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def test_create_task(client: AsyncClient, tmp_path):
    project_id = await _seed_project(client, tmp_path)

    resp = await client.post(
        f"/api/projects/{project_id}/tasks",
        json={"description": "Hello world task"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["description"] == "Hello world task"
    assert data["status"] in ("created", "running")


async def test_list_tasks(client: AsyncClient, tmp_path):
    project_id = await _seed_project(client, tmp_path)

    await client.post(
        f"/api/projects/{project_id}/tasks",
        json={"description": "Task one"},
    )
    await client.post(
        f"/api/projects/{project_id}/tasks",
        json={"description": "Task two"},
    )

    resp = await client.get(f"/api/projects/{project_id}/tasks")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_get_messages(client: AsyncClient, tmp_path):
    project_id = await _seed_project(client, tmp_path)

    resp = await client.post(
        f"/api/projects/{project_id}/tasks",
        json={"description": "Msg test"},
    )
    task_id = resp.json()["id"]

    resp = await client.get(f"/api/projects/{project_id}/tasks/{task_id}/messages")
    assert resp.status_code == 200
    assert "messages" in resp.json()


async def test_task_stream_endpoint_returns_sse(client: AsyncClient, tmp_path):
    project_id = await _seed_project(client, tmp_path)
    resp = await client.post(
        f"/api/projects/{project_id}/tasks",
        json={"description": "Stream test"},
    )
    task_id = resp.json()["id"]

    async with client.stream(
        "GET",
        f"/api/projects/{project_id}/tasks/{task_id}/stream?bootstrap_only=1",
    ) as stream_resp:
        assert stream_resp.status_code == 200
        assert stream_resp.headers["content-type"].startswith("text/event-stream")
        line = await anext(stream_resp.aiter_lines())
        assert line == "event: task-updated"


async def test_project_board_stream_endpoint_returns_sse(client: AsyncClient, tmp_path):
    project_id = await _seed_project(client, tmp_path)

    async with client.stream(
        "GET",
        f"/api/projects/{project_id}/tasks/board-stream?bootstrap_only=1",
    ) as stream_resp:
        assert stream_resp.status_code == 200
        assert stream_resp.headers["content-type"].startswith("text/event-stream")
        line = await anext(stream_resp.aiter_lines())
        assert line == "event: project-updated"


async def test_send_message_no_agent(client: AsyncClient, tmp_path):
    project_id = await _seed_project(client, tmp_path)

    resp = await client.post(
        f"/api/projects/{project_id}/tasks",
        json={"description": "Chat task"},
    )
    task_id = resp.json()["id"]

    resp = await client.post(
        f"/api/projects/{project_id}/tasks/{task_id}/send-message",
        json={"message": "Hello agent"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_create_task_stays_created_when_project_bootstrap_unavailable(
    client: AsyncClient, tmp_path, monkeypatch
):
    project_id = await _seed_project(client, tmp_path)

    async def _no_bootstrap(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "opencode_orchestrator.routers.tasks._bootstrap_project_pinned_agent",
        _no_bootstrap,
    )

    resp = await client.post(
        f"/api/projects/{project_id}/tasks",
        json={"description": "Bootstrap unavailable should remain created"},
    )
    assert resp.status_code == 201
    payload = resp.json()
    assert payload["status"] == "created"
    assert payload["assigned_agent_id"] is None

    session_count = await fetch_one(
        "SELECT COUNT(*) AS count FROM sessions WHERE task_id = ?",
        (payload["id"],),
    )
    assert session_count is not None
    assert session_count["count"] == 0


async def test_run_task_uses_project_pinned_agent_bootstrap(
    client: AsyncClient, tmp_path, monkeypatch
):
    project_id = await _seed_project(client, tmp_path)
    task_id = "task-run-bootstrap"
    timestamp = "2026-03-31T12:00:00+00:00"
    project_path = str(tmp_path / "my-project")

    await execute(
        """INSERT INTO tasks (id, project_id, worktree_id, title, description, status, priority, created_at, updated_at)
           VALUES (?, ?, NULL, ?, ?, 'created', 0, ?, ?)""",
        (
            task_id,
            project_id,
            "Run task bootstrap",
            "Run task bootstrap description",
            timestamp,
            timestamp,
        ),
    )
    await execute(
        """INSERT INTO agent_registry (id, name, command, port, cwd, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
        (
            "ag-run-bootstrap",
            "run-bootstrap-agent",
            "opencode",
            4994,
            project_path,
            "available",
        ),
    )

    async def _bootstrap(_project_id: str, _project_path: str):
        return {"id": "ag-run-bootstrap", "port": 4994}

    async def _path_info(_client, _port: int):
        return {"directory": project_path}

    async def _noop_background(*_args, **_kwargs):
        return None

    async def _noop_publish(*_args, **_kwargs):
        return None

    class _Resp:
        def __init__(self, status_code: int, payload: dict | None = None):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = ""

        def json(self):
            return self._payload

    class _FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, json: dict | None = None):
            if url.endswith("/session"):
                return _Resp(200, {"id": "ses_run_bootstrap"})
            return _Resp(200, {})

    monkeypatch.setattr(
        "opencode_orchestrator.routers.tasks._bootstrap_project_pinned_agent", _bootstrap
    )
    monkeypatch.setattr("opencode_orchestrator.routers.tasks.fetch_path_info", _path_info)
    monkeypatch.setattr(
        "opencode_orchestrator.routers.tasks.send_task_to_agent_background", _noop_background
    )
    monkeypatch.setattr("opencode_orchestrator.routers.tasks.publish_task_updated", _noop_publish)
    monkeypatch.setattr(
        "opencode_orchestrator.routers.tasks.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeAsyncClient(),
    )

    resp = await client.post(f"/api/projects/{project_id}/tasks/{task_id}/run")
    assert resp.status_code == 200
    assert resp.json()["status"] == "started"
    assert resp.json()["session_id"] == "ses_run_bootstrap"

    task_row = await fetch_one(
        "SELECT status, assigned_agent_id FROM tasks WHERE id = ?",
        (task_id,),
    )
    assert task_row is not None
    assert task_row["status"] == "running"
    assert task_row["assigned_agent_id"] == "ag-run-bootstrap"

    session_row = await fetch_one(
        "SELECT id, status, agent_id FROM sessions WHERE task_id = ?",
        (task_id,),
    )
    assert session_row is not None
    assert session_row["id"] == "ses_run_bootstrap"
    assert session_row["status"] == "running"
    assert session_row["agent_id"] == "ag-run-bootstrap"


async def test_send_message_reuses_latest_session_even_if_locally_completed(
    client: AsyncClient, tmp_path, monkeypatch
):
    project_id = await _seed_project(client, tmp_path)
    create_resp = await client.post(
        f"/api/projects/{project_id}/tasks",
        json={"description": "Reuse completed local session"},
    )
    assert create_resp.status_code == 201
    task_id = create_resp.json()["id"]
    await execute("DELETE FROM sessions WHERE task_id = ?", (task_id,))

    await execute(
        """INSERT INTO agent_registry (id, name, command, port, cwd, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
        ("ag-rotate", "rotate-agent", "opencode", 4999, str(tmp_path), "available"),
    )
    await execute(
        "UPDATE tasks SET status = 'running', assigned_agent_id = ? WHERE id = ?",
        ("ag-rotate", task_id),
    )
    await execute(
        """INSERT INTO sessions (id, project_id, task_id, agent_id, status, started_at)
           VALUES (?, ?, ?, ?, 'completed', datetime('now'))""",
        ("ses_old", project_id, task_id, "ag-rotate"),
    )

    async def _alive(_session_id: str, _port: int) -> bool:
        return True

    async def _noop_background(*_args, **_kwargs):
        return None

    monkeypatch.setattr("opencode_orchestrator.routers.tasks.probe_agent_session", _alive)
    monkeypatch.setattr(
        "opencode_orchestrator.routers.tasks.send_task_to_agent_background", _noop_background
    )

    resp = await client.post(
        f"/api/projects/{project_id}/tasks/{task_id}/send-message",
        json={"message": "follow-up please"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    old_session = await fetch_one("SELECT status FROM sessions WHERE id = ?", ("ses_old",))
    assert old_session is not None
    assert old_session["status"] == "running"

    latest_session = await fetch_one(
        "SELECT id, status FROM sessions WHERE task_id = ? ORDER BY started_at DESC LIMIT 1",
        (task_id,),
    )
    assert latest_session is not None
    assert latest_session["id"] == "ses_old"
    assert latest_session["status"] == "running"

    task_row = await fetch_one("SELECT status FROM tasks WHERE id = ?", (task_id,))
    assert task_row is not None
    assert task_row["status"] == "running"


async def test_send_message_rejects_when_agent_directory_mismatch(
    client: AsyncClient, tmp_path, monkeypatch
):
    project_id = await _seed_project(client, tmp_path)
    create_resp = await client.post(
        f"/api/projects/{project_id}/tasks",
        json={"description": "Rotate on cwd mismatch"},
    )
    assert create_resp.status_code == 201
    task_id = create_resp.json()["id"]
    await execute("DELETE FROM sessions WHERE task_id = ?", (task_id,))

    await execute(
        """INSERT INTO agent_registry (id, name, command, port, cwd, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
        ("ag-mismatch", "mismatch-agent", "opencode", 4998, str(tmp_path), "available"),
    )
    await execute(
        "UPDATE tasks SET status = 'running', assigned_agent_id = ? WHERE id = ?",
        ("ag-mismatch", task_id),
    )
    await execute(
        """INSERT INTO sessions (id, project_id, task_id, agent_id, status, started_at)
           VALUES (?, ?, ?, ?, 'running', datetime('now'))""",
        ("ses_old_mismatch", project_id, task_id, "ag-mismatch"),
    )

    async def _alive(_session_id: str, _port: int) -> bool:
        return True

    async def _path_info(_client, _port: int):
        return {"directory": "/Users/ericmjl/Documents/brain42"}

    async def _noop_background(*_args, **_kwargs):
        return None

    class _Resp:
        def __init__(self, status_code: int, payload: dict | None = None):
            self.status_code = status_code
            self._payload = payload or {}

        def json(self):
            return self._payload

    class _FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, json: dict | None = None):
            if url.endswith("/session"):
                return _Resp(200, {"id": "ses_new_mismatch"})
            return _Resp(200, {})

    monkeypatch.setattr("opencode_orchestrator.routers.tasks.probe_agent_session", _alive)
    monkeypatch.setattr("opencode_orchestrator.routers.tasks.fetch_path_info", _path_info)
    async def _no_bootstrap(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "opencode_orchestrator.routers.tasks._bootstrap_project_pinned_agent",
        _no_bootstrap,
    )
    monkeypatch.setattr(
        "opencode_orchestrator.routers.tasks.send_task_to_agent_background", _noop_background
    )
    monkeypatch.setattr(
        "opencode_orchestrator.routers.tasks.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeAsyncClient(),
    )

    resp = await client.post(
        f"/api/projects/{project_id}/tasks/{task_id}/send-message",
        json={"message": "pwd?"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "error"
    assert "project-pinned agent" in resp.json()["message"].lower()

    latest_session = await fetch_one(
        "SELECT id, status FROM sessions WHERE task_id = ? ORDER BY started_at DESC LIMIT 1",
        (task_id,),
    )
    assert latest_session is not None
    assert latest_session["id"] == "ses_old_mismatch"


async def test_send_message_bootstraps_project_pinned_agent_on_directory_mismatch(
    client: AsyncClient, tmp_path, monkeypatch
):
    project_id = await _seed_project(client, tmp_path)
    create_resp = await client.post(
        f"/api/projects/{project_id}/tasks",
        json={"description": "Bootstrap on cwd mismatch"},
    )
    assert create_resp.status_code == 201
    task_id = create_resp.json()["id"]
    await execute("DELETE FROM sessions WHERE task_id = ?", (task_id,))

    await execute(
        """INSERT INTO agent_registry (id, name, command, port, cwd, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
        ("ag-mismatch-2", "mismatch-agent-2", "opencode", 4996, str(tmp_path), "available"),
    )
    await execute(
        "UPDATE tasks SET status = 'running', assigned_agent_id = ? WHERE id = ?",
        ("ag-mismatch-2", task_id),
    )
    await execute(
        """INSERT INTO sessions (id, project_id, task_id, agent_id, status, started_at)
           VALUES (?, ?, ?, ?, 'running', datetime('now'))""",
        ("ses_old_bootstrap", project_id, task_id, "ag-mismatch-2"),
    )

    async def _alive(_session_id: str, _port: int) -> bool:
        return True

    async def _path_info(_client, port: int):
        if port == 4996:
            return {"directory": "/Users/ericmjl/Documents/brain42"}
        return {"directory": str(tmp_path / "my-project")}

    async def _bootstrap(_project_id: str, _project_path: str):
        return {"id": "ag-bootstrap", "port": 4995}

    async def _noop_background(*_args, **_kwargs):
        return None

    class _Resp:
        def __init__(self, status_code: int, payload: dict | None = None):
            self.status_code = status_code
            self._payload = payload or {}

        def json(self):
            return self._payload

    class _FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, json: dict | None = None):
            if url.endswith("/session"):
                return _Resp(200, {"id": "ses_bootstrapped"})
            return _Resp(200, {})

    monkeypatch.setattr("opencode_orchestrator.routers.tasks.probe_agent_session", _alive)
    monkeypatch.setattr("opencode_orchestrator.routers.tasks.fetch_path_info", _path_info)
    monkeypatch.setattr(
        "opencode_orchestrator.routers.tasks._bootstrap_project_pinned_agent", _bootstrap
    )
    monkeypatch.setattr(
        "opencode_orchestrator.routers.tasks.send_task_to_agent_background", _noop_background
    )
    monkeypatch.setattr(
        "opencode_orchestrator.routers.tasks.httpx.AsyncClient",
        lambda *args, **kwargs: _FakeAsyncClient(),
    )

    resp = await client.post(
        f"/api/projects/{project_id}/tasks/{task_id}/send-message",
        json={"message": "pwd?"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    latest_session = await fetch_one(
        "SELECT id, status FROM sessions WHERE task_id = ? ORDER BY started_at DESC LIMIT 1",
        (task_id,),
    )
    assert latest_session is not None
    assert latest_session["id"] == "ses_bootstrapped"
    assert latest_session["status"] == "running"


async def test_send_message_form_ignores_sync_failure(client: AsyncClient, tmp_path, monkeypatch):
    project_id = await _seed_project(client, tmp_path)
    create_resp = await client.post(
        f"/api/projects/{project_id}/tasks",
        json={"description": "Form send test"},
    )
    assert create_resp.status_code == 201
    task_id = create_resp.json()["id"]

    async def _ok_send(_project_id: str, _task_id: str, _payload: dict):
        return {"status": "ok"}

    async def _boom_sync(**_kwargs):
        raise RuntimeError("sync failed")

    monkeypatch.setattr("opencode_orchestrator.routers.tasks.send_task_message_v2", _ok_send)
    monkeypatch.setattr("opencode_orchestrator.session_sync.enqueue_sync_nudge", _boom_sync)

    resp = await client.post(
        f"/api/projects/{project_id}/tasks/{task_id}/send-message-form",
        data={"message": "hi"},
    )
    assert resp.status_code == 200
    assert "task-messages" in resp.text


async def test_messages_fragment_renders_assistant_markdown_safely(client: AsyncClient, tmp_path):
    project_id = await _seed_project(client, tmp_path)
    create_resp = await client.post(
        f"/api/projects/{project_id}/tasks",
        json={"description": "Markdown render test"},
    )
    assert create_resp.status_code == 201
    task_id = create_resp.json()["id"]

    await execute(
        """INSERT INTO task_messages (id, task_id, role, content, source, timestamp)
           VALUES (?, ?, 'assistant', ?, 'opencode_sqlite', datetime('now'))""",
        (
            "msg-md-safe",
            task_id,
            "Please click [here](https://example.com)\\n\\n<script>alert(1)</script>",
        ),
    )

    resp = await client.get(f"/api/projects/{project_id}/tasks/{task_id}/messages-fragment")
    assert resp.status_code == 200
    assert '<a href="https://example.com">here</a>' in resp.text
    assert "<script>" not in resp.text
    assert "alert(1)" in resp.text


async def test_messages_fragment_attempts_legacy_repair_for_10k_rows(
    client: AsyncClient, tmp_path, monkeypatch
):
    project_id = await _seed_project(client, tmp_path)
    create_resp = await client.post(
        f"/api/projects/{project_id}/tasks",
        json={"description": "Legacy repair test"},
    )
    assert create_resp.status_code == 201
    task_id = create_resp.json()["id"]

    await execute(
        """INSERT INTO task_messages (id, task_id, role, content, source, timestamp)
           VALUES (?, ?, 'assistant', ?, 'opencode_sqlite', datetime('now'))""",
        ("msg-legacy-10k", task_id, "X" * 10000),
    )

    async def _repair(_project_id: str, _task_id: str) -> None:
        await execute(
            "UPDATE task_messages SET content = ? WHERE id = ?",
            ("Y" * 12050, "msg-legacy-10k"),
        )

    monkeypatch.setattr(
        "opencode_orchestrator.routers.tasks._repair_legacy_truncated_task_messages",
        _repair,
    )

    resp = await client.get(f"/api/projects/{project_id}/tasks/{task_id}/messages-fragment")
    assert resp.status_code == 200
    assert "Show full response (12050 chars)" in resp.text


async def test_messages_fragment_backfills_when_user_turn_newer_than_assistant(
    client: AsyncClient, tmp_path, monkeypatch
):
    project_id = await _seed_project(client, tmp_path)
    create_resp = await client.post(
        f"/api/projects/{project_id}/tasks",
        json={"description": "Staleness backfill test"},
    )
    assert create_resp.status_code == 201
    task_id = create_resp.json()["id"]

    await execute(
        """INSERT INTO task_messages (id, task_id, role, content, source, timestamp)
           VALUES (?, ?, 'assistant', ?, 'opencode_sqlite', '2026-04-01T00:00:00+00:00')""",
        ("msg-old-assistant", task_id, "Older assistant response"),
    )
    await execute(
        """INSERT INTO task_messages (id, task_id, role, content, source, timestamp)
           VALUES (?, ?, 'user', ?, 'orchestrator', '2026-04-01T00:01:00+00:00')""",
        ("msg-new-user", task_id, "follow up please"),
    )

    async def _backfill(_project_id: str, _task_id: str) -> None:
        await execute(
            """INSERT INTO task_messages (id, task_id, role, content, source, timestamp)
               VALUES (?, ?, 'assistant', ?, 'opencode_sqlite', '2026-04-01T00:01:01+00:00')""",
            ("msg-backfilled-assistant", task_id, "Here is the missing reply"),
        )

    monkeypatch.setattr(
        "opencode_orchestrator.routers.tasks._import_latest_task_session_history",
        _backfill,
    )

    resp = await client.get(f"/api/projects/{project_id}/tasks/{task_id}/messages-fragment")
    assert resp.status_code == 200
    assert "Here is the missing reply" in resp.text


async def test_delete_task(client: AsyncClient, tmp_path):
    project_id = await _seed_project(client, tmp_path)

    resp = await client.post(
        f"/api/projects/{project_id}/tasks",
        json={"description": "To delete"},
    )
    task_id = resp.json()["id"]

    resp = await client.delete(f"/api/projects/{project_id}/tasks/{task_id}")
    assert resp.status_code == 204

    resp = await client.get(f"/api/projects/{project_id}/tasks")
    assert len(resp.json()) == 0


async def test_now_uses_utc():
    from opencode_orchestrator.models import now

    ts = now()
    assert "+00:00" in ts or ts.endswith("Z")


async def test_unread_count_excludes_archived_tasks(client: AsyncClient, tmp_path):
    """Badges count only non-archived unread tasks."""
    project_id = await _seed_project(client, tmp_path)
    resp = await client.post(
        f"/api/projects/{project_id}/tasks",
        json={"description": "Unread completed"},
    )
    task_id = resp.json()["id"]
    await execute(
        "UPDATE tasks SET status = 'completed', is_new = 1, archived = 0 WHERE id = ?",
        (task_id,),
    )
    resp = await client.get(f"/api/projects/{project_id}")
    assert resp.status_code == 200
    assert resp.json()["unread_count"] == 1

    await execute(
        "UPDATE tasks SET archived = 1 WHERE id = ?",
        (task_id,),
    )
    resp = await client.get(f"/api/projects/{project_id}")
    assert resp.json()["unread_count"] == 0


async def test_archive_task_clears_is_new(client: AsyncClient, tmp_path):
    """Archiving marks the task as read so unread badges stay consistent."""
    project_id = await _seed_project(client, tmp_path)
    resp = await client.post(
        f"/api/projects/{project_id}/tasks",
        json={"description": "To archive"},
    )
    task_id = resp.json()["id"]
    await execute(
        "UPDATE tasks SET status = 'completed', is_new = 1, archived = 0 WHERE id = ?",
        (task_id,),
    )

    resp = await client.delete(f"/api/projects/{project_id}/tasks/{task_id}/archive")
    assert resp.status_code == 200

    row = await fetch_one("SELECT is_new, archived FROM tasks WHERE id = ?", (task_id,))
    assert row is not None
    assert row["is_new"] == 0
    assert row["archived"] == 1

    resp = await client.get(f"/api/projects/{project_id}")
    assert resp.json()["unread_count"] == 0


async def test_model_options_fragment_uses_discovered_models(client: AsyncClient, tmp_path, monkeypatch):
    project_id = await _seed_project(client, tmp_path)

    async def _fake_models():
        return [
            {"id": "openai/gpt-5.4", "name": "GPT 5.4", "provider": "openai"},
            {"id": "anthropic/claude-sonnet-4.5", "name": "Claude Sonnet 4.5", "provider": "anthropic"},
        ]

    monkeypatch.setattr("opencode_orchestrator.routers.tasks.get_available_models", _fake_models)
    resp = await client.get(f"/api/projects/{project_id}/tasks/model-options-fragment")
    assert resp.status_code == 200
    body = resp.text
    assert 'name="model"' in body
    assert 'value="openai/gpt-5.4"' in body
    assert "Claude Sonnet 4.5" in body

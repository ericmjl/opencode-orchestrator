import os
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from opencode_orchestrator.models import init_db


@pytest_asyncio.fixture(autouse=True)
async def setup_db(tmp_path, monkeypatch):
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
    assert resp.json()["status"] == "error"


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

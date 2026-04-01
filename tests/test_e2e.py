"""
End-to-end tests for OpenCode Orchestrator using Playwright.

These tests verify that critical UI functionality works correctly in a real browser.

Prerequisites:
- Server must be running (start with: pixi run start)
- Set ORCHESTRATOR_URL env var (e.g., http://127.0.0.1:8418)
"""

import pytest
import time
import os
import httpx
from pathlib import Path

pytestmark = pytest.mark.e2e


def get_server_url():
    """Get the server URL - check env var ORCHESTRATOR_URL."""
    return os.environ.get("ORCHESTRATOR_URL", "http://127.0.0.1:8418")


def ensure_project_id(server_url: str) -> str:
    """Return an existing project id, creating one for this repo if needed."""
    existing = httpx.get(f"{server_url}/api/projects", timeout=10)
    if existing.status_code == 200 and existing.json():
        return existing.json()[0]["id"]

    repo_path = str(Path(__file__).parent.parent.resolve())
    created = httpx.post(
        f"{server_url}/api/projects",
        json={"path": repo_path, "name": "opencode-orchestrator"},
        timeout=10,
    )
    created.raise_for_status()
    return created.json()["id"]


def test_create_task_with_enter_key(page):
    """Test that pressing Enter creates a task - regression test for Enter key handler."""
    server_url = get_server_url()
    ensure_project_id(server_url)
    page.goto(f"{server_url}/projects")
    page.wait_for_load_state("domcontentloaded")

    project_link = page.locator('a[href^="/projects/"]').first
    project_href = project_link.get_attribute("href")

    page.goto(f"{server_url}{project_href}")
    page.wait_for_load_state("domcontentloaded")

    task_input = page.locator("#task-description")
    task_input.fill(f"test enter {int(time.time())}")
    task_input.press("Enter")

    time.sleep(3)

    assert page.locator(".task-title", has_text="test enter").count() > 0


def test_create_task_with_button(page):
    """Test that clicking Create button creates a task."""
    server_url = get_server_url()
    ensure_project_id(server_url)
    page.goto(f"{server_url}/projects")
    page.wait_for_load_state("domcontentloaded")

    project_link = page.locator('a[href^="/projects/"]').first
    project_href = project_link.get_attribute("href")

    page.goto(f"{server_url}{project_href}")
    page.wait_for_load_state("domcontentloaded")

    task_input = page.locator("#task-description")
    task_input.fill(f"test button {int(time.time())}")
    page.locator("#create-task-form button").click()

    time.sleep(3)
    assert page.locator(".task-title", has_text="test button").count() > 0


def test_create_task_launches_agent():
    """Test that task creation actually launches the agent."""
    server_url = get_server_url()

    import httpx

    project_id = ensure_project_id(server_url)

    task_desc = f"say hi {int(time.time())}"
    resp = httpx.post(
        f"{server_url}/api/projects/{project_id}/tasks", json={"description": task_desc}, timeout=15
    )
    assert resp.status_code == 201
    task_data = resp.json()
    assert task_data["status"] in {"running", "created"}

    if task_data["status"] == "running":
        time.sleep(5)
        messages_resp = httpx.get(
            f"{server_url}/api/projects/{project_id}/tasks/{task_data['id']}/messages", timeout=10
        )
        messages = messages_resp.json()["messages"]
        assert len(messages) >= 1


def test_task_board_has_three_columns(page):
    """Test that all three task columns (Running, Completed, Failed) are visible after HTMX poll."""
    server_url = get_server_url()
    project_id = ensure_project_id(server_url)

    page.goto(f"{server_url}/projects/{project_id}")
    page.wait_for_load_state("domcontentloaded")

    # Wait for HTMX poll to complete (poll interval is 3s, add buffer)
    time.sleep(4)

    # Check that all three column headers exist
    columns = page.locator(".task-column h3").all_text_contents()

    assert "Running" in columns, "Running column must be present"
    assert any("Completed" in col for col in columns), "Completed column must be present"
    assert "Failed" in columns, "Failed column must be present"

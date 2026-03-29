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


def get_server_url():
    """Get the server URL - check env var ORCHESTRATOR_URL."""
    return os.environ.get("ORCHESTRATOR_URL", "http://127.0.0.1:8418")


def test_create_task_with_enter_key(page):
    """Test that pressing Enter creates a task - regression test for Enter key handler."""
    server_url = get_server_url()
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

    task_text = page.locator(".task-title").first.text_content()
    assert "test enter" in task_text


def test_create_task_with_button(page):
    """Test that clicking Create button creates a task."""
    server_url = get_server_url()
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
    task_text = page.locator(".task-title").first.text_content()
    assert "test button" in task_text


def test_create_task_launches_agent():
    """Test that task creation actually launches the agent."""
    server_url = get_server_url()

    import httpx

    resp = httpx.get(f"{server_url}/projects")

    project_id = "2e89b646-ed1c-45a2-b120-b2ecbaa711b1"  # Hardcoded for now

    task_desc = f"say hi {int(time.time())}"
    resp = httpx.post(
        f"{server_url}/api/projects/{project_id}/tasks", json={"description": task_desc}, timeout=15
    )
    assert resp.status_code == 201
    task_data = resp.json()
    assert task_data["status"] == "running"

    time.sleep(5)

    messages_resp = httpx.get(
        f"{server_url}/api/projects/{project_id}/tasks/{task_data['id']}/messages", timeout=10
    )
    messages = messages_resp.json()["messages"]
    assert len(messages) >= 2

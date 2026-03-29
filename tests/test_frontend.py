"""
Frontend regression tests for OpenCode Orchestrator.

These tests verify that critical UI functionality works correctly
by checking the templates directly.
"""

import re
from pathlib import Path


def test_project_detail_has_enter_key_handler():
    """Test that the project detail template has Enter key handler for task creation."""
    template_path = (
        Path(__file__).parent.parent
        / "opencode_orchestrator"
        / "templates"
        / "pages"
        / "project-detail.html"
    )
    content = template_path.read_text()

    assert "onkeydown=\"if(event.key==='Enter')" in content, (
        "Create task input must have Enter key handler"
    )
    assert "createTask()" in content, "Create task must call createTask() on Enter"


def test_task_detail_has_sse_stream():
    """Test that the task detail template has SSE stream endpoint."""
    template_path = (
        Path(__file__).parent.parent
        / "opencode_orchestrator"
        / "templates"
        / "pages"
        / "task-detail.html"
    )
    content = template_path.read_text()

    assert "EventSource" in content, "Task detail must use EventSource for SSE"
    assert "/stream" in content, "Task detail must connect to stream endpoint"


def test_create_task_triggers_agent():
    """Test that task creation actually sends task to agent."""
    tasks_router_path = (
        Path(__file__).parent.parent / "opencode_orchestrator" / "routers" / "tasks.py"
    )
    content = tasks_router_path.read_text()

    assert "send_task_to_agent_background" in content, (
        "Task creation must trigger background agent task"
    )
    assert "message_resp = await client.post" in content, (
        "Task creation must send message to agent session"
    )
    assert "task_messages" in content, "Task creation must store messages in database"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])

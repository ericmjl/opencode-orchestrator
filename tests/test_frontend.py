"""
Frontend regression tests for OpenCode Orchestrator.

These tests verify that critical UI functionality works correctly
by checking the templates directly.
"""

import re
from pathlib import Path


def test_project_detail_uses_htmx_task_create_form():
    """Task creation should be HTMX-mediated through form submission."""
    template_path = (
        Path(__file__).parent.parent
        / "opencode_orchestrator"
        / "templates"
        / "pages"
        / "project-detail.html"
    )
    content = template_path.read_text()

    assert 'hx-post="/api/projects/{{ project.id }}/tasks/create-form"' in content
    assert 'hx-target="#task-board"' in content
    assert 'hx-get="/api/projects/{{ project.id }}/tasks/model-options-fragment"' in content
    assert 'id="task-model-picker"' in content
    assert "style=\"display:inline-block;\"" not in content
    assert 'const LAST_MODEL_KEY = "oc:lastTaskModel"' in content
    assert 'localStorage.setItem(LAST_MODEL_KEY, select.value);' in content
    assert 'if (target && target.id === "task-model-picker")' in content
    assert "function renderPendingTaskCard()" in content
    assert "form.addEventListener(\"htmx:beforeRequest\"" in content
    assert "button.textContent = isBusy ? \"Creating...\" : \"Create\";" in content
    assert 'Loading task board...' not in content
    assert "onsubmit" not in content
    assert 'hx-ext="sse"' in content
    assert 'sse-connect="/api/projects/{{ project.id }}/tasks/board-stream"' in content
    assert 'hx-trigger="load, sse:project-updated"' in content


def test_task_detail_has_reactive_status_updates_via_sse():
    """Task detail should reactively refresh status via EventSource events."""
    template_path = (
        Path(__file__).parent.parent
        / "opencode_orchestrator"
        / "templates"
        / "pages"
        / "task-detail.html"
    )
    content = template_path.read_text()

    assert 'hx-get="/api/projects/{{ project.id }}/tasks/{{ task.id }}/status-fragment"' in content
    assert 'hx-trigger="load"' in content
    assert "task-status-badge" in content, "Task detail must have a stable badge id"
    assert 'data-events-url="/api/projects/{{ project.id }}/tasks/{{ task.id }}/stream"' in content
    assert 'id="task-detail-live-root"' in content
    assert "function connectTaskEvents()" in content
    assert "new EventSource(eventsUrl)" in content
    assert 'events.addEventListener("task-status"' in content
    assert "pollSessionStatus" not in content


def test_task_detail_uses_sse_for_messages_and_keeps_live_session_link():
    """Task detail should refresh message fragments from reactive events and expose live session link."""
    template_path = (
        Path(__file__).parent.parent
        / "opencode_orchestrator"
        / "templates"
        / "pages"
        / "task-detail.html"
    )
    content = template_path.read_text()

    assert 'hx-get="/api/projects/{{ project.id }}/tasks/{{ task.id }}/messages-fragment"' in content
    assert 'hx-trigger="load"' in content
    assert "Open Live Session" in content or "live session" in content.lower(), (
        "Task detail should link to live session"
    )
    assert 'id="task-send-message-form"' in content
    assert 'hx-sync="#task-send-message-form:abort"' in content
    assert "function maybeFinalizePendingSend(form)" in content
    assert "function clearPendingSendState(form)" in content
    assert 'id="task-back-to-project-link"' in content
    assert "function bindBackLinkFallback()" in content
    assert 'id="task-prompts-region"' in content
    assert 'events.addEventListener("task-messages"' in content
    assert 'events.addEventListener("task-prompts"' in content
    assert "button.textContent = isBusy ? \"Sending...\" : \"Send\";" in content
    assert "form.addEventListener(\"htmx:beforeRequest\"" in content
    assert 'class="info-section task-messages-scroll"' in content
    assert "every 2s" not in content


def test_task_messages_escape_html_content() -> None:
    """Task message partial should render pre-sanitized HTML payloads."""
    partial_path = (
        Path(__file__).parent.parent
        / "opencode_orchestrator"
        / "templates"
        / "partials"
        / "task-messages.html"
    )
    content = partial_path.read_text()
    assert "{{ message.content_html | safe }}" in content


def test_long_assistant_messages_are_expandable() -> None:
    """Long assistant messages should be collapsed behind an expand control."""
    partial_path = (
        Path(__file__).parent.parent
        / "opencode_orchestrator"
        / "templates"
        / "partials"
        / "task-messages.html"
    )
    content = partial_path.read_text()
    assert "is_long_assistant" in content
    assert '<details class="message-expandable">' in content
    assert 'class="message-expandable-summary"' in content
    assert "Show full response" in content


def test_create_task_triggers_agent():
    """Test that task creation actually sends task to agent."""
    tasks_router_path = (
        Path(__file__).parent.parent / "opencode_orchestrator" / "routers" / "tasks.py"
    )
    content = tasks_router_path.read_text()

    assert "send_task_to_agent_background" in content, (
        "Task creation must trigger background agent task"
    )
    assert "client.stream(" in content, "Task creation must stream the agent message response"
    assert "task_messages" in content, "Task creation must store messages in database"


def test_task_board_partial_has_all_three_columns():
    """Test that the task board partial includes Running, Completed, and Failed columns."""
    partial_path = (
        Path(__file__).parent.parent
        / "opencode_orchestrator"
        / "templates"
        / "partials"
        / "task-board.html"
    )
    content = partial_path.read_text()

    assert '<div class="task-column">' in content, "Task board partial must have task-column divs"
    assert "<h3>Running</h3>" in content, "Task board partial must have Running column"
    assert "<h3>Completed" in content, "Task board partial must have Completed column"
    assert "<h3>Failed</h3>" in content, "Task board partial must have Failed column"
    assert 'hx-target="#task-board"' in content, "Archive action should re-render board"
    assert 'hx-swap="innerHTML"' in content, "Archive action should refresh empty states"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])

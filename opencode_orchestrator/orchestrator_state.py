"""Task/session state machine utilities for orchestrator v2."""

from __future__ import annotations

import uuid

from opencode_orchestrator.models import get_db, now

ALLOWED_TASK_TRANSITIONS: dict[str, set[str]] = {
    "created": {"running", "cancelled", "failed"},
    "running": {"waiting_question", "waiting_permission", "completed", "failed", "cancelled"},
    "waiting_question": {"running", "completed", "failed", "cancelled"},
    "waiting_permission": {"running", "completed", "failed", "cancelled"},
    "completed": {"running"},
    "failed": {"running", "cancelled"},
    "cancelled": {"running"},
}


async def transition_task_status(task_id: str, to_status: str, reason: str) -> None:
    """Apply a guarded state transition and append a task log entry.

    :param task_id: Task identifier.
    :param to_status: Target task status.
    :param reason: Human-readable reason for transition.
    """
    timestamp = now()
    async for db in get_db():
        task_row = await db.execute("SELECT status FROM tasks WHERE id = ?", (task_id,))
        row = await task_row.fetchone()
        if not row:
            return

        from_status = row["status"]
        if from_status == to_status:
            return

        allowed = ALLOWED_TASK_TRANSITIONS.get(from_status, set())
        if to_status not in allowed:
            return

        completed_at = timestamp if to_status == "completed" else None
        await db.execute(
            "UPDATE tasks SET status = ?, updated_at = ?, completed_at = COALESCE(?, completed_at) WHERE id = ?",
            (to_status, timestamp, completed_at, task_id),
        )
        await db.execute(
            """
            INSERT INTO task_logs (id, task_id, event, from_status, to_status, details, timestamp)
            VALUES (?, ?, 'state_transition', ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), task_id, from_status, to_status, reason, timestamp),
        )
        await db.commit()

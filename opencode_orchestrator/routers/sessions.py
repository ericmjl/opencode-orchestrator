
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from opencode_orchestrator.models import get_db, row_to_dict, now

router = APIRouter()


class SessionResponse(BaseModel):
    id: str
    project_id: str
    worktree_id: str | None
    task_id: str
    agent_id: str
    status: str
    pid: int | None
    started_at: str
    ended_at: str | None
    output_log_path: str | None
    exit_code: int | None
    error_message: str | None


@router.get("/{project_id}/sessions", response_model=list[SessionResponse])
async def list_sessions(project_id: str, status: str | None = None):
    async for db in get_db():
        query = "SELECT * FROM sessions WHERE project_id = ?"
        params = [project_id]

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY started_at DESC"

        rows = await db.execute(query, params)
        sessions = [row_to_dict(row) for row in await rows.fetchall()]

        return [
            SessionResponse(
                id=s["id"],
                project_id=s["project_id"],
                worktree_id=s["worktree_id"],
                task_id=s["task_id"],
                agent_id=s["agent_id"],
                status=s["status"],
                pid=s["pid"],
                started_at=s["started_at"],
                ended_at=s["ended_at"],
                output_log_path=s["output_log_path"],
                exit_code=s["exit_code"],
                error_message=s["error_message"],
            )
            for s in sessions
        ]


@router.get("/{project_id}/sessions/{session_id}", response_model=SessionResponse)
async def get_session(project_id: str, session_id: str):
    async for db in get_db():
        row = await db.execute(
            "SELECT * FROM sessions WHERE id = ? AND project_id = ?", (session_id, project_id)
        )
        session = await row.fetchone()
        if not session:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
        s = row_to_dict(session)
        return SessionResponse(
            id=s["id"],
            project_id=s["project_id"],
            worktree_id=s["worktree_id"],
            task_id=s["task_id"],
            agent_id=s["agent_id"],
            status=s["status"],
            pid=s["pid"],
            started_at=s["started_at"],
            ended_at=s["ended_at"],
            output_log_path=s["output_log_path"],
            exit_code=s["exit_code"],
            error_message=s["error_message"],
        )


@router.post("/{project_id}/sessions/{session_id}/cancel", response_model=SessionResponse)
async def cancel_session(project_id: str, session_id: str):
    async for db in get_db():
        row = await db.execute(
            "SELECT * FROM sessions WHERE id = ? AND project_id = ?", (session_id, project_id)
        )
        session = await row.fetchone()
        if not session:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
        s = row_to_dict(session)

        if s["status"] not in ("spawned", "running"):
            raise HTTPException(status_code=409, detail=f"Session '{session_id}' is not running")

        timestamp = now()

        if s["pid"]:
            import os
            import signal

            try:
                os.kill(s["pid"], signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass

        await db.execute(
            "UPDATE sessions SET status = 'stopping', ended_at = ? WHERE id = ?",
            (timestamp, session_id),
        )
        await db.commit()

        row = await db.execute(
            "SELECT * FROM sessions WHERE id = ? AND project_id = ?", (session_id, project_id)
        )
        session = await row.fetchone()
        s = row_to_dict(session)

    return SessionResponse(
        id=s["id"],
        project_id=s["project_id"],
        worktree_id=s["worktree_id"],
        task_id=s["task_id"],
        agent_id=s["agent_id"],
        status=s["status"],
        pid=s["pid"],
        started_at=s["started_at"],
        ended_at=s["ended_at"],
        output_log_path=s["output_log_path"],
        exit_code=s["exit_code"],
        error_message=s["error_message"],
    )

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from opencode_orchestrator.models import fetch_one, fetch_all, execute, now

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
    query = "SELECT * FROM sessions WHERE project_id = ?"
    params = [project_id]

    if status:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY started_at DESC"

    sessions = await fetch_all(query, tuple(params))

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
    session = await fetch_one(
        "SELECT * FROM sessions WHERE id = ? AND project_id = ?", (session_id, project_id)
    )
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return SessionResponse(
        id=session["id"],
        project_id=session["project_id"],
        worktree_id=session["worktree_id"],
        task_id=session["task_id"],
        agent_id=session["agent_id"],
        status=session["status"],
        pid=session["pid"],
        started_at=session["started_at"],
        ended_at=session["ended_at"],
        output_log_path=session["output_log_path"],
        exit_code=session["exit_code"],
        error_message=session["error_message"],
    )


@router.post("/{project_id}/sessions/{session_id}/cancel", response_model=SessionResponse)
async def cancel_session(project_id: str, session_id: str):
    session = await fetch_one(
        "SELECT * FROM sessions WHERE id = ? AND project_id = ?", (session_id, project_id)
    )
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    if session["status"] not in ("spawned", "running"):
        raise HTTPException(status_code=409, detail=f"Session '{session_id}' is not running")

    timestamp = now()

    if session["pid"]:
        import os
        import signal

        try:
            os.kill(session["pid"], signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    await execute(
        "UPDATE sessions SET status = 'stopping', ended_at = ? WHERE id = ?",
        (timestamp, session_id),
    )

    session = await fetch_one(
        "SELECT * FROM sessions WHERE id = ? AND project_id = ?", (session_id, project_id)
    )

    return SessionResponse(
        id=session["id"],
        project_id=session["project_id"],
        worktree_id=session["worktree_id"],
        task_id=session["task_id"],
        agent_id=session["agent_id"],
        status=session["status"],
        pid=session["pid"],
        started_at=session["started_at"],
        ended_at=session["ended_at"],
        output_log_path=session["output_log_path"],
        exit_code=session["exit_code"],
        error_message=session["error_message"],
    )

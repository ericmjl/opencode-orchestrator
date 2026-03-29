import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from opencode_orchestrator.models import get_db, row_to_dict, now

router = APIRouter()


class WorktreeCreate(BaseModel):
    branch_name: str
    base_ref: str | None = None


class WorktreeResponse(BaseModel):
    id: str
    project_id: str
    branch_name: str
    path: str
    status: str
    created_at: str


@router.get("/{project_id}/worktrees", response_model=list[WorktreeResponse])
async def list_worktrees(project_id: str):
    async for db in get_db():
        rows = await db.execute(
            "SELECT * FROM worktrees WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        )
        worktrees = [row_to_dict(row) for row in await rows.fetchall()]

        return [
            WorktreeResponse(
                id=w["id"],
                project_id=w["project_id"],
                branch_name=w["branch_name"],
                path=w["path"],
                status=w["status"],
                created_at=w["created_at"],
            )
            for w in worktrees
        ]


@router.post("/{project_id}/worktrees", status_code=201, response_model=WorktreeResponse)
async def create_worktree(project_id: str, data: WorktreeCreate):
    async for db in get_db():
        row = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
        project = await row.fetchone()
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
        p = row_to_dict(project)

        if not p["has_git"]:
            raise HTTPException(
                status_code=409, detail="Cannot create worktrees for non-git projects"
            )

        worktree_path = Path(p["path"]) / ".opencode" / "worktrees" / data.branch_name

        if worktree_path.exists():
            raise HTTPException(
                status_code=409, detail=f"Worktree path '{worktree_path}' already exists"
            )

        import subprocess

        cmd = ["git", "worktree", "add", str(worktree_path)]
        if data.base_ref:
            cmd.extend(["-b", data.branch_name, data.base_ref])
        else:
            cmd.append(p["default_branch"] or "main")

        try:
            result = subprocess.run(
                cmd,
                cwd=p["path"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                raise HTTPException(
                    status_code=500, detail=f"git worktree add failed: {result.stderr}"
                )
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=500, detail="git worktree add timed out")
        except FileNotFoundError:
            raise HTTPException(status_code=500, detail="git command not found")

        worktree_id = str(uuid.uuid4())
        timestamp = now()

        await db.execute(
            """INSERT INTO worktrees (id, project_id, branch_name, path, status, created_at)
               VALUES (?, ?, ?, ?, 'active', ?)""",
            (worktree_id, project_id, data.branch_name, str(worktree_path), timestamp),
        )
        await db.commit()

    return WorktreeResponse(
        id=worktree_id,
        project_id=project_id,
        branch_name=data.branch_name,
        path=str(worktree_path),
        status="active",
        created_at=timestamp,
    )


@router.delete("/{project_id}/worktrees/{worktree_id}", status_code=204)
async def delete_worktree(project_id: str, worktree_id: str):
    async for db in get_db():
        row = await db.execute(
            "SELECT * FROM worktrees WHERE id = ? AND project_id = ?", (worktree_id, project_id)
        )
        worktree = await row.fetchone()
        if not worktree:
            raise HTTPException(status_code=404, detail=f"Worktree '{worktree_id}' not found")
        w = row_to_dict(worktree)

        if w["status"] == "active":
            active_session = await db.execute(
                "SELECT id FROM sessions WHERE worktree_id = ? AND status IN ('spawned', 'running')",
                (worktree_id,),
            )
            if await active_session.fetchone():
                raise HTTPException(
                    status_code=409, detail=f"Worktree '{worktree_id}' has an active session"
                )

        import subprocess

        try:
            result = subprocess.run(
                ["git", "worktree", "remove", w["path"]],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                pass
        except Exception:
            pass

        await db.execute("UPDATE worktrees SET status = 'archived' WHERE id = ?", (worktree_id,))
        await db.commit()

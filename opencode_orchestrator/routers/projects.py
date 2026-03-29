import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from opencode_orchestrator.models import get_db, row_to_dict, now

router = APIRouter()


class ProjectCreate(BaseModel):
    path: str
    name: str | None = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    path: str
    has_git: bool
    vcs_url: str | None
    default_branch: str | None
    created_at: str
    updated_at: str


@router.get("", response_model=list[ProjectResponse])
async def list_projects():
    async for db in get_db():
        rows = await db.execute("SELECT * FROM projects ORDER BY created_at DESC")
        projects = [row_to_dict(row) for row in await rows.fetchall()]
        return [
            ProjectResponse(
                id=p["id"],
                name=p["name"],
                path=p["path"],
                has_git=bool(p["has_git"]),
                vcs_url=p["vcs_url"],
                default_branch=p["default_branch"],
                created_at=p["created_at"],
                updated_at=p["updated_at"],
            )
            for p in projects
        ]


@router.post("", status_code=201, response_model=ProjectResponse)
async def create_project(data: ProjectCreate):
    import json

    import os

    project_path_str = os.path.expanduser(data.path)
    project_path = Path(project_path_str).resolve()

    if not project_path.exists():
        raise HTTPException(status_code=400, detail=f"Path '{data.path}' does not exist")

    if not project_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Path '{data.path}' is not a directory")

    has_git = (project_path / ".git").exists()
    vcs_url = None
    default_branch = None

    if has_git:
        import subprocess

        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                vcs_url = result.stdout.strip()
        except Exception:
            pass

        try:
            result = subprocess.run(
                ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                default_branch = result.stdout.strip().split("/")[-1]
        except Exception:
            default_branch = "main"
    else:
        default_branch = None

    project_id = str(uuid.uuid4())
    project_name = data.name or project_path.name
    timestamp = now()

    async for db in get_db():
        existing = await db.execute("SELECT id FROM projects WHERE path = ?", (str(project_path),))
        if await existing.fetchone():
            raise HTTPException(
                status_code=409, detail=f"A project is already registered at '{data.path}'"
            )

        await db.execute(
            """INSERT INTO projects (id, name, path, has_git, vcs_url, default_branch, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project_id,
                project_name,
                str(project_path),
                int(has_git),
                vcs_url,
                default_branch,
                timestamp,
                timestamp,
            ),
        )
        await db.commit()

    return ProjectResponse(
        id=project_id,
        name=project_name,
        path=str(project_path),
        has_git=has_git,
        vcs_url=vcs_url,
        default_branch=default_branch,
        created_at=timestamp,
        updated_at=timestamp,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str):
    async for db in get_db():
        row = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
        project = await row.fetchone()
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
        p = row_to_dict(project)
        return ProjectResponse(
            id=p["id"],
            name=p["name"],
            path=p["path"],
            has_git=bool(p["has_git"]),
            vcs_url=p["vcs_url"],
            default_branch=p["default_branch"],
            created_at=p["created_at"],
            updated_at=p["updated_at"],
        )


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: str):
    async for db in get_db():
        result = await db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        await db.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")


@router.get("/{project_id}/status")
async def get_project_status(project_id: str):
    async for db in get_db():
        row = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
        project = await row.fetchone()
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

        p = row_to_dict(project)
        project_path = Path(p["path"])
        path_exists = project_path.exists()

        import subprocess

        current_branch = None
        repo_clean = None
        if p["has_git"] and path_exists:
            try:
                result = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=project_path,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    current_branch = result.stdout.strip()
            except Exception:
                pass

            try:
                result = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=project_path,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    repo_clean = len(result.stdout.strip()) == 0
            except Exception:
                pass

        active_sessions = await db.execute(
            "SELECT COUNT(*) as cnt FROM sessions WHERE project_id = ? AND status IN ('spawned', 'running')",
            (project_id,),
        )
        active_count = (await active_sessions.fetchone())["cnt"]

        pending_tasks = await db.execute(
            "SELECT COUNT(*) as cnt FROM tasks WHERE project_id = ? AND status NOT IN ('completed', 'failed', 'cancelled')",
            (project_id,),
        )
        pending_count = (await pending_tasks.fetchone())["cnt"]

        return {
            "id": project_id,
            "path_exists": path_exists,
            "has_git": bool(p["has_git"]),
            "repo_clean": repo_clean,
            "current_branch": current_branch,
            "active_sessions": active_count,
            "pending_tasks": pending_count,
            "last_activity": p["updated_at"],
        }

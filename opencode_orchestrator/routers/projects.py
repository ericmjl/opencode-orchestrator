import uuid
from pathlib import Path
import asyncio

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

from opencode_orchestrator.models import fetch_one, fetch_all, execute, now
from opencode_orchestrator.realtime import subscribe_project_updates

templates = Environment(loader=FileSystemLoader(Path(__file__).parent.parent / "templates"))

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
    unread_count: int
    created_at: str
    updated_at: str


async def _projects_with_unread() -> list[dict]:
    projects = await fetch_all("SELECT * FROM projects ORDER BY created_at DESC")
    result: list[dict] = []
    for p in projects:
        unread_row = await fetch_one(
            "SELECT COUNT(*) as cnt FROM tasks WHERE project_id = ? AND archived = 0 AND is_new = 1",
            (p["id"],),
        )
        project = dict(p)
        project["unread_count"] = unread_row["cnt"] if unread_row else 0
        result.append(project)
    return result


@router.get("", response_model=list[ProjectResponse])
async def list_projects():
    projects = await fetch_all("SELECT * FROM projects ORDER BY created_at DESC")
    result = []
    for p in projects:
        unread_row = await fetch_one(
            "SELECT COUNT(*) as cnt FROM tasks WHERE project_id = ? AND archived = 0 AND is_new = 1",
            (p["id"],),
        )
        unread_count = unread_row["cnt"] if unread_row else 0
        result.append(
            ProjectResponse(
                id=p["id"],
                name=p["name"],
                path=p["path"],
                has_git=bool(p["has_git"]),
                vcs_url=p["vcs_url"],
                default_branch=p["default_branch"],
                unread_count=unread_count,
                created_at=p["created_at"],
                updated_at=p["updated_at"],
            )
        )
    return result


@router.post("", status_code=201, response_model=ProjectResponse)
async def create_project(data: ProjectCreate):

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

    existing = await fetch_one("SELECT id FROM projects WHERE path = ?", (str(project_path),))
    if existing:
        raise HTTPException(
            status_code=409, detail=f"A project is already registered at '{data.path}'"
        )

    await execute(
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

    return ProjectResponse(
        id=project_id,
        name=project_name,
        path=str(project_path),
        has_git=has_git,
        vcs_url=vcs_url,
        default_branch=default_branch,
        unread_count=0,
        created_at=timestamp,
        updated_at=timestamp,
    )


@router.post("/form")
async def create_project_form(path: str = Form(...), name: str | None = Form(default=None)):
    await create_project(ProjectCreate(path=path, name=name))
    template = templates.get_template("partials/project-list.html")
    return HTMLResponse(content=template.render(projects=await _projects_with_unread()))


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str):
    project = await fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    unread_row = await fetch_one(
        "SELECT COUNT(*) as cnt FROM tasks WHERE project_id = ? AND archived = 0 AND is_new = 1",
        (project_id,),
    )
    unread_count = unread_row["cnt"] if unread_row else 0
    return ProjectResponse(
        id=project["id"],
        name=project["name"],
        path=project["path"],
        has_git=bool(project["has_git"]),
        vcs_url=project["vcs_url"],
        default_branch=project["default_branch"],
        unread_count=unread_count,
        created_at=project["created_at"],
        updated_at=project["updated_at"],
    )


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: str):
    result = await execute("DELETE FROM projects WHERE id = ?", (project_id,))
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")


@router.get("/{project_id}/status")
async def get_project_status(project_id: str):
    project = await fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    project_path = Path(project["path"])
    path_exists = project_path.exists()

    import subprocess

    current_branch = None
    repo_clean = None
    if project["has_git"] and path_exists:
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

    active_sessions = await fetch_one(
        "SELECT COUNT(*) as cnt FROM sessions WHERE project_id = ? AND status IN ('spawned', 'running')",
        (project_id,),
    )
    active_count = active_sessions["cnt"] if active_sessions else 0

    pending_tasks = await fetch_one(
        "SELECT COUNT(*) as cnt FROM tasks WHERE project_id = ? AND status NOT IN ('completed', 'failed', 'cancelled')",
        (project_id,),
    )
    pending_count = pending_tasks["cnt"] if pending_tasks else 0

    return {
        "id": project_id,
        "path_exists": path_exists,
        "has_git": bool(project["has_git"]),
        "repo_clean": repo_clean,
        "current_branch": current_branch,
        "active_sessions": active_count,
        "pending_tasks": pending_count,
        "last_activity": project["updated_at"],
    }


@router.get("/{project_id}/tasks/board")
async def get_task_board(project_id: str):
    project = await fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    running_tasks = await fetch_all(
        "SELECT * FROM tasks WHERE project_id = ? AND archived = 0 AND status IN ('running', 'waiting_question', 'waiting_permission') ORDER BY priority ASC, created_at ASC",
        (project_id,),
    )

    completed_tasks = await fetch_all(
        "SELECT * FROM tasks WHERE project_id = ? AND archived = 0 AND status = 'completed' ORDER BY updated_at DESC",
        (project_id,),
    )

    failed_tasks = await fetch_all(
        "SELECT * FROM tasks WHERE project_id = ? AND archived = 0 AND status = 'failed' ORDER BY updated_at DESC",
        (project_id,),
    )

    unread_row = await fetch_one(
        "SELECT COUNT(*) as cnt FROM tasks WHERE project_id = ? AND archived = 0 AND status = 'completed' AND is_new = 1",
        (project_id,),
    )
    completed_unread = unread_row["cnt"] if unread_row else 0
    sidebar_unread_row = await fetch_one(
        "SELECT COUNT(*) as cnt FROM tasks WHERE project_id = ? AND archived = 0 AND is_new = 1",
        (project_id,),
    )
    sidebar_unread = sidebar_unread_row["cnt"] if sidebar_unread_row else 0

    template = templates.get_template("partials/task-board.html")
    html = template.render(
        project=project,
        running_tasks=running_tasks,
        completed_tasks=completed_tasks,
        failed_tasks=failed_tasks,
        completed_unread=completed_unread,
        sidebar_unread=sidebar_unread,
    )
    return HTMLResponse(content=html)


@router.get("/{project_id}/tasks/board-stream")
async def get_task_board_stream(project_id: str, bootstrap_only: bool = False):
    project = await fetch_one("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    async def event_generator():
        yield "event: project-updated\ndata: 1\n\n"
        if bootstrap_only:
            return
        async with subscribe_project_updates(project_id) as queue:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield f"event: {event.name}\ndata: {event.data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                except asyncio.CancelledError:
                    break

    return StreamingResponse(event_generator(), media_type="text/event-stream")

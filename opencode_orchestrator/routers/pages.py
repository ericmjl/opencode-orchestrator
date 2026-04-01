import base64
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader
from opencode_orchestrator.models import get_db, row_to_dict
from opencode_orchestrator.routers.agents import get_available_models


def _opencode_slug(directory: str) -> str:
    return (
        base64.b64encode(directory.encode())
        .decode()
        .replace("+", "-")
        .replace("/", "_")
        .rstrip("=")
    )


templates = Environment(loader=FileSystemLoader(str(Path(__file__).parent.parent / "templates")))
templates.filters["opencode_slug"] = _opencode_slug

pages_router = APIRouter()


async def get_all_projects():
    async for db in get_db():
        rows = await db.execute("""
            SELECT p.*, 
                   (SELECT COUNT(*) FROM tasks t WHERE t.project_id = p.id AND t.archived = 0 AND t.is_new = 1) as unread_count
            FROM projects p 
            ORDER BY p.created_at DESC
        """)
        return [row_to_dict(row) for row in await rows.fetchall()]
    return []


async def render_template(template_name: str, request: Request, **kwargs):
    projects = await get_all_projects()

    kwargs["projects"] = projects
    kwargs["request"] = request

    template = templates.get_template(template_name)
    html = template.render(**kwargs)
    return HTMLResponse(content=html)


@pages_router.get("/projects")
async def projects_page(request: Request) -> HTMLResponse:
    async for db in get_db():
        rows = await db.execute("""
            SELECT p.*, 
                   (SELECT COUNT(*) FROM tasks t WHERE t.project_id = p.id AND t.archived = 0 AND t.is_new = 1) as unread_count
            FROM projects p 
            ORDER BY p.created_at DESC
        """)
        projects = [row_to_dict(row) for row in await rows.fetchall()]
        break

    return await render_template("pages/projects.html", request, projects=projects)


@pages_router.get("/projects/{project_id}")
async def project_detail_page(request: Request, project_id: str) -> HTMLResponse:
    async for db in get_db():
        proj = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
        project = await proj.fetchone()
        if not project:
            return HTMLResponse("Project not found", status_code=404)

        tasks_rows = await db.execute(
            "SELECT * FROM tasks WHERE project_id = ? AND archived = 0 ORDER BY priority ASC, created_at ASC",
            (project_id,),
        )
        tasks = [row_to_dict(row) for row in await tasks_rows.fetchall()]
        running_tasks = [
            t for t in tasks if t["status"] in ("running", "waiting_question", "waiting_permission")
        ]
        completed_tasks = [t for t in tasks if t["status"] == "completed"]
        failed_tasks = [t for t in tasks if t["status"] == "failed"]

        unread_rows = await db.execute(
            "SELECT COUNT(*) as cnt FROM tasks WHERE project_id = ? AND archived = 0 AND status = 'completed' AND is_new = 1",
            (project_id,),
        )
        completed_unread = (await unread_rows.fetchone())["cnt"] if unread_rows else 0
        sidebar_unread_rows = await db.execute(
            "SELECT COUNT(*) as cnt FROM tasks WHERE project_id = ? AND archived = 0 AND is_new = 1",
            (project_id,),
        )
        sidebar_unread = (await sidebar_unread_rows.fetchone())["cnt"] if sidebar_unread_rows else 0

        sessions_rows = await db.execute(
            "SELECT * FROM sessions WHERE project_id = ? ORDER BY started_at DESC LIMIT 10",
            (project_id,),
        )
        sessions = [row_to_dict(row) for row in await sessions_rows.fetchall()]

        agents_rows = await db.execute("SELECT * FROM agent_registry ORDER BY name ASC")
        agents = [row_to_dict(row) for row in await agents_rows.fetchall()]
        break

    try:
        task_models = await get_available_models()
    except Exception:
        task_models = []

    return await render_template(
        "pages/project-detail.html",
        request,
        project=row_to_dict(project),
        tasks=tasks,
        running_tasks=running_tasks,
        completed_tasks=completed_tasks,
        failed_tasks=failed_tasks,
        sessions=sessions,
        agents=agents,
        task_models=task_models,
        active_project_id=project_id,
        completed_unread=completed_unread,
        sidebar_unread=sidebar_unread,
    )


@pages_router.get("/projects/{project_id}/sessions")
async def sessions_page(request: Request, project_id: str) -> HTMLResponse:
    async for db in get_db():
        proj = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
        project = await proj.fetchone()
        if not project:
            return HTMLResponse("Project not found", status_code=404)

        sessions_rows = await db.execute(
            "SELECT * FROM sessions WHERE project_id = ? ORDER BY started_at DESC",
            (project_id,),
        )
        sessions = [row_to_dict(row) for row in await sessions_rows.fetchall()]

        agent_ids = {s["agent_id"] for s in sessions if s.get("agent_id")}
        agents = {}
        for aid in agent_ids:
            agent_row = await db.execute("SELECT * FROM agent_registry WHERE id = ?", (aid,))
            agent = await agent_row.fetchone()
            if agent:
                a = row_to_dict(agent)
                agents[a["id"]] = a
        break

    return await render_template(
        "pages/sessions.html",
        request,
        project=row_to_dict(project),
        sessions=sessions,
        agents=agents,
        active_project_id=project_id,
    )


@pages_router.get("/projects/{project_id}/tasks/{task_id}")
async def task_detail_page(request: Request, project_id: str, task_id: str) -> HTMLResponse:
    async for db in get_db():
        proj = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
        project = await proj.fetchone()
        if not project:
            return HTMLResponse("Project not found", status_code=404)

        task_row = await db.execute(
            "SELECT * FROM tasks WHERE id = ? AND project_id = ?", (task_id, project_id)
        )
        task = await task_row.fetchone()
        if not task:
            return HTMLResponse("Task not found", status_code=404)
        t = row_to_dict(task)

        session_row = await db.execute(
            "SELECT * FROM sessions WHERE task_id = ? ORDER BY started_at DESC LIMIT 1",
            (task_id,),
        )
        session = await session_row.fetchone()
        s = row_to_dict(session) if session else None

        agent = None
        if t.get("assigned_agent_id"):
            agent_row = await db.execute(
                "SELECT * FROM agent_registry WHERE id = ?", (t.get("assigned_agent_id"),)
            )
            agent = await agent_row.fetchone()
            a = row_to_dict(agent) if agent else None
        else:
            a = None

        msg_rows = await db.execute(
            "SELECT * FROM task_messages WHERE task_id = ? ORDER BY timestamp ASC",
            (task_id,),
        )
        session_messages = [row_to_dict(row) for row in await msg_rows.fetchall()]

    import json

    return await render_template(
        "pages/task-detail.html",
        request,
        project=row_to_dict(project),
        task=t,
        session=s,
        agent=a,
        messages=session_messages,
        messages_json=json.dumps(session_messages),
        active_project_id=project_id,
    )


@pages_router.get("/settings")
async def settings_page(request: Request) -> HTMLResponse:
    async for db in get_db():
        rows = await db.execute("SELECT * FROM agent_registry ORDER BY name ASC")
        agents = [row_to_dict(row) for row in await rows.fetchall()]
        break

    return await render_template("pages/settings.html", request, agents=agents)

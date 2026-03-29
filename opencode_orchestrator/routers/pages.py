import uuid
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader

templates = Environment(loader=FileSystemLoader(str(Path(__file__).parent.parent / "templates")))

pages_router = APIRouter()


@pages_router.get("/projects")
async def projects_page(request: Request) -> HTMLResponse:
    from opencode_orchestrator.models import get_db, row_to_dict

    async for db in get_db():
        rows = await db.execute("SELECT * FROM projects ORDER BY created_at DESC")
        projects = [row_to_dict(row) for row in await rows.fetchall()]
        break

    template = templates.get_template("pages/projects.html")
    html = template.render(request=request, projects=projects)
    return HTMLResponse(content=html)


@pages_router.get("/projects/{project_id}")
async def project_detail_page(request: Request, project_id: str) -> HTMLResponse:
    from opencode_orchestrator.models import get_db, row_to_dict

    async for db in get_db():
        proj = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
        project = await proj.fetchone()
        if not project:
            return HTMLResponse("Project not found", status_code=404)

        tasks_rows = await db.execute(
            "SELECT * FROM tasks WHERE project_id = ? ORDER BY priority ASC, created_at ASC",
            (project_id,),
        )
        tasks = [row_to_dict(row) for row in await tasks_rows.fetchall()]

        sessions_rows = await db.execute(
            "SELECT * FROM sessions WHERE project_id = ? ORDER BY started_at DESC LIMIT 10",
            (project_id,),
        )
        sessions = [row_to_dict(row) for row in await sessions_rows.fetchall()]

        agents_rows = await db.execute("SELECT * FROM agent_registry ORDER BY name ASC")
        agents = [row_to_dict(row) for row in await agents_rows.fetchall()]
        break

    template = templates.get_template("pages/project-detail.html")
    html = template.render(
        request=request,
        project=row_to_dict(project),
        tasks=tasks,
        sessions=sessions,
        agents=agents,
    )
    return HTMLResponse(content=html)


@pages_router.get("/projects/{project_id}/sessions")
async def sessions_page(request: Request, project_id: str) -> HTMLResponse:
    from opencode_orchestrator.models import get_db, row_to_dict

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
        break

    template = templates.get_template("pages/sessions.html")
    html = template.render(request=request, project=row_to_dict(project), sessions=sessions)
    return HTMLResponse(content=html)


@pages_router.get("/projects/{project_id}/tasks/{task_id}")
async def task_detail_page(request: Request, project_id: str, task_id: str) -> HTMLResponse:
    from opencode_orchestrator.models import get_db, row_to_dict
    import httpx

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
            "SELECT * FROM sessions WHERE task_id = ? AND status = 'running' ORDER BY started_at DESC LIMIT 1",
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

    template = templates.get_template("pages/task-detail.html")
    html = template.render(
        request=request,
        project=row_to_dict(project),
        task=t,
        session=s,
        agent=a,
        messages=session_messages,
        messages_json=json.dumps(session_messages),
    )
    return HTMLResponse(content=html)


@pages_router.get("/settings")
async def settings_page(request: Request) -> HTMLResponse:
    from opencode_orchestrator.models import get_db, row_to_dict

    async for db in get_db():
        rows = await db.execute("SELECT * FROM agent_registry ORDER BY name ASC")
        agents = [row_to_dict(row) for row in await rows.fetchall()]
        break

    template = templates.get_template("pages/settings.html")
    html = template.render(request=request, agents=agents)
    return HTMLResponse(content=html)

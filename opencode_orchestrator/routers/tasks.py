import uuid
import asyncio
import json
import logging
import os
import socket
from pathlib import Path

import bleach
import httpx
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from jinja2 import Environment, FileSystemLoader
from markupsafe import escape
from markdown_it import MarkdownIt
from pydantic import BaseModel

from opencode_orchestrator.models import get_db, row_to_dict, now
from opencode_orchestrator.opencode_client import fetch_path_info, httpx_auth_kw
from opencode_orchestrator.opencode_history import resolve_opencode_db_path
from opencode_orchestrator.orchestrator_state import transition_task_status
from opencode_orchestrator.realtime import TaskEvent, publish_project_updated, task_event_broker
from opencode_orchestrator.routers.agents import ensure_agent_running, get_available_models

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Environment(loader=FileSystemLoader(Path(__file__).parent.parent / "templates"))
_MESSAGE_SEMAPHORE = asyncio.Semaphore(int(os.environ.get("OC_MAX_CONCURRENT_TASKS", "4")))
_MARKDOWN = MarkdownIt("commonmark", {"html": False, "linkify": True, "breaks": True})
_ALLOWED_HTML_TAGS = [
    "p",
    "br",
    "pre",
    "code",
    "blockquote",
    "ul",
    "ol",
    "li",
    "em",
    "strong",
    "a",
]
_ALLOWED_HTML_ATTRS = {"a": ["href", "title", "target", "rel"]}
_ALLOWED_HTML_PROTOCOLS = ["http", "https", "mailto"]


def _render_message_content_html(role: str, content: str) -> str:
    """Render safe HTML for task messages."""
    if role != "assistant":
        return str(escape(content)).replace("\n", "<br>\n")
    rendered = _MARKDOWN.render(content)
    return bleach.clean(
        rendered,
        tags=_ALLOWED_HTML_TAGS,
        attributes=_ALLOWED_HTML_ATTRS,
        protocols=_ALLOWED_HTML_PROTOCOLS,
        strip=True,
    )


async def _repair_legacy_truncated_task_messages(project_id: str, task_id: str) -> None:
    """Best-effort repair of historic 10k-capped OpenCode sqlite messages."""
    await _import_latest_task_session_history(project_id, task_id)


async def _import_latest_task_session_history(project_id: str, task_id: str) -> None:
    """Best-effort import of latest session history for one task."""
    async for db in get_db():
        session_row = await db.execute(
            """
            SELECT s.id AS session_id, a.port
            FROM sessions s
            JOIN agent_registry a ON a.id = s.agent_id
            WHERE s.task_id = ? AND s.project_id = ?
            ORDER BY s.started_at DESC
            LIMIT 1
            """,
            (task_id, project_id),
        )
        session = await session_row.fetchone()
        break

    if not session:
        return
    session_id = str(session["session_id"])
    port = session["port"]
    if port is None:
        return

    db_path: str | None = None
    try:
        async with httpx.AsyncClient(**httpx_auth_kw()) as client:
            path_info = await fetch_path_info(client, int(port))
        resolved = resolve_opencode_db_path(path_info)
        if resolved:
            db_path = str(resolved)
    except Exception:
        logger.exception(
            "failed to resolve opencode sqlite path while repairing task=%s", task_id
        )
        return

    if not db_path:
        return

    from opencode_orchestrator.session_sync import _import_session_history

    await _import_session_history(project_id, task_id, session_id, db_path)


async def _task_history_appears_stale(task_id: str) -> bool:
    """Return True when a newer user message exists than imported assistant history."""
    async for db in get_db():
        recency_row = await db.execute(
            """
            SELECT
                (
                    SELECT MAX(timestamp)
                    FROM task_messages
                    WHERE task_id = ?
                      AND role = 'user'
                      AND source = 'orchestrator'
                ) AS latest_user_timestamp,
                (
                    SELECT MAX(timestamp)
                    FROM task_messages
                    WHERE task_id = ?
                      AND role = 'assistant'
                      AND source = 'opencode_sqlite'
                ) AS latest_assistant_timestamp
            """,
            (task_id, task_id),
        )
        recency = await recency_row.fetchone()
        break

    if not recency:
        return False

    latest_user = recency["latest_user_timestamp"]
    latest_assistant = recency["latest_assistant_timestamp"]
    if latest_user is None:
        return False
    if latest_assistant is None:
        return True
    return bool(str(latest_user) > str(latest_assistant))


def _render_sse_event(event: str, data: object = "1") -> str:
    if isinstance(data, str):
        payload = data
    else:
        payload = json.dumps(data)
    return f"event: {event}\ndata: {payload}\n\n"


async def publish_task_updated(project_id: str, task_id: str) -> None:
    """Notify task-detail stream subscribers with typed reactive events."""
    status = "unknown"
    async for db in get_db():
        status_row = await db.execute("SELECT status FROM tasks WHERE id = ?", (task_id,))
        task = await status_row.fetchone()
        status = task["status"] if task else "unknown"
        break
    await task_event_broker.publish(
        project_id, task_id, TaskEvent(name="task-status", data={"status": status})
    )
    await task_event_broker.publish(
        project_id, task_id, TaskEvent(name="task-messages", data={"taskId": task_id})
    )
    await task_event_broker.publish(
        project_id, task_id, TaskEvent(name="task-prompts", data={"taskId": task_id})
    )
    await task_event_broker.publish(
        project_id, task_id, TaskEvent(name="task-updated", data={"status": status})
    )
    await publish_project_updated(project_id)


async def _sync_task_after_send(project_id: str, task_id: str) -> None:
    """Perform bounded post-send sync nudges off the request path."""
    from opencode_orchestrator.session_sync import enqueue_sync_nudge

    try:
        await asyncio.wait_for(
            enqueue_sync_nudge(project_id=project_id, task_id=task_id, reason="post-send"),
            timeout=1.0,
        )
    except Exception:
        logger.exception(
            "post-send sync nudge failed for project=%s task=%s",
            project_id,
            task_id,
        )


async def update_agent_cwd(agent_id: str, project_id: str):
    async for db in get_db():
        proj = await db.execute("SELECT path FROM projects WHERE id = ?", (project_id,))
        proj_row = await proj.fetchone()
        if proj_row:
            await db.execute(
                "UPDATE agent_registry SET cwd = ? WHERE id = ?",
                (proj_row[0], agent_id),
            )
            await db.commit()


async def probe_agent_session(session_id: str, port: int) -> bool:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"http://127.0.0.1:{port}/session/{session_id}",
                timeout=httpx.Timeout(5.0),
            )
            return resp.status_code == 200
    except Exception:
        return False


def _normalize_dir(path: str) -> str:
    return str(Path(path).expanduser().resolve())


def _path_info_matches_project(path_info: dict | None, expected_project_path: str) -> bool:
    """Return True when OpenCode reports the expected working directory.

    If path info is unavailable, return True and let existing flow continue.
    """
    if not isinstance(path_info, dict):
        return True
    directory = path_info.get("directory")
    if not isinstance(directory, str) or not directory:
        return True
    return _normalize_dir(directory) == _normalize_dir(expected_project_path)


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return sock.connect_ex(("127.0.0.1", port)) != 0


async def _find_project_agent_port() -> int | None:
    """Find an available localhost port for a project-pinned agent."""
    start = int(os.environ.get("OC_AGENT_PORT_START", "4100"))
    end = int(os.environ.get("OC_AGENT_PORT_END", "4999"))
    used_ports: set[int] = set()
    async for db in get_db():
        rows = await db.execute("SELECT port FROM agent_registry")
        for row in await rows.fetchall():
            try:
                used_ports.add(int(row["port"]))
            except Exception:
                continue
        break
    for port in range(start, end + 1):
        if port in used_ports:
            continue
        if _port_is_free(port):
            return port
    return None


async def _bootstrap_project_pinned_agent(project_id: str, expected_project_path: str) -> dict | None:
    """Ensure there is a running agent rooted at the project path."""
    normalized_project_path = _normalize_dir(expected_project_path)

    async for db in get_db():
        rows = await db.execute(
            "SELECT * FROM agent_registry WHERE status IN ('available', 'starting', 'offline') ORDER BY created_at ASC"
        )
        candidates = [row_to_dict(r) for r in await rows.fetchall()]
        break

    for candidate in candidates:
        candidate_cwd = candidate.get("cwd")
        if not isinstance(candidate_cwd, str) or not candidate_cwd:
            continue
        if _normalize_dir(candidate_cwd) != normalized_project_path:
            continue
        ensured = await ensure_agent_running(candidate["id"])
        if not ensured:
            continue
        ensured_dict = dict(ensured)
        try:
            async with httpx.AsyncClient(**httpx_auth_kw()) as client:
                path_info = await fetch_path_info(client, int(ensured_dict["port"]))
            if _path_info_matches_project(path_info, expected_project_path):
                return ensured_dict
        except Exception:
            logger.exception(
                "Failed checking existing project-pinned agent %s for project %s",
                candidate["id"],
                project_id,
            )

    port = await _find_project_agent_port()
    if port is None:
        return None

    agent_id = str(uuid.uuid4())
    timestamp = now()
    agent_name = f"opencode-{project_id[:8]}-{port}"
    command = f"opencode serve --port {port}"
    async for db in get_db():
        await db.execute(
            """INSERT INTO agent_registry (id, name, command, port, cwd, capabilities, status, config, pid, last_seen, created_at)
               VALUES (?, ?, ?, ?, ?, NULL, 'offline', NULL, NULL, NULL, ?)""",
            (agent_id, agent_name, command, port, expected_project_path, timestamp),
        )
        await db.commit()
        break

    ensured = await ensure_agent_running(agent_id)
    if not ensured:
        return None
    ensured_dict = dict(ensured)
    try:
        async with httpx.AsyncClient(**httpx_auth_kw()) as client:
            path_info = await fetch_path_info(client, int(ensured_dict["port"]))
        if not _path_info_matches_project(path_info, expected_project_path):
            logger.error(
                "Bootstrapped agent %s did not start in expected project path (%s != %s)",
                agent_id,
                (path_info or {}).get("directory"),
                expected_project_path,
            )
            return None
    except Exception:
        logger.exception("Failed checking bootstrapped agent %s", agent_id)
        return None

    return ensured_dict


async def send_task_to_agent_background(
    project_id: str, task_id: str, agent_session_id: str, description: str, port: int
):
    logger.info(f"Starting background task for task {task_id}, agent session {agent_session_id}")

    await asyncio.sleep(1)

    logger.info(f"Sending message to agent at port {port}, session {agent_session_id}")
    try:
        async with _MESSAGE_SEMAPHORE:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    f"http://127.0.0.1:{port}/session/{agent_session_id}/message",
                    json={"parts": [{"type": "text", "text": description}]},
                    timeout=httpx.Timeout(connect=15.0, read=600.0, write=30.0, pool=30.0),
                ) as message_resp:
                    logger.info(f"Agent response status: {message_resp.status_code}")

                    if message_resp.status_code == 200:
                        body = b""
                        async for chunk in message_resp.aiter_bytes():
                            body += chunk

                        try:
                            result = json.loads(body)
                            parts = result.get("parts", [])
                            response_text = ""
                            pending_questions = []
                            pending_permissions = []
                            for part in parts:
                                if part.get("type") == "text":
                                    response_text += part.get("text", "")
                                elif part.get("type") == "thought":
                                    response_text += part.get("thought", "")
                                elif part.get("type") == "permission":
                                    pending_permissions.append(part)
                                elif part.get("type") in ("tool_use", "question"):
                                    pending_questions.append(part)

                            logger.info(f"Agent response text: {response_text[:100]}...")

                            async for db in get_db():
                                msg_timestamp = now()
                                # Assistant text is persisted exclusively through OpenCode sqlite
                                # history ingestion in session_sync to avoid duplicate messages.

                                for q in pending_questions + pending_permissions:
                                    q_id = str(uuid.uuid4())
                                    q_type = q.get("type", "unknown")
                                    q_content = (
                                        q.get("text")
                                        or q.get("question")
                                        or q.get("input", {}).get("prompt", "")
                                        or json.dumps(q)
                                    )
                                    q_metadata = json.dumps(q)
                                    await db.execute(
                                        """INSERT INTO questions (id, session_id, task_id, question_type, content, metadata, status, created_at)
                                           VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
                                        (
                                            q_id,
                                            agent_session_id,
                                            task_id,
                                            q_type,
                                            q_content[:2000],
                                            q_metadata,
                                            msg_timestamp,
                                        ),
                                    )
                                    logger.info(f"Stored pending question {q_id} of type {q_type}")

                                if pending_permissions:
                                    await transition_task_status(
                                        task_id,
                                        "waiting_permission",
                                        "agent requested permission",
                                    )
                                elif pending_questions:
                                    await transition_task_status(
                                        task_id,
                                        "waiting_question",
                                        "agent asked a question",
                                    )
                                    logger.info(f"Task {task_id} is waiting for user input")
                                # Don't mark task as completed here - let the session-status poll
                                # detect when the session actually finishes

                                await db.commit()
                        except Exception as e:
                            logger.error(
                                f"Error processing agent response: {e!r}, body: {body[:200]!r}"
                            )
                        else:
                            try:
                                # After OpenCode finishes responding, force a fresh history import
                                # and realtime nudge so the UI updates without manual refresh.
                                await _import_latest_task_session_history(project_id, task_id)
                                await publish_task_updated(project_id, task_id)
                            except Exception:
                                logger.exception(
                                    "post-response history import failed for project=%s task=%s",
                                    project_id,
                                    task_id,
                                )
                    else:
                        logger.error(f"Agent returned status {message_resp.status_code}")
                        try:
                            error_body = await message_resp.aread()
                            logger.error(f"Agent error response body: {error_body[:500]!r}")
                        except Exception:
                            pass
    except Exception as e:
        logger.error(f"Background task failed for task {task_id}: {e!r}")


class TaskCreate(BaseModel):
    description: str
    title: str | None = None
    worktree_id: str | None = None
    model: str | None = None


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    priority: int | None = None


class TaskAssign(BaseModel):
    agent_id: str


class TaskResponse(BaseModel):
    id: str
    project_id: str
    worktree_id: str | None
    title: str
    description: str
    status: str
    assigned_agent_id: str | None
    priority: int
    schedule_cron: str | None
    schedule_enabled: bool
    retry_count: int
    max_retries: int
    archived: bool
    created_at: str
    updated_at: str
    completed_at: str | None


async def render_task_board_fragment(project_id: str) -> str:
    """Render task board snippet with OOB sidebar badge update."""
    async for db in get_db():
        proj_row = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
        project = await proj_row.fetchone()
        if not project:
            return "<div>Project not found</div>"
        project = row_to_dict(project)

        running_rows = await db.execute(
            "SELECT * FROM tasks WHERE project_id = ? AND archived = 0 AND status IN ('running', 'waiting_question', 'waiting_permission') ORDER BY priority ASC, created_at ASC",
            (project_id,),
        )
        running_tasks = [row_to_dict(r) for r in await running_rows.fetchall()]

        completed_rows = await db.execute(
            "SELECT * FROM tasks WHERE project_id = ? AND archived = 0 AND status = 'completed' ORDER BY updated_at DESC",
            (project_id,),
        )
        completed_tasks = [row_to_dict(r) for r in await completed_rows.fetchall()]

        failed_rows = await db.execute(
            "SELECT * FROM tasks WHERE project_id = ? AND archived = 0 AND status = 'failed' ORDER BY updated_at DESC",
            (project_id,),
        )
        failed_tasks = [row_to_dict(r) for r in await failed_rows.fetchall()]

        unread_row = await db.execute(
            "SELECT COUNT(*) AS cnt FROM tasks WHERE project_id = ? AND archived = 0 AND status = 'completed' AND is_new = 1",
            (project_id,),
        )
        completed_unread = (await unread_row.fetchone())["cnt"]

        sidebar_unread_row = await db.execute(
            "SELECT COUNT(*) AS cnt FROM tasks WHERE project_id = ? AND archived = 0 AND is_new = 1",
            (project_id,),
        )
        sidebar_unread = (await sidebar_unread_row.fetchone())["cnt"]
        break

    template = templates.get_template("partials/task-board.html")
    return template.render(
        project=project,
        running_tasks=running_tasks,
        completed_tasks=completed_tasks,
        failed_tasks=failed_tasks,
        completed_unread=completed_unread,
        sidebar_unread=sidebar_unread,
        include_sidebar_oob=True,
    )


@router.get("/{project_id}/tasks", response_model=list[TaskResponse])
async def list_tasks(
    project_id: str,
    status: str | None = None,
    assigned_agent_id: str | None = None,
    include_archived: bool = False,
):
    async for db in get_db():
        query = "SELECT * FROM tasks WHERE project_id = ?"
        params = [project_id]

        if not include_archived:
            query += " AND archived = 0"
        if status:
            query += " AND status = ?"
            params.append(status)
        if assigned_agent_id:
            query += " AND assigned_agent_id = ?"
            params.append(assigned_agent_id)

        query += " ORDER BY priority ASC, created_at ASC"

        rows = await db.execute(query, params)
        tasks = [row_to_dict(row) for row in await rows.fetchall()]

        return [
            TaskResponse(
                id=t["id"],
                project_id=t["project_id"],
                worktree_id=t["worktree_id"],
                title=t["title"],
                description=t["description"],
                status=t["status"],
                assigned_agent_id=t["assigned_agent_id"],
                priority=t["priority"],
                schedule_cron=t["schedule_cron"],
                schedule_enabled=bool(t["schedule_enabled"]),
                retry_count=t["retry_count"],
                max_retries=t["max_retries"],
                archived=bool(t.get("archived", 0)),
                created_at=t["created_at"],
                updated_at=t["updated_at"],
                completed_at=t["completed_at"],
            )
            for t in tasks
        ]


@router.post("/{project_id}/tasks", status_code=201, response_model=TaskResponse)
async def create_task(project_id: str, data: TaskCreate, request: Request):
    async for db in get_db():
        proj = await db.execute("SELECT id, path FROM projects WHERE id = ?", (project_id,))
        project = await proj.fetchone()
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
        expected_project_path = str(project["path"])

        task_id = str(uuid.uuid4())
        timestamp = now()

        title = data.title or (
            data.description[:50] + "..." if len(data.description) > 50 else data.description
        )

        await db.execute(
            """INSERT INTO tasks (id, project_id, worktree_id, title, description, status, priority, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'created', 0, ?, ?)""",
            (
                task_id,
                project_id,
                data.worktree_id,
                title,
                data.description,
                timestamp,
                timestamp,
            ),
        )
        await db.commit()

        await db.execute(
            """INSERT INTO task_logs (id, task_id, event, to_status, timestamp)
               VALUES (?, ?, 'created', 'created', ?)""",
            (str(uuid.uuid4()), task_id, timestamp),
        )
        await db.commit()

    a = await _bootstrap_project_pinned_agent(project_id, expected_project_path)
    if a:

        try:
            async with httpx.AsyncClient() as client:
                agent_id = a["id"]
                port = a["port"]
                base_url = f"http://127.0.0.1:{port}"

                session_json = {"title": title[:50]}
                if data.model:
                    if "/" in data.model:
                        provider, model_id = data.model.split("/", 1)
                        session_json["providerID"] = provider
                        session_json["modelID"] = model_id
                    else:
                        session_json["modelID"] = data.model
                session_resp = await client.post(f"{base_url}/session", json=session_json)
                if session_resp.status_code == 200:
                    session = session_resp.json()
                    agent_session_id = session.get("id")
                    path_info = await fetch_path_info(client, int(port))
                    if not _path_info_matches_project(path_info, expected_project_path):
                        raise HTTPException(
                            status_code=400,
                            detail=(
                                "Agent is running in the wrong directory for this project. "
                                "Restart the agent from Settings and try again."
                            ),
                        )

                    timestamp = now()
                    async for db in get_db():
                        await db.execute(
                            "UPDATE tasks SET status = 'running', assigned_agent_id = ?, updated_at = ? WHERE id = ?",
                            (agent_id, timestamp, task_id),
                        )
                        await db.commit()

                        await db.execute(
                            """INSERT INTO sessions (id, project_id, task_id, agent_id, status, started_at)
                               VALUES (?, ?, ?, ?, 'running', ?)""",
                            (agent_session_id, project_id, task_id, agent_id, timestamp),
                        )
                        await db.commit()

                        await db.execute(
                            """INSERT INTO task_messages (id, task_id, role, content, timestamp)
                               VALUES (?, ?, 'user', ?, ?)""",
                            (str(uuid.uuid4()), task_id, data.description, timestamp),
                        )
                        await db.commit()

                    asyncio.create_task(
                        send_task_to_agent_background(
                            project_id, task_id, agent_session_id, data.description, port
                        )
                    )

                    response = TaskResponse(
                        id=task_id,
                        project_id=project_id,
                        worktree_id=data.worktree_id,
                        title=title,
                        description=data.description,
                        status="running",
                        assigned_agent_id=agent_id,
                        priority=0,
                        schedule_cron=None,
                        schedule_enabled=False,
                        retry_count=0,
                        max_retries=3,
                        archived=False,
                        created_at=timestamp,
                        updated_at=timestamp,
                        completed_at=None,
                    )
                    if request.headers.get("HX-Request") == "true":
                        return HTMLResponse(content=await render_task_board_fragment(project_id))
                    return response
        except Exception:
            pass

    response = TaskResponse(
        id=task_id,
        project_id=project_id,
        worktree_id=data.worktree_id,
        title=title,
        description=data.description,
        status="created",
        assigned_agent_id=None,
        priority=0,
        schedule_cron=None,
        schedule_enabled=False,
        retry_count=0,
        max_retries=3,
        archived=False,
        created_at=timestamp,
        updated_at=timestamp,
        completed_at=None,
    )
    if request.headers.get("HX-Request") == "true":
        return HTMLResponse(content=await render_task_board_fragment(project_id))
    return response


@router.post("/{project_id}/tasks/create-form")
async def create_task_form(
    project_id: str,
    request: Request,
    description: str = Form(...),
    model: str | None = Form(default=None),
):
    payload = TaskCreate(description=description, model=model)
    return await create_task(project_id=project_id, data=payload, request=request)


@router.get("/{project_id}/tasks/model-options-fragment")
async def get_task_model_options_fragment(project_id: str):
    async for db in get_db():
        project_row = await db.execute("SELECT id FROM projects WHERE id = ?", (project_id,))
        if not await project_row.fetchone():
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
        break
    models = await get_available_models()
    template = templates.get_template("partials/task-model-picker.html")
    return HTMLResponse(content=template.render(models=models))


@router.get("/{project_id}/tasks/{task_id}")
async def get_task_detail(project_id: str, task_id: str):

    async for db in get_db():
        task_row = await db.execute(
            "SELECT * FROM tasks WHERE id = ? AND project_id = ?", (task_id, project_id)
        )
        task = await task_row.fetchone()
        if not task:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
        t = row_to_dict(task)

        session_row = await db.execute(
            "SELECT * FROM sessions WHERE task_id = ? ORDER BY started_at DESC LIMIT 1",
            (task_id,),
        )
        session = await session_row.fetchone()
        s = row_to_dict(session) if session else None

        agent_row = await db.execute(
            "SELECT * FROM agent_registry WHERE id = ?", (t.get("assigned_agent_id"),)
        )
        agent = await agent_row.fetchone()
        a = row_to_dict(agent) if agent else None

    return {
        "task": t,
        "session": s,
        "agent": a,
    }


@router.get("/{project_id}/tasks/{task_id}/messages")
async def get_task_messages(project_id: str, task_id: str):
    async for db in get_db():
        task_row = await db.execute(
            "SELECT * FROM tasks WHERE id = ? AND project_id = ?", (task_id, project_id)
        )
        task = await task_row.fetchone()
        if not task:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

        msg_rows = await db.execute(
            "SELECT * FROM task_messages WHERE task_id = ? ORDER BY timestamp ASC",
            (task_id,),
        )
        messages = [row_to_dict(row) for row in await msg_rows.fetchall()]

    return {"messages": messages}


@router.get("/{project_id}/tasks/{task_id}/messages-fragment")
async def get_task_messages_fragment(project_id: str, task_id: str):
    if await _task_history_appears_stale(task_id):
        await _import_latest_task_session_history(project_id, task_id)

    payload = await get_task_messages(project_id, task_id)
    has_legacy_truncated = any(
        message.get("source") == "opencode_sqlite"
        and len(str(message.get("content", ""))) == 10000
        for message in payload["messages"]
    )
    if has_legacy_truncated:
        await _repair_legacy_truncated_task_messages(project_id, task_id)
        payload = await get_task_messages(project_id, task_id)
    rendered_messages = []
    for message in payload["messages"]:
        rendered_messages.append(
            {
                **message,
                "content_html": _render_message_content_html(
                    str(message.get("role", "")),
                    str(message.get("content", "")),
                ),
            }
        )
    template = templates.get_template("partials/task-messages.html")
    return HTMLResponse(
        content=template.render(
            project_id=project_id,
            task_id=task_id,
            messages=rendered_messages,
        )
    )


@router.get("/{project_id}/tasks/{task_id}/stream")
async def get_task_stream(project_id: str, task_id: str, bootstrap_only: bool = False):
    async for db in get_db():
        task_row = await db.execute(
            "SELECT id FROM tasks WHERE id = ? AND project_id = ?",
            (task_id, project_id),
        )
        if not await task_row.fetchone():
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
        break

    async def event_generator():
        # Prime the client immediately so stream validation can proceed.
        yield _render_sse_event("task-updated")
        if bootstrap_only:
            return
        async with task_event_broker.subscribe(project_id, task_id) as queue:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield _render_sse_event(event.name, event.data)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                except asyncio.CancelledError:
                    break

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/{project_id}/tasks/{task_id}/mark-read")
async def mark_task_read(project_id: str, task_id: str):
    async for db in get_db():
        task_row = await db.execute(
            "SELECT id FROM tasks WHERE id = ? AND project_id = ?", (task_id, project_id)
        )
        if not await task_row.fetchone():
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
        await db.execute("UPDATE tasks SET is_new = 0, updated_at = ? WHERE id = ?", (now(), task_id))
        await db.commit()
    return {"status": "ok"}


@router.get("/{project_id}/tasks/{task_id}/session-status")
async def get_task_session_status(project_id: str, task_id: str):
    async for db in get_db():
        session_row = await db.execute(
            "SELECT * FROM sessions WHERE task_id = ? AND project_id = ? ORDER BY started_at DESC LIMIT 1",
            (task_id, project_id),
        )
        session = await session_row.fetchone()
        if not session:
            return {"status": "none"}

        session_status = session["status"]

        # If session has finished, update task status accordingly
        if session_status in ("completed", "stopped", "failed"):
            timestamp = now()
            task_row = await db.execute("SELECT status FROM tasks WHERE id = ?", (task_id,))
            task = await task_row.fetchone()
            if task and task["status"] != "completed":
                await db.execute(
                    "UPDATE tasks SET status = ?, completed_at = ?, updated_at = ? WHERE id = ?",
                    (session_status, timestamp, timestamp, task_id),
                )
                await db.commit()

        task_row = await db.execute("SELECT status FROM tasks WHERE id = ?", (task_id,))
        task_now = await task_row.fetchone()
        return {"status": task_now["status"] if task_now else "unknown"}

    return {"status": "unknown"}


@router.get("/{project_id}/tasks/{task_id}/status-fragment")
async def get_task_status_fragment(project_id: str, task_id: str):
    status_payload = await get_task_session_status(project_id, task_id)
    status = status_payload.get("status", "unknown")
    template = templates.get_template("partials/task-status.html")
    return HTMLResponse(content=template.render(status=status))


@router.get("/{project_id}/tasks/{task_id}/prompts-fragment")
async def get_task_prompts_fragment(project_id: str, task_id: str):
    async for db in get_db():
        q_rows = await db.execute(
            """
            SELECT q.*
            FROM questions q
            JOIN sessions s ON s.id = q.session_id
            WHERE q.task_id = ? AND q.status = 'pending'
            ORDER BY q.created_at ASC
            """,
            (task_id,),
        )
        questions = [row_to_dict(r) for r in await q_rows.fetchall()]
        break
    template = templates.get_template("partials/task-prompts.html")
    return HTMLResponse(
        content=template.render(project_id=project_id, task_id=task_id, questions=questions)
    )


@router.post("/{project_id}/tasks/{task_id}/send-message")
async def send_task_message_v2(project_id: str, task_id: str, data: dict):
    message = data.get("message", "")
    if not message:
        return {"status": "error", "message": "No message provided"}

    async for db in get_db():
        task_row = await db.execute(
            "SELECT * FROM tasks WHERE id = ? AND project_id = ?", (task_id, project_id)
        )
        task = await task_row.fetchone()
        if not task:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
        t = row_to_dict(task)
        project_row = await db.execute("SELECT path FROM projects WHERE id = ?", (project_id,))
        project = await project_row.fetchone()
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
        expected_project_path = str(project["path"])

        # Always try to reuse the latest existing session to preserve context,
        # even if local task/session status drifted to a terminal state.
        session_row = await db.execute(
            "SELECT * FROM sessions WHERE task_id = ? ORDER BY started_at DESC LIMIT 1",
            (task_id,),
        )
        session = await session_row.fetchone()

        if not session:
            bootstrap_agent = await _bootstrap_project_pinned_agent(project_id, expected_project_path)
            if not bootstrap_agent:
                return {
                    "status": "error",
                    "message": (
                        "No project-pinned agent available for this project path. "
                        "Check agent startup from Settings."
                    ),
                }
            a = bootstrap_agent

            async with httpx.AsyncClient() as client:
                port = a["port"]
                session_resp = await client.post(
                    f"http://127.0.0.1:{port}/session", json={"title": t["description"][:50]}
                )
                if session_resp.status_code != 200:
                    return {"status": "error", "message": "Failed to create session"}

                new_session = session_resp.json()
                agent_session_id = new_session.get("id")

                timestamp = now()
                await db.execute(
                    "UPDATE tasks SET status = 'running', assigned_agent_id = ?, updated_at = ? WHERE id = ?",
                    (a["id"], timestamp, task_id),
                )
                await db.commit()

                await db.execute(
                    """INSERT INTO sessions (id, project_id, task_id, agent_id, status, started_at)
                       VALUES (?, ?, ?, ?, 'running', ?)""",
                    (agent_session_id, project_id, task_id, a["id"], timestamp),
                )
                await db.commit()

                session_id = agent_session_id
        else:
            s = row_to_dict(session)
            session_id = s["id"]

            agent_row = await db.execute(
                "SELECT * FROM agent_registry WHERE id = ?", (t.get("assigned_agent_id"),)
            )
            agent = await agent_row.fetchone()
            if not agent:
                return {"status": "error", "message": "Agent not found"}

            a = row_to_dict(agent)
            port = a["port"]
            await update_agent_cwd(a["id"], project_id)

            alive = await probe_agent_session(session_id, port)
            should_rotate_session = not alive
            if alive:
                try:
                    async with httpx.AsyncClient(**httpx_auth_kw()) as client:
                        path_info = await fetch_path_info(client, int(port))
                    actual_directory = None
                    if isinstance(path_info, dict):
                        directory = path_info.get("directory")
                        if isinstance(directory, str) and directory:
                            actual_directory = str(Path(directory).resolve())
                    if actual_directory and actual_directory != str(Path(expected_project_path).resolve()):
                        should_rotate_session = True
                        logger.warning(
                            "Session %s directory mismatch (%s != %s), rotating session",
                            session_id,
                            actual_directory,
                            expected_project_path,
                        )
                except Exception:
                    logger.exception(
                        "Failed to validate OpenCode directory for session %s; continuing with existing session",
                        session_id,
                    )
            if should_rotate_session:
                logger.warning(
                    "Session %s unavailable for reuse, closing and creating fresh", session_id
                )
                ts = now()
                await db.execute(
                    "UPDATE sessions SET status = 'completed', ended_at = ? WHERE id = ?",
                    (ts, session_id),
                )
                await db.commit()

                fa = await _bootstrap_project_pinned_agent(project_id, expected_project_path)
                if not fa:
                    return {
                        "status": "error",
                        "message": (
                            "Session unavailable and no project-pinned agent could be started."
                        ),
                    }

                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"http://127.0.0.1:{fa['port']}/session",
                        json={"title": t["description"][:50]},
                    )
                    if resp.status_code != 200:
                        return {"status": "error", "message": "Failed to create fresh session"}

                    new_sess = resp.json()
                    session_id = new_sess.get("id")
                    ts2 = now()
                    await db.execute(
                        """INSERT INTO sessions (id, project_id, task_id, agent_id, status, started_at)
                           VALUES (?, ?, ?, ?, 'running', ?)""",
                        (session_id, project_id, task_id, fa["id"], ts2),
                    )
                    await db.commit()
                    a = fa
                    port = a["port"]

            async with httpx.AsyncClient(**httpx_auth_kw()) as client:
                path_info = await fetch_path_info(client, int(port))
            if not _path_info_matches_project(path_info, expected_project_path):
                return {
                    "status": "error",
                    "message": (
                        "Agent directory mismatch for this project. "
                        "Restart the agent from Settings in the correct project directory."
                    ),
                }

            # Mark task as running so the UI status badge updates immediately.
            timestamp = now()
            await db.execute(
                "UPDATE sessions SET status = 'running', ended_at = NULL WHERE id = ?",
                (session_id,),
            )
            await db.execute(
                "UPDATE tasks SET status = 'running', updated_at = ? WHERE id = ?",
                (timestamp, task_id),
            )
            await db.commit()

        port = a["port"]

        timestamp = now()
        await db.execute(
            """INSERT INTO task_messages (id, task_id, role, content, timestamp)
               VALUES (?, ?, 'user', ?, ?)""",
            (str(uuid.uuid4()), task_id, message, timestamp),
        )
        await db.commit()

    await publish_task_updated(project_id, task_id)
    logger.info(f"Firing background task for session={session_id} port={port} msg={message[:30]}")
    asyncio.create_task(
        send_task_to_agent_background(project_id, task_id, session_id, message, port)
    )

    return {"status": "ok"}


@router.post("/{project_id}/tasks/{task_id}/send-message-form")
async def send_task_message_form(project_id: str, task_id: str, message: str = Form(...)):
    result = await send_task_message_v2(project_id, task_id, {"message": message})
    if result.get("status") != "ok":
        raise HTTPException(status_code=400, detail=result.get("message", "Failed to send message"))

    asyncio.create_task(_sync_task_after_send(project_id, task_id))
    return await get_task_messages_fragment(project_id, task_id)


@router.post("/{project_id}/tasks/{task_id}/run")
async def run_task(project_id: str, task_id: str):
    expected_project_path = ""
    async for db in get_db():
        task_row = await db.execute(
            "SELECT * FROM tasks WHERE id = ? AND project_id = ?", (task_id, project_id)
        )
        task = await task_row.fetchone()
        if not task:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
        t = row_to_dict(task)
        project_row = await db.execute("SELECT path FROM projects WHERE id = ?", (project_id,))
        project = await project_row.fetchone()
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
        expected_project_path = str(project["path"])

        if t["status"] != "created":
            return {
                "status": "error",
                "message": f"Task is not in created state (current: {t['status']})",
            }

        a = await _bootstrap_project_pinned_agent(project_id, expected_project_path)
        if not a:
            return {
                "status": "error",
                "message": (
                    "No project-pinned agent available. Add/restart an agent in Settings "
                    "for this project path."
                ),
            }

    agent_id = a["id"]
    port = a["port"]

    base_url = f"http://127.0.0.1:{port}"

    try:
        async with httpx.AsyncClient() as client:
            session_resp = await client.post(
                f"{base_url}/session", json={"title": t["description"][:50]}
            )
            if session_resp.status_code != 200:
                return {
                    "status": "error",
                    "message": f"Failed to create session: {session_resp.text}",
                }

            session = session_resp.json()
            agent_session_id = session.get("id")
            path_info = await fetch_path_info(client, int(port))
            if not _path_info_matches_project(path_info, expected_project_path):
                return {
                    "status": "error",
                    "message": (
                        "Agent is running in the wrong directory for this project. "
                        "Restart the agent from Settings and try again."
                    ),
                }

            timestamp = now()

            async for db in get_db():
                await db.execute(
                    "UPDATE tasks SET status = 'running', assigned_agent_id = ?, updated_at = ? WHERE id = ?",
                    (agent_id, timestamp, task_id),
                )
                await db.commit()

                await db.execute(
                    """INSERT INTO sessions (id, project_id, task_id, agent_id, status, started_at)
                       VALUES (?, ?, ?, ?, 'running', ?)""",
                    (agent_session_id, project_id, task_id, agent_id, timestamp),
                )
                await db.commit()

                await db.execute(
                    """INSERT INTO task_messages (id, task_id, role, content, timestamp)
                       VALUES (?, ?, 'user', ?, ?)""",
                    (str(uuid.uuid4()), task_id, t["description"], timestamp),
                )
                await db.commit()

            asyncio.create_task(
                send_task_to_agent_background(
                    project_id, task_id, agent_session_id, t["description"], port
                )
            )
            await publish_task_updated(project_id, task_id)

            return {
                "status": "started",
                "session_id": agent_session_id,
                "message": f"Task '{t['title']}' is now running!",
            }

    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.delete("/{project_id}/tasks/{task_id}/archive")
async def archive_task(project_id: str, task_id: str, request: Request):
    async for db in get_db():
        task_row = await db.execute(
            "SELECT * FROM tasks WHERE id = ? AND project_id = ?", (task_id, project_id)
        )
        task = await task_row.fetchone()
        if not task:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

        timestamp = now()
        await db.execute(
            "UPDATE tasks SET archived = 1, is_new = 0, updated_at = ? WHERE id = ?",
            (timestamp, task_id),
        )
        await db.commit()

    if request.headers.get("HX-Request") == "true":
        return HTMLResponse(content=await render_task_board_fragment(project_id))
    return {"status": "ok"}


@router.post("/{project_id}/tasks/{task_id}/unarchive")
async def unarchive_task(project_id: str, task_id: str, request: Request):
    async for db in get_db():
        task_row = await db.execute(
            "SELECT * FROM tasks WHERE id = ? AND project_id = ?", (task_id, project_id)
        )
        task = await task_row.fetchone()
        if not task:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

        timestamp = now()
        await db.execute(
            "UPDATE tasks SET archived = 0, updated_at = ? WHERE id = ?",
            (timestamp, task_id),
        )
        await db.commit()

    if request.headers.get("HX-Request") == "true":
        return HTMLResponse(content=await render_task_board_fragment(project_id))
    return {"status": "ok"}


@router.post("/{project_id}/tasks/{task_id}/archive")
async def archive_task_post(project_id: str, task_id: str, request: Request):
    return await archive_task(project_id, task_id, request)


@router.delete("/{project_id}/tasks/{task_id}", status_code=204)
async def delete_task(project_id: str, task_id: str):
    async for db in get_db():
        task_row = await db.execute(
            "SELECT * FROM tasks WHERE id = ? AND project_id = ?", (task_id, project_id)
        )
        task = await task_row.fetchone()
        if not task:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

        await db.execute("DELETE FROM sessions WHERE task_id = ?", (task_id,))
        await db.commit()

        result = await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        await db.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")


@router.get("/sessions/{session_id}/questions")
async def get_session_questions(session_id: str, status: str | None = None):
    async for db in get_db():
        query = "SELECT * FROM questions WHERE session_id = ?"
        params = [session_id]

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY created_at ASC"

        rows = await db.execute(query, params)
        questions = [row_to_dict(row) for row in await rows.fetchall()]

    return {"questions": questions}


class QuestionRespond(BaseModel):
    response: str


async def _respond_to_question(session_id: str, question_id: str, response_text: str):
    async for db in get_db():
        q_row = await db.execute(
            "SELECT * FROM questions WHERE id = ? AND session_id = ?", (question_id, session_id)
        )
        question = await q_row.fetchone()
        if not question:
            raise HTTPException(status_code=404, detail=f"Question '{question_id}' not found")

        q = row_to_dict(question)
        if q["status"] != "pending":
            raise HTTPException(status_code=400, detail="Question already answered")

        task_id = q["task_id"]

        task_row = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        task = await task_row.fetchone()
        if not task:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

        t = row_to_dict(task)
        assigned_agent_id = t.get("assigned_agent_id")
        if not assigned_agent_id:
            raise HTTPException(status_code=400, detail="Task has no assigned agent")

        agent_row = await db.execute(
            "SELECT * FROM agent_registry WHERE id = ?", (assigned_agent_id,)
        )
        agent = await agent_row.fetchone()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        a = row_to_dict(agent)
        port = a["port"]

        timestamp = now()
        await db.execute(
            "UPDATE questions SET status = 'answered', answered_at = ? WHERE id = ?",
            (timestamp, question_id),
        )
        await transition_task_status(task_id, "running", "user answered pending question")
        await db.commit()

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"http://127.0.0.1:{port}/session/{session_id}/message",
            json={"parts": [{"type": "text", "text": response_text}]},
            timeout=httpx.Timeout(30.0),
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to send response to agent")

    asyncio.create_task(
        send_task_to_agent_background(
            project_id=t["project_id"],
            task_id=task_id,
            agent_session_id=session_id,
            description=response_text,
            port=port,
        )
    )

    return {"status": "ok", "message": "Response sent to agent", "task_id": task_id, "project_id": t["project_id"]}


@router.post("/sessions/{session_id}/questions/{question_id}/respond")
async def respond_to_question(session_id: str, question_id: str, data: QuestionRespond):
    return await _respond_to_question(session_id, question_id, data.response)


@router.post("/sessions/{session_id}/questions/{question_id}/respond-form")
async def respond_to_question_form(
    session_id: str,
    question_id: str,
    response: str = Form(...),
):
    payload = await _respond_to_question(session_id, question_id, response)
    return await get_task_prompts_fragment(payload["project_id"], payload["task_id"])

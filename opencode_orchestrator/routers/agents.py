import uuid
import os
import asyncio
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

from opencode_orchestrator.models import fetch_one, fetch_all, execute, now

router = APIRouter()
templates = Environment(loader=FileSystemLoader(Path(__file__).parent.parent / "templates"))


async def _agent_rows() -> list[dict]:
    return await fetch_all("SELECT * FROM agent_registry ORDER BY name ASC")


async def get_available_models() -> list[dict[str, str]]:
    """Query available OpenCode agents for provider/model metadata."""
    import httpx

    models: list[dict[str, str]] = []
    agents = await fetch_all("SELECT * FROM agent_registry WHERE status = 'available'")

    for agent in agents:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"http://127.0.0.1:{agent['port']}/config/providers", timeout=10.0
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                providers = data.get("providers", []) if isinstance(data, dict) else data
                for provider in providers:
                    provider_id = provider.get("id", "")
                    provider_name = provider.get("name", provider_id)
                    provider_models = provider.get("models", {})
                    if isinstance(provider_models, dict):
                        provider_models = list(provider_models.values())
                    for model in provider_models:
                        model_id = model.get("id", "")
                        if not model_id:
                            continue
                        full_id = f"{provider_id}/{model_id}"
                        model_name = model.get("name", model_id)
                        models.append(
                            {
                                "id": full_id,
                                "name": model_name,
                                "provider": provider_id,
                            }
                        )
        except Exception:
            continue

    unique_models: dict[str, dict[str, str]] = {}
    for model in models:
        unique_models.setdefault(model["id"], model)
    return sorted(unique_models.values(), key=lambda model: model["id"])


class AgentCreate(BaseModel):
    name: str
    port: int
    cwd: str | None = None


class AgentUpdate(BaseModel):
    name: str | None = None
    port: int | None = None
    config: dict | None = None


class AgentResponse(BaseModel):
    id: str
    name: str
    command: str
    port: int
    cwd: str | None
    capabilities: dict | None
    status: str
    config: dict | None
    pid: int | None
    last_seen: str | None
    created_at: str


@router.get("", response_model=list[AgentResponse])
async def list_agents():
    agents = await fetch_all("SELECT * FROM agent_registry ORDER BY name ASC")

    return [
        AgentResponse(
            id=a["id"],
            name=a["name"],
            command=a["command"],
            port=a["port"],
            cwd=a.get("cwd"),
            capabilities=a["capabilities"],
            status=a["status"],
            config=a["config"],
            pid=a.get("pid"),
            last_seen=a["last_seen"],
            created_at=a["created_at"],
        )
        for a in agents
    ]


@router.get("/models")
async def list_available_models():
    return {"models": await get_available_models()}


@router.post("", status_code=201, response_model=AgentResponse)
async def create_agent(data: AgentCreate):

    command = f"opencode serve --port {data.port}"
    agent_id = str(uuid.uuid4())
    timestamp = now()

    existing = await fetch_one("SELECT id FROM agent_registry WHERE name = ?", (data.name,))
    if existing:
        raise HTTPException(status_code=409, detail=f"Agent '{data.name}' already registered")

    agent_cwd = os.path.expanduser(data.cwd) if data.cwd else os.getcwd()

    await execute(
        """INSERT INTO agent_registry (id, name, command, port, cwd, capabilities, status, config, pid, last_seen, created_at)
           VALUES (?, ?, ?, ?, ?, NULL, 'offline', NULL, NULL, NULL, ?)""",
        (agent_id, data.name, command, data.port, agent_cwd, timestamp),
    )

    return AgentResponse(
        id=agent_id,
        name=data.name,
        command=command,
        port=data.port,
        cwd=agent_cwd,
        capabilities=None,
        status="offline",
        config=None,
        pid=None,
        last_seen=None,
        created_at=timestamp,
    )


@router.post("/form")
async def create_agent_form(
    name: str = Form(...),
    port: int = Form(...),
    cwd: str | None = Form(default=None),
):
    await create_agent(AgentCreate(name=name, port=port, cwd=cwd))
    template = templates.get_template("partials/agent-list.html")
    return HTMLResponse(content=template.render(agents=await _agent_rows()))


@router.post("/{agent_id}/start")
async def start_agent(agent_id: str):
    agent = await fetch_one("SELECT * FROM agent_registry WHERE id = ?", (agent_id,))
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    if agent.get("pid"):
        try:
            os.kill(agent["pid"], 0)
            return {"status": "error", "message": "Agent already running"}
        except OSError:
            pass

    try:
        proc = await asyncio.create_subprocess_shell(
            agent["command"],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=agent.get("cwd") or os.getcwd(),
        )

        await asyncio.sleep(3)

        try:
            os.kill(proc.pid, 0)
            pid = proc.pid
        except OSError:
            stdout, stderr = await proc.communicate()
            return {"status": "error", "message": f"Failed to start: {stderr.decode()[:200]}"}

        timestamp = now()
        await execute(
            "UPDATE agent_registry SET status = 'starting', pid = ?, last_seen = ? WHERE id = ?",
            (pid, timestamp, agent_id),
        )

        return {"status": "started", "pid": pid}

    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/{agent_id}/stop")
async def stop_agent(agent_id: str):
    agent = await fetch_one("SELECT * FROM agent_registry WHERE id = ?", (agent_id,))
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    pid = agent.get("pid")
    if not pid:
        return {"status": "error", "message": "Agent not running"}

    try:
        os.kill(pid, 15)
        await asyncio.sleep(1)
        try:
            os.kill(pid, 9)
        except OSError:
            pass
    except OSError:
        pass

    timestamp = now()
    await execute(
        "UPDATE agent_registry SET status = 'offline', pid = NULL, last_seen = ? WHERE id = ?",
        (timestamp, agent_id),
    )

    return {"status": "stopped"}


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str):
    agent = await fetch_one("SELECT * FROM agent_registry WHERE id = ?", (agent_id,))
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return AgentResponse(
        id=agent["id"],
        name=agent["name"],
        command=agent["command"],
        port=agent["port"],
        cwd=agent.get("cwd"),
        capabilities=agent["capabilities"],
        status=agent["status"],
        config=agent["config"],
        pid=agent.get("pid"),
        last_seen=agent["last_seen"],
        created_at=agent["created_at"],
    )


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: str):
    agent = await fetch_one("SELECT * FROM agent_registry WHERE id = ?", (agent_id,))
    if agent:
        pid = agent.get("pid")
        if pid:
            try:
                os.kill(pid, 15)
            except OSError:
                pass

    result = await execute("DELETE FROM agent_registry WHERE id = ?", (agent_id,))
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")


async def ensure_agent_running(agent_id: str):
    agent = await fetch_one("SELECT * FROM agent_registry WHERE id = ?", (agent_id,))
    if not agent:
        return None

    pid = agent.get("pid")
    if pid:
        try:
            os.kill(pid, 0)
            return agent
        except OSError:
            pass

    proc = await asyncio.create_subprocess_shell(
        agent["command"],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=agent.get("cwd") or os.getcwd(),
    )
    await asyncio.sleep(3)

    try:
        os.kill(proc.pid, 0)
        new_pid = proc.pid
    except OSError:
        return None

    timestamp = now()
    await execute(
        "UPDATE agent_registry SET status = 'starting', pid = ?, last_seen = ? WHERE id = ?",
        (new_pid, timestamp, agent_id),
    )

    return agent


@router.post("/{agent_id}/ping")
async def ping_agent(agent_id: str):
    import httpx

    agent = await ensure_agent_running(agent_id)
    if not agent:
        return {"status": "error", "message": "Failed to start agent"}

    base_url = f"http://127.0.0.1:{agent['port']}"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{base_url}/global/health", timeout=10.0)
            if resp.status_code == 200:
                timestamp = now()
                await execute(
                    "UPDATE agent_registry SET status = 'available', last_seen = ? WHERE id = ?",
                    (timestamp, agent_id),
                )
                return {"status": "available", "capabilities": {}}
            else:
                return {"status": "error", "message": f"Health check failed: {resp.status_code}"}
    except Exception as e:
        timestamp = now()
        await execute(
            "UPDATE agent_registry SET status = 'error', last_seen = ? WHERE id = ?",
            (timestamp, agent_id),
        )
        return {"status": "error", "message": str(e)}


@router.post("/{agent_id}/start-form")
async def start_agent_form(agent_id: str):
    await start_agent(agent_id)
    template = templates.get_template("partials/agent-list.html")
    return HTMLResponse(content=template.render(agents=await _agent_rows()))


@router.post("/{agent_id}/stop-form")
async def stop_agent_form(agent_id: str):
    await stop_agent(agent_id)
    template = templates.get_template("partials/agent-list.html")
    return HTMLResponse(content=template.render(agents=await _agent_rows()))


@router.post("/{agent_id}/ping-form")
async def ping_agent_form(agent_id: str):
    await ping_agent(agent_id)
    template = templates.get_template("partials/agent-list.html")
    return HTMLResponse(content=template.render(agents=await _agent_rows()))


class AgentMessage(BaseModel):
    message: str


@router.post("/{agent_id}/message")
async def send_message(agent_id: str, data: AgentMessage):
    import httpx

    a = await ensure_agent_running(agent_id)
    if not a:
        return {"status": "error", "message": "Failed to start agent"}

    base_url = f"http://127.0.0.1:{a['port']}"

    try:
        async with httpx.AsyncClient() as client:
            session_resp = await client.post(
                f"{base_url}/session", json={"title": data.message[:50]}
            )
            if session_resp.status_code != 200:
                return {
                    "status": "error",
                    "message": f"Failed to create session: {session_resp.text}",
                }

            session = session_resp.json()
            session_id = session.get("id")

            message_resp = await client.post(
                f"{base_url}/session/{session_id}/message",
                json={"parts": [{"type": "text", "text": data.message}]},
                timeout=120.0,
            )

            if message_resp.status_code != 200:
                return {
                    "status": "error",
                    "message": f"Failed to send message: {message_resp.text}",
                }

            result = message_resp.json()
            parts = result.get("parts", [])
            response_text = ""
            for part in parts:
                if part.get("type") == "text":
                    response_text += part.get("text", "")
                elif part.get("type") == "thought":
                    response_text += part.get("thought", "")

            if not response_text:
                return {"status": "ok", "message": f"Sent: '{data.message}' (no text response)"}

            return {"status": "ok", "message": response_text[:500]}

    except Exception as e:
        return {"status": "error", "message": str(e)}

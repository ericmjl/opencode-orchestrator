import uuid
import os
import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import json

from opencode_orchestrator.models import get_db, row_to_dict, now

router = APIRouter()


class AgentCreate(BaseModel):
    name: str
    port: int


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
    async for db in get_db():
        rows = await db.execute("SELECT * FROM agent_registry ORDER BY name ASC")
        agents = [row_to_dict(row) for row in await rows.fetchall()]

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


@router.post("", status_code=201, response_model=AgentResponse)
async def create_agent(data: AgentCreate):
    import json

    command = f"opencode serve --port {data.port}"
    agent_id = str(uuid.uuid4())
    timestamp = now()

    async for db in get_db():
        existing = await db.execute("SELECT id FROM agent_registry WHERE name = ?", (data.name,))
        if await existing.fetchone():
            raise HTTPException(status_code=409, detail=f"Agent '{data.name}' already registered")

        await db.execute(
            """INSERT INTO agent_registry (id, name, command, port, cwd, capabilities, status, config, pid, last_seen, created_at)
               VALUES (?, ?, ?, ?, ?, NULL, 'offline', NULL, NULL, NULL, ?)""",
            (agent_id, data.name, command, data.port, os.getcwd(), timestamp),
        )
        await db.commit()

    return AgentResponse(
        id=agent_id,
        name=data.name,
        command=command,
        port=data.port,
        cwd=os.getcwd(),
        capabilities=None,
        status="offline",
        config=None,
        pid=None,
        last_seen=None,
        created_at=timestamp,
    )


@router.post("/{agent_id}/start")
async def start_agent(agent_id: str):
    async for db in get_db():
        row = await db.execute("SELECT * FROM agent_registry WHERE id = ?", (agent_id,))
        agent = await row.fetchone()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
        a = row_to_dict(agent)

    if a.get("pid"):
        try:
            os.kill(a["pid"], 0)
            return {"status": "error", "message": "Agent already running"}
        except OSError:
            pass

    try:
        proc = await asyncio.create_subprocess_shell(
            a["command"],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=a.get("cwd") or os.getcwd(),
        )

        await asyncio.sleep(3)

        try:
            os.kill(proc.pid, 0)
            pid = proc.pid
        except OSError:
            stdout, stderr = await proc.communicate()
            return {"status": "error", "message": f"Failed to start: {stderr.decode()[:200]}"}

        timestamp = now()
        async for db in get_db():
            await db.execute(
                "UPDATE agent_registry SET status = 'starting', pid = ?, last_seen = ? WHERE id = ?",
                (pid, timestamp, agent_id),
            )
            await db.commit()

        return {"status": "started", "pid": pid}

    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/{agent_id}/stop")
async def stop_agent(agent_id: str):
    async for db in get_db():
        row = await db.execute("SELECT * FROM agent_registry WHERE id = ?", (agent_id,))
        agent = await row.fetchone()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
        a = row_to_dict(agent)

    pid = a.get("pid")
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
    async for db in get_db():
        await db.execute(
            "UPDATE agent_registry SET status = 'offline', pid = NULL, last_seen = ? WHERE id = ?",
            (timestamp, agent_id),
        )
        await db.commit()

    return {"status": "stopped"}


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str):
    async for db in get_db():
        row = await db.execute("SELECT * FROM agent_registry WHERE id = ?", (agent_id,))
        agent = await row.fetchone()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
        a = row_to_dict(agent)
        return AgentResponse(
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


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: str):
    async for db in get_db():
        row = await db.execute("SELECT * FROM agent_registry WHERE id = ?", (agent_id,))
        agent = await row.fetchone()
        if agent:
            a = row_to_dict(agent)
            pid = a.get("pid")
            if pid:
                try:
                    os.kill(pid, 15)
                except OSError:
                    pass

        result = await db.execute("DELETE FROM agent_registry WHERE id = ?", (agent_id,))
        await db.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")


async def ensure_agent_running(agent_id: str):
    async for db in get_db():
        row = await db.execute("SELECT * FROM agent_registry WHERE id = ?", (agent_id,))
        agent = await row.fetchone()
        if not agent:
            return None
        a = row_to_dict(agent)

    pid = a.get("pid")
    if pid:
        try:
            os.kill(pid, 0)
            return a
        except OSError:
            pass

    proc = await asyncio.create_subprocess_shell(
        a["command"],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=a.get("cwd") or os.getcwd(),
    )
    await asyncio.sleep(3)

    try:
        os.kill(proc.pid, 0)
        new_pid = proc.pid
    except OSError:
        return None

    timestamp = now()
    async for db in get_db():
        await db.execute(
            "UPDATE agent_registry SET status = 'starting', pid = ?, last_seen = ? WHERE id = ?",
            (new_pid, timestamp, agent_id),
        )
        await db.commit()

    return a


@router.post("/{agent_id}/ping")
async def ping_agent(agent_id: str):
    import httpx

    a = await ensure_agent_running(agent_id)
    if not a:
        return {"status": "error", "message": "Failed to start agent"}

    base_url = f"http://127.0.0.1:{a['port']}"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{base_url}/global/health", timeout=10.0)
            if resp.status_code == 200:
                timestamp = now()
                async for db in get_db():
                    await db.execute(
                        "UPDATE agent_registry SET status = 'available', last_seen = ? WHERE id = ?",
                        (timestamp, agent_id),
                    )
                    await db.commit()
                return {"status": "available", "capabilities": {}}
            else:
                return {"status": "error", "message": f"Health check failed: {resp.status_code}"}
    except Exception as e:
        timestamp = now()
        async for db in get_db():
            await db.execute(
                "UPDATE agent_registry SET status = 'error', last_seen = ? WHERE id = ?",
                (timestamp, agent_id),
            )
            await db.commit()
        return {"status": "error", "message": str(e)}


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

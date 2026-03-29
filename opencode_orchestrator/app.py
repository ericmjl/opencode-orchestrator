# ruff: noqa: E402
import logging
import os
import random
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from opencode_orchestrator.models import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await recover_stale_tasks()
    yield


async def recover_stale_tasks():
    from opencode_orchestrator.models import get_db, now

    async for db in get_db():
        rows = await db.execute("SELECT id FROM tasks WHERE status = 'running'")
        stale = await rows.fetchall()
        if stale:
            timestamp = now()
            for row in stale:
                task_id = row[0]
                await db.execute(
                    "UPDATE tasks SET status = 'created', updated_at = ? WHERE id = ?",
                    (timestamp, task_id),
                )
                await db.execute(
                    "UPDATE sessions SET status = 'completed', ended_at = ? WHERE task_id = ? AND status = 'running'",
                    (timestamp, task_id),
                )
            await db.commit()
            logging.getLogger(__name__).info(
                f"Recovered {len(stale)} stale running tasks on startup"
            )


app = FastAPI(title="OpenCode Orchestrator", version="0.1.0", lifespan=lifespan)

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

from opencode_orchestrator.routers import projects, tasks, sessions, agents, worktrees
from opencode_orchestrator.routers.pages import pages_router

app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(tasks.router, prefix="/api/projects", tags=["tasks"])
app.include_router(sessions.router, prefix="/api/projects", tags=["sessions"])
app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(worktrees.router, prefix="/api/projects", tags=["worktrees"])
app.include_router(pages_router, tags=["pages"])


@app.get("/")
async def root(request: Request):
    return RedirectResponse(url="/projects", status_code=302)


if __name__ == "__main__":
    port = int(os.environ.get("OC_PORT", random.randint(8000, 9000)))
    print(f"Starting server on http://127.0.0.1:{port}")
    uvicorn.run("opencode_orchestrator.app:app", host="127.0.0.1", port=port, reload=True)

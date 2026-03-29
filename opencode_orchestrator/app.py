import logging
import random
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from opencode_orchestrator.models import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="OpenCode Orchestrator", version="0.1.0", lifespan=lifespan)

import os

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

from fastapi.responses import RedirectResponse
from fastapi import Request


@app.get("/")
async def root(request: Request):
    return RedirectResponse(url="/projects", status_code=302)


if __name__ == "__main__":
    port = random.randint(8000, 9000)
    print(f"Starting server on http://127.0.0.1:{port}")
    uvicorn.run("opencode_orchestrator.app:app", host="127.0.0.1", port=port, reload=True)

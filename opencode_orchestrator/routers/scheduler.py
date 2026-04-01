import json
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from opencode_orchestrator.models import get_db, row_to_dict

router = APIRouter()

SCHEDULER_DIR = Path.home() / ".config" / "opencode" / "scheduler" / "scopes"


def find_scope_for_path(workdir: str) -> Path | None:
    target = Path(workdir).resolve()
    if not SCHEDULER_DIR.exists():
        return None
    for scope_dir in SCHEDULER_DIR.iterdir():
        if not scope_dir.is_dir():
            continue
        jobs_dir = scope_dir / "jobs"
        if not jobs_dir.exists():
            continue
        for job_file in jobs_dir.glob("*.json"):
            try:
                with open(job_file) as f:
                    job = json.load(f)
                    job_workdir = Path(job.get("workdir", "")).resolve()
                    if job_workdir == target:
                        return jobs_dir
            except Exception:
                continue
    return None


def normalize_path(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    return p.resolve()


class JobCreate(BaseModel):
    name: str
    prompt: str
    schedule: str
    model: str | None = None
    workdir: str
    title: str | None = None


class JobUpdate(BaseModel):
    name: str | None = None
    prompt: str | None = None
    schedule: str | None = None
    model: str | None = None
    title: str | None = None


def load_job(scope_dir: Path, slug: str) -> dict | None:
    job_file = scope_dir / f"{slug}.json"
    if not job_file.exists():
        return None
    with open(job_file) as f:
        return json.load(f)


def list_jobs_for_scope(scope_dir: Path) -> list[dict]:
    jobs = []
    if not scope_dir.exists():
        return jobs
    for job_file in scope_dir.glob("*.json"):
        with open(job_file) as f:
            jobs.append(json.load(f))
    return sorted(jobs, key=lambda j: j.get("name", ""))


def is_job_running(slug: str, scope_dir: Path) -> bool:
    lock_dir = scope_dir.parent / "locks"
    if lock_dir.exists():
        lock_file = lock_dir / f"{slug}.json"
        if lock_file.exists():
            return True
    runs_dir = scope_dir.parent / "runs"
    if runs_dir.exists():
        run_file = runs_dir / f"{slug}.jsonl"
        if run_file.exists():
            try:
                with open(run_file) as f:
                    for line in f:
                        if line.strip():
                            run = json.loads(line)
                            if run.get("status") == "running" or "finishedAt" not in run:
                                return True
            except Exception:
                pass
    return False


@router.get("/projects/{project_id}/jobs")
async def list_jobs(project_id: str):
    async for db in get_db():
        proj = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
        project = await proj.fetchone()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        p = row_to_dict(project)

    workdir = p["path"]
    scope_dir_obj = find_scope_for_path(workdir)
    jobs = list_jobs_for_scope(scope_dir_obj) if scope_dir_obj else []

    return [
        {
            "name": j.get("name"),
            "slug": j.get("slug"),
            "schedule": j.get("schedule"),
            "workdir": j.get("workdir"),
            "model": j.get("run", {}).get("model"),
            "title": j.get("run", {}).get("title"),
            "prompt": j.get("prompt"),
            "lastRunAt": j.get("lastRunAt"),
            "lastRunStatus": j.get("lastRunStatus"),
            "lastRunExitCode": j.get("lastRunExitCode"),
            "createdAt": j.get("createdAt"),
            "updatedAt": j.get("updatedAt"),
            "isRunning": is_job_running(j.get("slug"), scope_dir_obj),
        }
        for j in jobs
    ]


@router.get("/projects/{project_id}/jobs/{slug}")
async def get_job(project_id: str, slug: str):
    async for db in get_db():
        proj = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
        project = await proj.fetchone()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        p = row_to_dict(project)

    workdir = p["path"]
    scope_dir_obj = find_scope_for_path(workdir)
    job = load_job(scope_dir_obj, slug)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    run_history = []
    runs_dir = scope_dir_obj.parent / "runs"
    if runs_dir.exists():
        for run_file in sorted(runs_dir.glob(f"{slug}-*.jsonl"), reverse=True)[:10]:
            with open(run_file) as f:
                for line in f:
                    if line.strip():
                        run_history.append(json.loads(line))

    logs = []
    logs_dir = (
        Path.home() / ".config" / "opencode" / "logs" / "scheduler" / scope_dir_obj.parent.name
    )
    if logs_dir.exists():
        for log_file in sorted(logs_dir.glob(f"{slug}.log"), reverse=True)[:1]:
            with open(log_file) as f:
                logs.append(f.read()[-5000:])

    return {
        "job": job,
        "run_history": run_history,
        "logs": logs,
    }


@router.post("/projects/{project_id}/jobs")
async def create_job(project_id: str, data: JobCreate):
    async for db in get_db():
        proj = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
        project = await proj.fetchone()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        p = row_to_dict(project)

    workdir = data.workdir or p["path"]
    workdir_path = normalize_path(workdir)
    slug = data.name.lower().replace(" ", "-")

    scope_dir_obj = find_scope_for_path(workdir)
    if not scope_dir_obj:
        project_slug = workdir_path.name.lower().replace(" ", "-").replace("_", "-")
        scope_dir_obj = SCHEDULER_DIR / f"{project_slug}" / "jobs"
        scope_dir_obj.mkdir(parents=True, exist_ok=True)

    job_file = scope_dir_obj / f"{slug}.json"
    if job_file.exists():
        raise HTTPException(status_code=409, detail="Job already exists")

    job_data = {
        "name": data.name,
        "slug": slug,
        "prompt": data.prompt,
        "schedule": data.schedule,
        "workdir": str(normalize_path(workdir)),
        "createdAt": "2026-03-29T00:00:00Z",
        "updatedAt": "2026-03-29T00:00:00Z",
        "invocation": {
            "command": "/Users/ericmjl/.opencode/bin/opencode",
            "args": [
                "run",
                "--model" if data.model else None,
                data.model,
                "--title" if data.title else None,
                data.title or data.name,
                "--",
                data.prompt,
            ],
        },
        "run": {
            "model": data.model or "zai-coding-plan/glm-5.1",
            "prompt": data.prompt,
            "title": data.title or data.name,
        },
    }
    job_data["invocation"]["args"] = [a for a in job_data["invocation"]["args"] if a]

    with open(job_file, "w") as f:
        json.dump(job_data, f, indent=2)

    return {"status": "created", "slug": slug}


@router.patch("/projects/{project_id}/jobs/{slug}")
async def update_job(project_id: str, slug: str, data: JobUpdate):
    async for db in get_db():
        proj = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
        project = await proj.fetchone()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        p = row_to_dict(project)

    workdir = p["path"]
    scope_dir_obj = find_scope_for_path(workdir)
    job = load_job(scope_dir_obj, slug)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if data.name is not None:
        job["name"] = data.name
    if data.prompt is not None:
        job["prompt"] = data.prompt
        job["run"]["prompt"] = data.prompt
    if data.schedule is not None:
        job["schedule"] = data.schedule
    if data.model is not None:
        job["run"]["model"] = data.model
    if data.title is not None:
        job["run"]["title"] = data.title

    job["updatedAt"] = "2026-03-29T00:00:00Z"

    with open(scope_dir_obj / f"{slug}.json", "w") as f:
        json.dump(job, f, indent=2)

    return {"status": "updated", "slug": slug}


@router.delete("/projects/{project_id}/jobs/{slug}")
async def delete_job(project_id: str, slug: str):
    async for db in get_db():
        proj = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
        project = await proj.fetchone()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        p = row_to_dict(project)

    workdir = p["path"]
    scope_dir_obj = find_scope_for_path(workdir)
    job = load_job(scope_dir_obj, slug)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job_file = scope_dir_obj / f"{slug}.json"
    job_file.unlink()

    return {"status": "deleted", "slug": slug}


@router.post("/projects/{project_id}/jobs/{slug}/run")
async def run_job_now(project_id: str, slug: str):
    async for db in get_db():
        proj = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
        project = await proj.fetchone()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        p = row_to_dict(project)

    workdir = p["path"]
    scope_dir_obj = find_scope_for_path(workdir)
    job = load_job(scope_dir_obj, slug)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {"status": "triggered", "slug": slug}


@router.get("/running-jobs")
async def list_running_jobs():
    running = []

    if not SCHEDULER_DIR.exists():
        return {"jobs": running}

    for scope_dir in SCHEDULER_DIR.iterdir():
        if not scope_dir.is_dir():
            continue
        jobs_dir = scope_dir / "jobs"
        if not jobs_dir.exists():
            continue
        lock_dir = scope_dir / "locks"
        runs_dir = scope_dir / "runs"

        for job_file in jobs_dir.glob("*.json"):
            try:
                with open(job_file) as f:
                    job = json.load(f)
                slug = job.get("slug")

                is_running = False
                if lock_dir.exists():
                    lock_file = lock_dir / f"{slug}.json"
                    if lock_file.exists():
                        is_running = True

                if not is_running and runs_dir.exists():
                    run_file = runs_dir / f"{slug}.jsonl"
                    if run_file.exists():
                        with open(run_file) as f:
                            for line in f:
                                if line.strip():
                                    run = json.loads(line)
                                    if run.get("status") == "running":
                                        is_running = True
                                        break

                if is_running:
                    running.append(
                        {
                            "name": job.get("name"),
                            "slug": slug,
                            "workdir": job.get("workdir"),
                            "schedule": job.get("schedule"),
                            "model": job.get("run", {}).get("model"),
                            "title": job.get("run", {}).get("title"),
                            "source": "scheduler",
                        }
                    )
            except Exception:
                continue

    return {"jobs": running}

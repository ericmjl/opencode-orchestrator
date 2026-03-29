import aiosqlite
import datetime
from pathlib import Path
from typing import Any, AsyncGenerator

DATABASE_PATH = Path.home() / ".config" / "opencode-orchestrator" / "orchestrator.db"
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)


async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


async def init_db() -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        await db.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                has_git INTEGER NOT NULL DEFAULT 0,
                vcs_url TEXT,
                default_branch TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS worktrees (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                branch_name TEXT NOT NULL,
                path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS agent_registry (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                command TEXT NOT NULL,
                port INTEGER NOT NULL,
                cwd TEXT,
                capabilities TEXT,
                status TEXT NOT NULL DEFAULT 'offline',
                config TEXT,
                pid INTEGER,
                last_seen TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                worktree_id TEXT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'created',
                assigned_agent_id TEXT,
                priority INTEGER NOT NULL DEFAULT 0,
                schedule_cron TEXT,
                schedule_enabled INTEGER NOT NULL DEFAULT 0,
                schedule_id TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 3,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (worktree_id) REFERENCES worktrees(id) ON DELETE SET NULL,
                FOREIGN KEY (assigned_agent_id) REFERENCES agent_registry(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS task_messages (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS task_logs (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                event TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT,
                details TEXT,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                worktree_id TEXT,
                task_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'spawned',
                pid INTEGER,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                output_log_path TEXT,
                exit_code INTEGER,
                error_message TEXT,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (worktree_id) REFERENCES worktrees(id) ON DELETE SET NULL,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (agent_id) REFERENCES agent_registry(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS questions (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                question_type TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                answered_at TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_worktrees_project ON worktrees(project_id);
            CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_task_messages_task ON task_messages(task_id);
            CREATE INDEX IF NOT EXISTS idx_task_logs_task ON task_logs(task_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_task ON sessions(task_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
            CREATE INDEX IF NOT EXISTS idx_questions_session ON questions(session_id);
            CREATE INDEX IF NOT EXISTS idx_questions_task ON questions(task_id);
            CREATE INDEX IF NOT EXISTS idx_questions_status ON questions(status);
        """)

        try:
            await db.execute("ALTER TABLE tasks ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass

        await db.commit()


def row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    result = dict(row)
    for key, value in result.items():
        if isinstance(value, str) and (value.startswith("{") or value.startswith("[")):
            try:
                import json

                result[key] = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                pass
    return result


def now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()

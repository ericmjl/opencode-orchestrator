# Implementation Status

OpenCode Orchestrator

 High-Level Design: reference: https://github.com/ericmjl/opencode-orchestrator/blob/main/docs/high-level-design.md)

 **Created**: 2026-03-28
 **Last updated**: 2026-03-29

## What Worksed

 v0.1.0 — Initial Coding Agent + Task Management

This document tracks what has been built, the current state of the app, and what still needs to be done.

 It also serves as a handoff for the the next coding agent.

 Please read `docs/high-level-design.md` for full context before continuing.

 This doc references the the architecture decisions and data model.

## How to Run

 Server

```bash
pixi run python -m opencode_orchestrator.app
```

Server runs on http://127.0.01:8627.

 Agent (opencode) runs on port 4000):

```bash
opencode serve --port 4000
```
## Relevant files / directories

```
opencode_orchestrator/
├── app.py                          # FastAPI entry point, logging config
 + uvicorn
├── models/
│   ├── database.py              # SQLite schema, get_db(), row_to_dict(), now()
│   └── __init__.py
├── routers/
│   ├── tasks.py                    # Task CRUD, agent message sending (background task)
 SSE stream endpoint
 polling endpoint
 │   ├── pages.py                    # Server-rendered HTML pages (Jinja2)
  │   ├── agents.py                # Agent registry CRUD + heartbeat
│   ├── projects.py              # Project CRUD
│   ├── sessions.py              # Session management
│   └── worktrees.py             # Worktree management
├── templates/
│   ├── base.html
│   └── pages/
│       └── task-detail.html        # Task detail page with chat UI
 polling logic
├── static/
│   └── styles.css                # Black/white/grayscale theme
└── /tmp/orchestrator.log               # Server log output
```

## What works

 end-to-end

### Task Lifecycle

1. User creates a task → task inserted as `created`
 in DB
2. If agent available → `POST /agent/{port}/session` → opencode creates a session
 `ses_xxx`
3. Task set to `running`, session inserted, user message stored in DB
4. Background task fires: `POST /agent/session/{id}/message` with the task description
5. Agent streams response; `httpx` streaming reads captures body
 response parsed, stored as assistant message, task set to `completed`

### Follow-up Message Flow (what we fixed)
1. User types message in task detail chat input → `send-message` endpoint
2. `send-message` sets task to `running`, inserts user message in DB
3. `send-message` fires background task (returns `{"status": "ok"}` immediately)
4. Frontend polls `GET /messages` every 1 second
5. When assistant message appears in DB, poll renders it and stops polling

 task badge flips to `completed`

## Completed

 ✅
- Project CRUD (create, list, detail, delete)
- Task CRUD (create, list, detail, run, delete, send-message)
- Agent registration (register, deregister, heartbeat)
- Session management (list, cancel)
- Worktree management (create, list, delete)
- Frontend pages (project list, task list, task detail with chat)
- Task auto-execution on creation (creates op session, sends to agent)
 background)
- Agent message passing with streaming response read (httpx `client.stream()` + `aiter_bytes()`)
- Context preservation across follow-up messages (session stays `running` after reply)
 so next message reuses same session)
- Status badge updates (running/completed) without page refresh (polling-based)
- Optimistic user message rendering (appears immediately on send)
- Session reuse for existing `running` sessions for follow-up messages on same task)

## Known Bugs / Issues

 Need Fixing

### 1. Agent sessions get stuck (unresponsive)
After many messages exchanges on the session, the agent stops responding to `/session/{id}/message`. The `httpx` streaming read hangs forever with 0 bytes received.

 Root cause unknown (possibly context window exhaustion on opencode side but the response body never arrives. Temporary workaround: close the session in DB (`status = completed`) and let `send-message` create a fresh session.

### 2. Duplicate user messages in chat
The polling-based JS uses `knownMessageCount` (count-based dedup) to skip user messages that were already rendered optimistically. This works in most cases, but may fail if messages are DB have non-sequential timestamps ordering vs server-rendered order. Not yet confirmed.

 needs testing with edge cases.

 **File**: `opencode_orchestrator/templates/pages/task-detail.html:206-207`

### 3. Task status may show stale `running` forever
If background task crashes (e.g. from server reload via `asyncio.CancelledError`), the task stays `running` in DB but but no cleanup mechanism exists to recover from this. Need: add a startup task that checks for stale `running` tasks (older than N minutes) and reset to `created`.

### 4. SSE endpoint still exists but unused
The `GET /stream` SSE endpoint (`opencode_orchestrator/routers/tasks.py:338-378`) is still registered and functional. It was replaced by polling in the frontend but but the endpoint itself still exists and It should be either removed or kept for a fallback. The SSE endpoint has issues:
 replays old messages on reconnect, uses UUID string comparison for dedup (broken, fixed with timestamp comparison but that also broke), never worked reliably with opencode agent (agent returns 200 but streams body forever).

## What Needs to Be Done Next

 Next Steps

### Priority 1: Fix known bugs above
- **Stale `running` task recovery**: Add a startup task or scans for tasks with `status = running` and `updated_at` older than 5 minutes, reset to `created` or mark as `failed`. This prevents tasks from being stuck in `running` forever if the background task crashes.
- **Agent session stuck detection**: Before reusing a `running` session, probe the agent with a lightweight request (e.g. `GET /session/{id}`) to verify it the session still exists and is responsive. If not, create a fresh session.
 Currently, if the opencode session dies or becomes unresponsive, messages are silently lost.
- **Remove unused SSE endpoint**: The `GET /{project_id}/tasks/{task_id}/stream` endpoint in `tasks.py` is dead code. Remove the `task_status` event logic since the SSE generator. The frontend no longer uses it SSE.
 keeping it endpoint around adds confusion.

 Remove `since` param from route signature too.

 **File**: `opencode_orchestrator/routers/tasks.py:338-378`

### Priority 2: Testing
 Fix bugs, then write tests to Verify:
- Full message lifecycle (create task → agent responds → follow-up message → agent responds)
- Status badge transitions (completed → running → completed)
- Duplicate message prevention
- Stale session recovery
- Context preservation across messages in same session
 Use the test framework in `tests/` directory (see `tests/test_e2e.py` and `tests/test_frontend.py` as starting points).

 Agent mock server on port 4000 that required.

### Priority 3: Architecture improvements
- **Pixi task runner**: Add a `pixi task` for run the orchestrator server so so `pixi task run` for tests. Currently started manually.
- **Config file**: Move hardcoded port (8627) and agent port (4000) to a config file or environment variables. Current setup is fragile.
- **Error handling in background task**: The `send_task_to_agent_background` function has bare `except` blocks with logging only. Should add retry logic with exponential backoff for transient failures.
- **Message timestamp ordering**: Verify that `now()` (using `datetime.utcnow()().isoformat()`) produces consistent ordering. This was flagged as deprecated in Python 3.12+.

### Priority 4: Future features (from HLD, not yet implemented)
- Worktree management (create/list/delete worktrees via UI)
- Scheduler (cron-based recurring tasks)
- Tailscale integration (remote access)
- Multi-user/team features
- EARS (event-driven architecture)

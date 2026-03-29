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

- [x] Project CRUD (create, list, detail, delete)
- [x] Task CRUD (create, list, detail, run, delete, send-message)
- [x] Agent registration (register, deregister, Heartbeat)
- [x] Session management (List, Cancel)
- [x] Worktree management (Create, List, Delete)
- [x] Frontend pages (Project List, Task List, Task Detail with chat)
- [x] Task auto-execution on creation (Creates Agent session, Sends to agent in background)
- [x] Agent message passing with streaming response read (httpx `client.stream()` + `aiter_bytes()`)
- [x] Context preservation across follow-up messages (Session stays `running` after reply)
- [x] Status badge updates (Running/Completed) without page refresh (polling-based)
- [x] Optimistic user Message rendering (Appears immediately on Send)
- [x] Session Reuse for existing `Running` sessions for follow-up messages
- [x] Stale Task Recovery on Startup (Reset `Running` tasks back to `Created` on server restart)
- [x] Agent Session Liveness Probe (GET `/session/{id}` before reusing)
- [x] Polling-based message delivery (replaced SSE)
- [x] Count-based dedup (`knownMessageCount`) to avoid duplicate messages
- [x] Dead SSE endpoint removed from `tasks.py`

## Known Bugs / Issues

### 1. Agent sessions can become unresponsive after many messages

After several exchanges on the same session, the agent may stop responding to `/session/{id}/message`.
 The httpx streaming read hangs forever. The liveness probe (`probe_agent_session`) was mitigate this by detecting dead sessions before reusing them.
 If you probe fails, a new session is created.

### 2. Polling timeout (no Max Timeout)

The `setInterval` polling runs indefinitely until an assistant reply arrives. If the agent never responds (e.g. crashes), the polling continues forever.
 A max timeout (e.g. 2 minutes) should be added to stop polling and re-enable the Send button.

### 3. `datetime.utcnow()` is Deprecated

`now()` in `models/database.py` uses `datetime.datetime.utcnow()` which is deprecated in Python 3.12+.
 Should be updated to `datetime.now(datetime.UTC)`.

## What Needs to Be Done Next

### Priority 1: Fix Known Bugs

- **Add Polling Timeout in JS**: Stop polling after 2 minutes and re-enable Send button.
  **File**: `opencode_orchestrator/templates/pages/task-detail.html` (sendMessage function)
- **Fix `datetime.utcnow()` deprecation**: Update `now()` in `models/database.py`.
  **File**: `opencode_orchestrator/models/database.py`

### Priority 2: Testing

Write tests to verify:
- Full message lifecycle (Create task → Agent responds → Follow-up message → Agent responds)
- Status badge transitions (Completed → Running → Completed)
- Duplicate message prevention
- Stale session recovery
- Context preservation across messages in same session

Test framework already in `tests/`. Agent mock server on port 4000 required.

### Priority 3: Architecture Improvements

- **Pixi task runner**: Add a `pixi task` to run the orchestrator server.
- **Config file**: Move hardcoded ports (8627, 4000) to config or env vars.
- **Error handling**: Add retry logic with exponential backoff in `send_task_to_agent_background`.
- **Message timestamp ordering**: Verify `now()` produces consistent ordering.

### Priority 4: Future Features (from HLD, Not Yet Implemented)

- Worktree management UI
- Scheduler (cron-based recurring tasks)
- Tailscale integration (remote access)
- Multi-user/team features

### Priority 4: Future features (from HLD, not yet implemented)
- Worktree management (create/list/delete worktrees via UI)
- Scheduler (cron-based recurring tasks)
- Tailscale integration (remote access)
- Multi-user/team features
- EARS (event-driven architecture)

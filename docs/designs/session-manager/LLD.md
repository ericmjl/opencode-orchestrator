# Session Manager - Low-Level Design

**Created**: 2026-03-28
**HLD Link**: ../../high-level-design.md

## Overview

The Session Manager owns the lifecycle of agent sessions — from launch to termination. It manages git worktrees (for git projects), spawns agent processes via the ACP Gateway, captures output in real-time, and monitors session health via heartbeats.

## Context

Per the HLD, each agent session operates in its own git worktree (when git is available). The Session Manager coordinates with the Task Engine (which decides *what* to run) and the ACP Gateway (which handles *how* agents communicate). The Session Manager is responsible for the *where* and *when* — the filesystem environment and process lifecycle.

## UI Sketch — Session Monitor

```
┌─ OpenCode Orchestrator ──────────────────────────────────────────────────┐
│ Projects > my-project > Sessions                                         │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Active Sessions (2)                                          [▶ New]   │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │ ● fix-login-bug          opencode     running    00:12:34         │  │
│  │   worktree: wt-fix-login   agent: gpt-4.1   task: #3             │  │
│  │   [View Output] [Pause] [Cancel]                                  │  │
│  ├────────────────────────────────────────────────────────────────────┤  │
│  │ ● add-search-api         claude       running    00:05:21         │  │
│  │   worktree: wt-search      agent: sonnet    task: #7             │  │
│  │   [View Output] [Pause] [Cancel]                                  │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  Recent Sessions                                                         │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │ ✓ update-readme          opencode     completed  00:02:15         │  │
│  │   worktree: wt-readme     task: #1     finished 2 min ago         │  │
│  │   [View Output] [View Diff]                                       │  │
│  ├────────────────────────────────────────────────────────────────────┤  │
│  │ ✗ refactor-auth          codex        failed     00:08:44         │  │
│  │   worktree: wt-auth       task: #4     error: process exit 1      │  │
│  │   [View Output] [Retry]                                          │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

When the user clicks "View Output" on a running session:

```
┌─ OpenCode Orchestrator ──────────────────────────────────────────────────┐
│ Projects > my-project > Sessions > fix-login-bug          [◀ Back]      │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Session: fix-login-bug                                                  │
│  Agent: opencode (gpt-4.1)    Status: ● running    Duration: 00:12:47   │
│  Worktree: wt-fix-login       Task: #3 Fix login bug                    │
│  PID: 48291                                                              │
│                                                                          │
│  ┌─ Agent Output ────────────────────────────────────────────────────┐  │
│  │                                                                    │  │
│  │  I'll start by examining the login handler to understand the       │  │
│  │  current implementation.                                          │  │
│  │                                                                    │  │
│  │  > reading src/auth/login.py                                      │  │
│  │                                                                    │  │
│  │  I can see the issue. The email validation regex doesn't handle    │  │
│  │  plus signs in the local part. I'll fix this by updating the       │  │
│  │  validation pattern.                                              │  │
│  │                                                                    │  │
│  │  > editing src/auth/validators.py                                 │  │
│  │                                                                    │  │
│  │  Now let me write a test for this case.                            │  │
│  │                                                                    │  │
│  │  > writing tests/test_auth_validators.py                          │  │
│  │                                                                    │  │
│  │  █  (streaming...)                                                 │  │
│  │                                                                    │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌─ Conversation ────────────────────────────────────────────────────┐  │
│  │                                                                    │  │
│  │  [user]    Fix the login bug where emails with + signs fail        │  │
│  │  [agent]   Found the issue in validators.py, fixing now...        │  │
│  │  [user]    Also check the API endpoint handler                    │  │
│  │  [agent]   Good call, checking src/auth/api.py too...             │  │
│  │                                                                    │  │
│  │  ┌─────────────────────────────────────────────────────────────┐  │  │
│  │  │ Send a message...                                    [Send] │  │  │
│  │  └─────────────────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  [Pause]  [Cancel]  [View Diff]  [Open Worktree in Editor]              │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

## Session Lifecycle

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌───────────┐
│ spawned  │────→│ running  │────→│ stopping │────→│ completed │
└──────────┘     └────┬─────┘     └──────────┘     └───────────┘
                      │
                      │ crash / timeout
                      ▼
                 ┌──────────┐
                 │  failed  │
                 └──────────┘
```

States:
- `spawned` — Process launched, awaiting first ACP handshake
- `running` — Agent is active, output streaming
- `stopping` — Graceful shutdown initiated (SIGTERM sent)
- `completed` — Agent exited normally
- `failed` — Agent crashed or was killed (SIGKILL after timeout)

## Data Models

### Worktree

| Field | Type | Description |
|-------|------|-------------|
| id | String (UUID) | Primary key |
| project_id | String (UUID) | Foreign key to Project |
| branch_name | String | Git branch name for this worktree |
| path | String (absolute path) | Filesystem path to the worktree directory |
| status | Enum | `active`, `merged`, `archived` |
| created_at | Timestamp | Creation time |

Worktrees are only created for git projects. For non-git projects, sessions run directly in the project directory and no Worktree record is created.

### Session

| Field | Type | Description |
|-------|------|-------------|
| id | String (UUID) | Primary key |
| project_id | String (UUID) | Foreign key to Project |
| worktree_id | String (UUID, nullable) | Foreign key to Worktree |
| task_id | String (UUID) | Foreign key to Task |
| agent_id | String (UUID) | Foreign key to AgentRegistry |
| status | Enum | `spawned`, `running`, `stopping`, `completed`, `failed` |
| pid | Integer (nullable) | OS process ID |
| started_at | Timestamp | When the agent process was launched |
| ended_at | Timestamp (nullable) | When the session terminated |
| output_log_path | String | Path to the session's output log file |
| exit_code | Integer (nullable) | Process exit code |
| error_message | String (nullable) | Error details if failed |

## API Contracts

### Session Management

| Endpoint | Method | Request | Response |
|----------|--------|---------|----------|
| `/api/projects/{id}/sessions` | GET | query: `status` | `SessionListResponse` |
| `/api/projects/{id}/sessions/{sid}` | GET | — | `SessionDetailResponse` |
| `/api/projects/{id}/sessions/{sid}/cancel` | POST | — | `SessionResponse` |

**Note**: SSE streaming, pause/resume, and diff endpoints are not implemented in v1.

### Worktree Management

| Endpoint | Method | Request | Response |
|----------|--------|---------|----------|
| `/api/projects/{id}/worktrees` | GET | — | `WorktreeListResponse` |
| `/api/projects/{id}/worktrees` | POST | `WorktreeCreateRequest` | `WorktreeResponse` (201) |
| `/api/projects/{id}/worktrees/{wid}` | DELETE | — | 204 |

**POST /api/projects/{id}/worktrees** — `WorktreeCreateRequest`:
```json
{
  "branch_name": "fix-login-bug",
  "base_ref": "main"
}
```

`base_ref` is optional, defaults to the project's default branch.

### Session Output (Not Implemented in v1)

SSE streaming for real-time output is not implemented. Future versions will support:
- `GET /api/projects/{id}/sessions/{sid}/output` — SSE stream for real-time output
- Agent output can be viewed in task detail page via TaskMessages

## Session Launch Flow

When the Task Engine transitions a task to `running`, it calls the Session Manager:

```
┌───────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ Task      │───→│  Create      │───→│  Launch      │───→│  Start       │
│ Engine    │    │  worktree    │    │  agent       │    │  heartbeat   │
│ (start)   │    │  (if git)    │    │  process     │    │  monitor     │
└───────────┘    └──────────────┘    └──────────────┘    └──────────────┘
                       │                    │
                       ▼                    ▼
                 ┌──────────┐        ┌──────────────┐
                 │ git      │        │ ACP Gateway  │
                 │ worktree │        │ subprocess   │
                 │ add      │        │ spawn        │
                 └──────────┘        └──────────────┘
```

1. **Create worktree** (git projects only): `git worktree add <path> -b <branch_name> <base_ref>`. The worktree path is `<project_path>/.opencode/worktrees/<branch_name>`.
2. **Spawn agent**: The ACP Gateway launches the agent process in the worktree directory. Returns PID and stdio pipes.
3. **Record session**: Write Session row to SQLite with `spawned` status.
4. **Await handshake**: First ACP message from agent transitions session to `running`.
5. **Start heartbeat**: Periodic check (configurable interval, default 30s) that the agent process is alive.

## Session Shutdown

1. **Graceful**: Send SIGTERM to the agent process. Wait up to `graceful_timeout` seconds (default: 10s).
2. **Force**: If process hasn't exited after graceful timeout, send SIGKILL.
3. **Cleanup**: Update Session record, set `ended_at` and `exit_code`, transition task status.
4. **Worktree**: Worktree is NOT automatically removed. User can merge or delete manually.

## Heartbeat and Health Monitoring (Not Implemented in v1)

Background heartbeat monitoring is not implemented. Future versions will include:
- Periodic check (configurable interval, default 30s) that the agent process is alive
- If process is dead, transitions session to `failed`, notifies Task Engine
- If no heartbeat received within `heartbeat_timeout` (default: 120s), marks session as unresponsive in the UI

## Error Handling

| Code | Condition | Message |
|------|-----------|---------|
| 404 | Session not found | "Session '{sid}' not found" |
| 404 | Worktree not found | "Worktree '{wid}' not found" |
| 409 | Worktree has active session | "Worktree '{wid}' already has a running session" |
| 409 | Not a git project | "Cannot create worktrees for non-git projects" |
| 500 | Agent spawn failed | "Failed to launch agent: <error>" |

## Edge Cases

1. **Orphaned worktrees**: If the orchestrator crashes, worktrees remain on disk. On startup, Session Manager reconciles: checks for sessions that were `running` and marks them `failed`, cleans up any stray state.
2. **Worktree directory already exists**: Fail with 409. User must clean up manually or choose a different branch name.
3. **Non-git project sessions**: No worktree created. The agent's working directory is the project path directly. No `diff` endpoint available.
4. **Multiple sessions on same task (scheduled tasks)**: Each scheduled run creates a new Session record. The task's `retry_count` is independent of the number of sessions.
5. **Agent outputs binary/large content**: Output log file is append-only text. Binary output is not captured; the SSE stream truncates lines longer than 10KB.
6. **Disk space exhaustion in worktree**: Not handled by Session Manager. The agent itself is responsible for not filling disk.

## Dependencies

- **SQLite**: Session and Worktree storage
- **Agent Registry**: Agent process spawning and communication
- **Task Engine**: Session status updates flow back to task state
- **git (CLI)**: Worktree creation and cleanup (git projects only)
- **asyncio**: Subprocess management
- **pathlib**: Worktree path construction

## Design Decisions

### Why worktrees under `.opencode/worktrees/`?

Keeps orchestrator artifacts inside the project directory but out of the user's way. The `.opencode` directory is a natural home (already used by OpenCode for config). The worktree name matches the branch name for easy identification.

### Why not auto-delete worktrees on session end?

The user may want to review the changes, merge them, or run another task in the same worktree. Auto-deletion risks losing work. The user can explicitly delete worktrees when they're done.

## Implementation Status

✅ Implemented (v0.1.0). List, get, cancel endpoints working. SSE streaming, heartbeat monitoring, and pause/resume not implemented yet.

## Requirements

- [Session Management EARS](./session-management-EARS.md)

## Related Documents

- [High-Level Design](../../high-level-design.md)
- [Task Engine LLD](../task-engine/LLD.md)
- [ACP Agent Gateway LLD](../acp-gateway/LLD.md)
- [Project Management LLD](../project-management/LLD.md)

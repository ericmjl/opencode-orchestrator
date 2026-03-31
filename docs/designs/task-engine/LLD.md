# Task Engine - Low-Level Design

**Created**: 2026-03-28
**HLD Link**: ../../high-level-design.md

## Overview

The Task Engine is the core workflow engine of the orchestrator. Every unit of work is a **task ticket** — an atomic, trackable unit that can be assigned to an agent and monitored through its full lifecycle. The Task Engine manages task creation, assignment, guarded state transitions, conversation threads, and OpenCode synchronization.

## Context

Per the HLD, the task system is inspired by Paperclip's ticket model. Tasks live within a project and (when git is available) are associated with a worktree. The Task Engine coordinates with the Session Manager (to launch agents) and the Scheduler (to run recurring jobs).

## Task Lifecycle

```
                    ┌─────────┐
                    │ created │
                    └────┬────┘
                         │ auto-assign on creation
                         ▼
                    ┌─────────┐
                ┌───│ running │───┐
                │   └────┬────┘   │
                │        │        │ schedule (recurring)
                │        │        │
                │        │   ┌────┴────┐
                │        │   ▼         ▼
                │        │ ┌────────┐ ┌─────────┐
                │        │ │completed│ │ failed  │
                │        │ └────────┘ └────┬────┘
                │        │                 │ retry
                │        │                 ▼
                │        │           ┌─────────┐
                └───────┴──────────→│ running │
                    cancel           └─────────┘
                         │
                         ▼
                    ┌─────────┐
                    │cancelled│
                    └─────────┘
```

States:

- `created` — Task exists, not yet assigned to an agent
- `running` — Agent session is active
- `waiting_question` — Agent asked a question and is awaiting user response
- `waiting_permission` — Agent requested permission approval
- `completed` — Agent finished successfully
- `failed` — Agent failed; may be retried
- `cancelled` — User cancelled the task

**Note**: The v1 implementation simplifies the lifecycle by auto-assigning tasks to available agents upon creation. Tasks go directly from `created` to `running` when an agent is available.

## UI Sketch — Task Detail View

When a user clicks on a task card, they navigate to the task detail page:

```
┌─ OpenCode Orchestrator ──────────────────────────────────────────────────┐
│ Projects > my-project > Tasks > Fix login bug            [◀ Back]      │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Fix login bug                                                           │
│  Status: ● running      Created: 2026-03-29 10:00                      │
│                                                                          │
│  ┌─ Task Details ──────────────────────────────────────────────────────┐ │
│  │ Description:                                                        │ │
│  │ The login form returns 500 when email contains a plus sign. Fix   │ │
│  │ the validation to handle emails like user+tag@example.com           │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  ┌─ Agent ────────────────────────────────────────────────────────────┐ │
│  │ Name: opencode     Port: 4000     Status: ● available              │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  ┌─ Session ──────────────────────────────────────────────────────────┐ │
│  │ Session ID: 8fe8d359-bfcd-450c-98a9-74739877abd2                  │ │
│  │ Status: ● running    Started: 2026-03-29 10:05    PID: 48291     │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  ┌─ Session Console ─────────────────────────────────────────────────┐ │
│  │                                                                    │ │
│  │  [user] Fix the login bug...                                     │ │
│  │  [assistant] I'll start by examining the login handler...         │ │
│  │  > reading src/auth/login.py                                      │ │
│  │                                                                    │ │
│  │  ┌─────────────────────────────────────────────────────────────┐  │ │
│  │  │ Send a message...                                    [Send]  │  │ │
│  │  └─────────────────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  [Cancel Task]                                                          │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

The task detail page shows:
- Task information (title, description, status, timestamps)
- Agent information (name, port, status)
- Session information (session ID, status, PID)
- Interactive console to send messages to the agent and view responses

## Data Models

### Task

| Field | Type | Description |
|-------|------|-------------|
| id | String (UUID) | Primary key |
| project_id | String (UUID) | Foreign key to Project |
| worktree_id | String (UUID, nullable) | Foreign key to Worktree (git projects only) |
| title | String | Auto-generated from description (first 50 chars) |
| description | String | Full task prompt / instructions for the agent |
| status | Enum | `created`, `running`, `waiting_question`, `waiting_permission`, `completed`, `failed`, `cancelled` |
| assigned_agent_id | String (UUID, nullable) | Foreign key to AgentRegistry |
| priority | Integer | Deprecated (kept for compatibility, always 0) |
| schedule_cron | String (nullable) | Cron expression for recurring tasks, null for one-shot |
| schedule_enabled | Boolean | Whether the scheduled job is active |
| schedule_id | String (nullable) | OS scheduler job identifier |
| retry_count | Integer | Number of times this task has been retried |
| max_retries | Integer | Maximum retries before giving up (default: 3) |
| created_at | Timestamp | Task creation time |
| updated_at | Timestamp | Last state change |
| completed_at | Timestamp (nullable) | When task reached terminal state |

### TaskMessage

| Field | Type | Description |
|-------|------|-------------|
| id | String (UUID) | Primary key |
| task_id | String (UUID) | Foreign key to Task |
| role | Enum | `user`, `agent`, `system` |
| content | String | Message body |
| source | Enum | `orchestrator`, `opencode_sqlite` |
| opencode_message_id | String (nullable) | Message id from OpenCode sqlite for deduplication |
| metadata | JSON (nullable) | Token usage, tool calls, duration, etc. |
| timestamp | Timestamp | Message time |

### Message Ingestion Ownership

The Task Engine uses explicit write ownership to prevent duplicate messages:

1. **User messages** are persisted by the orchestrator send path (`source=orchestrator`).
2. **Assistant messages** are persisted only by OpenCode sqlite sync (`source=opencode_sqlite`).
3. The HTTP stream parsing path may inspect assistant payloads for waiting states (questions/permissions), but it shall not insert assistant `TaskMessage` rows.
4. Deduplication for imported assistant history is keyed by `(task_id, opencode_message_id)` so repeated sync passes remain idempotent.

### TaskLog

| Field | Type | Description |
|-------|------|-------------|
| id | String (UUID) | Primary key |
| task_id | String (UUID) | Foreign key to Task |
| event | String | State transition or event name |
| from_status | String (nullable) | Previous status |
| to_status | String (nullable) | New status |
| details | JSON (nullable) | Additional context |
| timestamp | Timestamp | Event time |

## API Contracts

### Task CRUD

| Endpoint | Method | Request | Response |
|----------|--------|---------|----------|
| `/api/projects/{id}/tasks` | GET | query params: `status`, `assigned_agent_id` | `TaskListResponse` |
| `/api/projects/{id}/tasks` | POST | `TaskCreateRequest` | `TaskResponse` (201) |
| `/api/projects/{id}/tasks/{taskId}` | GET | — | `TaskDetailResponse` |
| `/api/projects/{id}/tasks/{taskId}` | PATCH | `TaskUpdateRequest` | `TaskResponse` |
| `/api/projects/{id}/tasks/{taskId}` | DELETE | — | 204 |

### Task Actions

| Endpoint | Method | Request | Response |
|----------|--------|---------|----------|
| `/api/projects/{id}/tasks/{taskId}` | GET | — | `TaskDetailResponse` (includes session and agent info) |
| `/api/projects/{id}/tasks/{taskId}/run` | POST | — | Starts task with available agent |
| `/api/projects/{id}/tasks/{taskId}/send-message` | POST | `{"message": "..."}` | Sends message to agent session |
| `/api/projects/{id}/tasks/{taskId}/mark-read` | POST | — | Clears unread badge for task |
| `/api/projects/{id}/tasks/{taskId}/messages-fragment` | GET | — | HTMX HTML snippet for message thread |
| `/api/projects/{id}/tasks/{taskId}/status-fragment` | GET | — | HTMX HTML snippet for status badge |
| `/api/projects/{id}/tasks/{taskId}/prompts-fragment` | GET | — | HTMX HTML snippet for pending prompts |
| `/api/projects/{id}/tasks/model-options-fragment` | GET | — | HTMX HTML snippet for task model picker |

**Note**: Task cancellation is handled by cancelling the associated session via `/api/projects/{id}/sessions/{sessionId}/cancel`.

### Task Messages

| Endpoint | Method | Request | Response |
|----------|--------|---------|----------|
| `/api/projects/{id}/tasks/{taskId}/messages` | GET | — | `MessageListResponse` |
| `/api/projects/{id}/tasks/{taskId}/messages` | POST | `MessageCreateRequest` | `MessageResponse` (201) |

### Task Schedule

| Endpoint | Method | Request | Response |
|----------|--------|---------|----------|
| `/api/projects/{id}/tasks/{taskId}/schedule` | PUT | `ScheduleRequest` | `TaskResponse` |
| `/api/projects/{id}/tasks/{taskId}/schedule` | DELETE | — | `TaskResponse` |
| `/api/projects/{id}/tasks/{taskId}/run` | POST | — | `TaskResponse` |

### Key Request/Response Shapes

**POST /api/projects/{id}/tasks** — `TaskCreateRequest`:

```json
{
  "description": "The login form returns 500 when email contains a plus sign...",
  "worktree_id": "optional-uuid",
  "model": "openai/gpt-5.4"
}
```

**Note**: The `title` field is auto-generated from the description (first 50 characters + "..." if longer). The `priority` field is no longer used in v1 — tasks are ordered by creation time.
The `model` field is optional. When set as `provider/model`, the Task Engine maps it to OpenCode session fields (`providerID`, `modelID`) when creating a session.

**POST /api/projects/{id}/tasks/{taskId}/assign** — `AssignRequest`:

```json
{
  "agent_id": "uuid-of-opencode-agent"
}
```

**PUT /api/projects/{id}/tasks/{taskId}/schedule** — `ScheduleRequest`:

```json
{
  "cron": "0 9 * * *",
  "enabled": true
}
```

**TaskResponse** includes current status, assigned agent, message count, and (if applicable) schedule info.

## Assignment and Concurrency

Tasks follow a checkout model to prevent duplicate work:

1. A task in `created` status can be assigned to any available agent
2. Assignment is atomic: the API uses a conditional update (`SET status='assigned' WHERE id=? AND status='created'`). If 0 rows affected, another process got there first.
3. Multiple tasks can be `running` concurrently (different agents, different worktrees)
4. A worktree can have at most one `running` task at a time (enforced by the Session Manager)

## Scheduling (Not Implemented in v1)

The database schema includes schedule fields (`schedule_cron`, `schedule_enabled`, `schedule_id`) but the scheduling functionality is not yet implemented. Future versions will support:

1. **One-shot tasks**: Created, assigned, started immediately or manually. No cron expression.
2. **Recurring tasks**: Created with a `schedule_cron` expression. When enabled, the Scheduler registers an OS-native job (launchd/systemd) that calls back into the Task Engine at the specified interval.
3. **Schedule lifecycle**:
   - `PUT /schedule` → Task Engine stores cron expression → Scheduler registers OS job → `schedule_id` stored on task
   - `DELETE /schedule` → Scheduler removes OS job → `schedule_cron` and `schedule_id` cleared
   - `POST /run` → Fire-and-forget: immediately creates a new task run (clones the task's description into a new session)

Recurring tasks create a new session for each invocation. The task record tracks the template; individual runs are tracked via Session records.

## Error Handling

| Code | Condition | Message |
|------|-----------|---------|
| 400 | Invalid status transition | "Cannot transition task from 'completed' to 'running'" |
| 400 | Invalid cron expression | "Invalid cron expression: 'every monday'" |
| 404 | Task not found | "Task '{taskId}' not found in project '{id}'" |
| 409 | Task already assigned | "Task '{taskId}' is already assigned to agent '{agentId}'" |
| 409 | Worktree busy | "Worktree '{worktreeId}' already has a running task" |
| 422 | Missing required field | "Field 'description' is required" |

## Edge Cases

1. **Agent crashes mid-task**: Session Manager detects crash via heartbeat, marks session as `failed`, Task Engine moves task back to `assigned` (if retries remain) or `failed`.
2. **Scheduled task fires while previous run is still active**: Scheduler's no-overlap guarantee prevents this at the OS level. If somehow triggered, Task Engine rejects the duplicate start.
3. **Task description updated while running**: Allowed. The agent receives the update via its conversation thread (TaskMessage). The task description field is the canonical source of truth.
4. **Deleting a task with an active schedule**: Must unschedule first, or the API auto-unschedules as part of the delete.
5. **Retries with different agents**: Allowed. `retry_count` increments but `assigned_agent_id` can change.
6. **Non-git project tasks**: `worktree_id` is null. Session runs directly in the project directory without worktree isolation.

## Dependencies

- **SQLite**: Task, TaskMessage, and TaskLog storage
- **Session Manager**: Launches agent sessions for assigned tasks
- **Agent Registry**: Validates agent availability during assignment
- **Project Manager**: Validates project exists and resolves path
- **httpx**: HTTP client for communicating with agent servers

## Design Decisions

### Why a flat ticket model, not a hierarchy?

Per the HLD non-goal: no personas, no org charts, no parent/child task trees. A flat list of tasks per project keeps the model simple. If grouping is needed later, tags or labels can be added without restructuring.

### Why retry is re-assignment, not re-run?

Retrying a failed task gives the user a chance to pick a different agent or adjust the description. Simply re-running with the same inputs that just failed is rarely useful.

### Why schedule configuration lives on the task?

Keeping `schedule_cron` and `schedule_id` on the Task record means the task is self-describing. You can see at a glance whether a task is recurring, what its schedule is, and whether it's enabled. The Scheduler component is a thin adapter that translates this into OS-native job registration.

### Why separate TaskMessage from TaskLog?

`TaskMessage` is the conversation thread (user-agent-system messages) — it's the content the user and agent produce. `TaskLog` is the audit trail (state transitions, system events) — it's what happened to the task mechanically. Different consumers, different query patterns.

### Why sqlite-sync-only assistant persistence?

Assistant text can arrive through multiple observation paths (HTTP response body and sqlite timeline). If both write to `TaskMessage`, the user sees duplicate assistant entries. Restricting assistant persistence to sqlite sync hardens an arrow-of-intent invariant: OpenCode history is the single source of truth for assistant timeline hydration.

## Implementation Status

✅ Implemented (v0.2 rewrite slice). Full CRUD, guarded state transitions, HTMX fragment endpoints, and SQLite history-aware message timeline ingestion.

## Requirements

- [Task Management EARS](./task-management-EARS.md)

## Related Documents

- [High-Level Design](../../high-level-design.md)
- [Project Management LLD](../project-management/LLD.md)
- [Session Manager LLD](../session-manager/LLD.md)
- [Scheduler LLD](../scheduler/LLD.md)

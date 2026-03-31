# OpenCode Orchestrator - EARS

**Parent HLD**: ../high-level-design.md

## Project Management

- [x] **PROJ-001**: The system shall allow users to register a local directory as a project.
- [x] **PROJ-002**: The system shall detect if a project directory contains a git repository.
- [x] **PROJ-003**: The system shall extract git remote URL (origin) when available.
- [x] **PROJ-004**: The system shall extract the default branch name from git config.
- [x] **PROJ-005**: The system shall prevent duplicate project registration for the same path.
- [x] **PROJ-006**: The system shall list all registered projects.
- [x] **PROJ-007**: The system shall allow users to delete a project.
- [x] **PROJ-008**: The system shall return project status including path existence and git state.

## Agent Registry

- [x] **AGENT-001**: The system shall allow users to register an agent with name and port.
- [x] **AGENT-002**: The system shall auto-generate the agent command as "opencode serve --port {port}".
- [x] **AGENT-003**: The system shall allow users to start an agent process.
- [x] **AGENT-004**: The system shall allow users to stop an agent process.
- [x] **AGENT-005**: The system shall perform health check via HTTP GET to /global/health.
- [x] **AGENT-006**: The system shall update agent status based on health check result.
- [x] **AGENT-007**: The system shall allow users to send a message to an agent and receive a response.
- [x] **AGENT-008**: The system shall list all registered agents.
- [x] **AGENT-009**: The system shall allow users to delete an agent registration.
- [x] **AGENT-010**: The system shall prevent duplicate agent name registration.
- [x] **AGENT-011**: The system shall discover available providers/models from OpenCode `GET /config/providers`.

## Worktree Management

- [x] **WORK-001**: The system shall allow users to create a git worktree for a project.
- [x] **WORK-002**: The system shall create worktrees under .opencode/worktrees/ within the project.
- [x] **WORK-003**: The system shall prevent worktree creation for non-git projects.
- [x] **WORK-004**: The system shall prevent duplicate worktree paths.
- [x] **WORK-005**: The system shall allow users to delete a worktree.
- [x] **WORK-006**: The system shall prevent worktree deletion if an active session exists.
- [x] **WORK-007**: The system shall list all worktrees for a project.

## Task Management

- [x] **TASK-001**: The system shall allow users to create a task with description.
- [x] **TASK-002**: The system shall auto-generate task title from description (first 50 chars).
- [x] **TASK-003**: The system shall auto-assign a task to an available agent upon creation.
- [x] **TASK-004**: The system shall create a session when task is assigned to agent.
- [x] **TASK-005**: The system shall send task description as initial message to agent.
- [x] **TASK-006**: The system shall allow users to run a created task manually.
- [x] **TASK-007**: The system shall allow users to send additional messages to a running task.
- [x] **TASK-008**: The system shall store user messages in task_messages table.
- [x] **TASK-009**: The system shall store agent responses in task_messages table.
- [x] **TASK-010**: The system shall list all tasks for a project.
- [x] **TASK-011**: The system shall filter tasks by status.
- [x] **TASK-012**: The system shall allow users to delete a task.
- [x] **TASK-013**: The system shall return task details including associated session and agent.
- [x] **TASK-018**: The system shall represent waiting states as `waiting_question` and `waiting_permission`.
- [x] **TASK-019**: The system shall expose HTMX task snippets for board, status, messages, and prompts.
- [x] **TASK-020**: The system shall ingest OpenCode sqlite message history and deduplicate by OpenCode message id.
- [x] **TASK-021**: The system shall accept an optional `model` on task creation and map `provider/model` to OpenCode session `providerID`/`modelID`.
- [x] **TASK-022**: The system shall persist assistant task messages from OpenCode sqlite sync only.
- [x] **TASK-023**: The system shall not persist assistant task messages from orchestrator stream parsing.
- [ ] **TASK-014**: The system shall allow users to cancel a running task.
- [ ] **TASK-015**: The system shall allow users to retry a failed task.
- [ ] **TASK-016**: The system shall support scheduling tasks via cron expression.
- [ ] **TASK-017**: The system shall store schedule configuration (cron, enabled, schedule_id) on task.

## Session Management

- [x] **SESS-001**: The system shall create a session record when task starts running.
- [x] **SESS-002**: The system shall list all sessions for a project.
- [x] **SESS-003**: The system shall filter sessions by status.
- [x] **SESS-004**: The system shall allow users to cancel a running session.
- [x] **SESS-005**: The system shall send SIGTERM to agent process on cancel.
- [x] **SESS-006**: The system shall update session status to "stopping" on cancel.
- [x] **SESS-007**: The system shall return session details.
- [x] **SESS-011**: The system shall reconcile session/task runtime status from OpenCode `/session/status`, `/permission`, and `/question`.
- [x] **SESS-012**: The system shall import OpenCode session timeline from sqlite (`opencode.db`) for chat history hydration.
- [x] **SESS-013**: The system shall treat sqlite timeline import as the durable source of truth for assistant message hydration.
- [ ] **SESS-008**: The system shall stream session output via SSE.
- [ ] **SESS-009**: The system shall support pause/resume for sessions.
- [ ] **SESS-010**: The system shall perform heartbeat monitoring for running sessions.

## Frontend

- [x] **UI-001**: The system shall render project list page.
- [x] **UI-002**: The system shall render project detail page with tasks and sessions.
- [x] **UI-003**: The system shall render task detail page with messages.
- [x] **UI-004**: The system shall render settings page with agent registry.
- [x] **UI-005**: The system shall render session list page.
- [x] **UI-006**: The system shall load HTMX from CDN.
- [x] **UI-007**: The system shall mediate create/update/delete interactions through HTMX endpoints and snippet responses.
- [x] **UI-011**: The system shall render task model options from OpenCode provider metadata rather than hardcoded UI lists.
- [ ] **UI-008**: The system shall support real-time output streaming via SSE.
- [ ] **UI-009**: The system shall support real-time chat via WebSocket.
- [ ] **UI-010**: The system shall support mobile access via Tailscale.

## API General

- [x] **API-001**: The system shall return appropriate HTTP status codes (200, 201, 400, 404, 409).
- [x] **API-002**: The system shall return JSON error messages with detail field.
- [x] **API-003**: The system shall use UUIDs for all entity IDs.
- [x] **API-004**: The system shall use ISO8601 timestamps.

## Data Storage

- [x] **DB-001**: The system shall store all data in SQLite database.
- [x] **DB-002**: The system shall create database at ~/.config/opencode-orchestrator/orchestrator.db.
- [x] **DB-003**: The system shall create necessary tables on startup.
- [x] **DB-004**: The system shall use foreign key relationships with cascade delete.

## Related Documents

- [High-Level Design](../high-level-design.md)
- [Project Management LLD](./project-management/LLD.md)
- [Task Engine LLD](./task-engine/LLD.md)
- [Session Manager LLD](./session-manager/LLD.md)
- [Agent Gateway LLD](./acp-gateway/LLD.md)
- [Frontend LLD](./frontend/LLD.md)

# Task Management - EARS

**Parent LLD**: ./LLD.md

## Task Creation

- [x] **TASK-CREATE-001**: The system shall create a task with the provided description.
- [x] **TASK-CREATE-002**: The system shall auto-generate title from description (first 50 characters).
- [x] **TASK-CREATE-003**: The system shall set task status to "created" on creation.
- [x] **TASK-CREATE-004**: The system shall create a task log entry on creation.
- [x] **TASK-CREATE-005**: Where an available agent exists, the system shall auto-assign the task.

## Task Listing

- [x] **TASK-LIST-001**: The system shall list all tasks for a project.
- [x] **TASK-LIST-002**: The system shall filter tasks by status when requested.
- [x] **TASK-LIST-003**: The system shall filter tasks by assigned agent when requested.
- [x] **TASK-LIST-004**: The system shall order tasks by priority, then creation time.

## Task Execution

- [x] **TASK-RUN-001**: When a task is run, the system shall create a session with the assigned agent.
- [x] **TASK-RUN-002**: The system shall send the task description as the initial message to the agent.
- [x] **TASK-RUN-003**: The system shall update task status to "running" when session starts.
- [x] **TASK-RUN-004**: Where no agent is available, the system shall keep task in "created" status.

## Task Messaging

- [x] **TASK-MSG-001**: The system shall allow sending messages to a running task.
- [x] **TASK-MSG-002**: The system shall store user messages in the task message history.
- [x] **TASK-MSG-003**: The system shall store assistant responses in the task message history from OpenCode sqlite sync.
- [x] **TASK-MSG-004**: The system shall forward messages to the agent via HTTP.
- [x] **TASK-MSG-005**: The system shall not persist assistant responses directly from orchestrator stream parsing.
- [x] **TASK-MSG-006**: When a follow-up message is sent and a prior session exists for the task, the system shall reuse the latest reachable task session before creating a new one.
- [x] **TASK-MSG-007**: Where the latest task session is unreachable, the system shall mark that session completed and create a new session for the outgoing follow-up message.
- [x] **TASK-MSG-008**: After a successful background agent response, the system shall trigger task history import and emit a `task-updated` event so the task-detail thread refreshes without manual page reload.
- [x] **TASK-MSG-009**: The system shall emit typed task-detail events (`task-status`, `task-messages`, `task-prompts`) so UI regions can react independently with minimal delay.
- [x] **TASK-MSG-010**: The system shall enqueue sync nudges from periodic, event-driven, and post-send triggers through a coalesced queue rather than invoking overlapping sync passes directly.
- [x] **TASK-MSG-011**: Where a follow-up send detects directory mismatch for the latest session's agent, the system shall rotate away from that runtime and attempt a project-pinned agent bootstrap.
- [x] **TASK-MSG-012**: Where project-pinned bootstrap fails during follow-up send, the system shall return an explicit error and shall not report a successful send.

## Project-Pinned Agent Bootstrap

- [x] **TASK-BOOT-001**: The system shall resolve task execution to an agent whose configured `cwd` matches the task project's path.
- [x] **TASK-BOOT-002**: Where no matching agent exists, the system shall create a new agent registry entry with the project path as `cwd` and an available local port.
- [x] **TASK-BOOT-003**: The system shall validate the live OpenCode runtime directory via `/path` before accepting create/run/send task execution.
- [x] **TASK-BOOT-004**: Where the live directory does not match project path after bootstrap, the system shall fail closed with an explicit directory-mismatch error.

## Task Deletion

- [x] **TASK-DEL-001**: The system shall delete the task and associated sessions.
- [x] **TASK-DEL-002**: The system shall delete associated task messages and logs.

## Related Documents

- [Task Engine LLD](./LLD.md)

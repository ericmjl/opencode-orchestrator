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

## Task Deletion

- [x] **TASK-DEL-001**: The system shall delete the task and associated sessions.
- [x] **TASK-DEL-002**: The system shall delete associated task messages and logs.

## Related Documents

- [Task Engine LLD](./LLD.md)

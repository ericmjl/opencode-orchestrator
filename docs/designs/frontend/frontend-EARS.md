# Frontend - EARS

**Parent LLD**: ./LLD.md

## Project Pages

- [x] **FE-PROJ-001**: The system shall display a list of registered projects.
- [x] **FE-PROJ-002**: The system shall provide a form to register new projects.
- [x] **FE-PROJ-003**: The system shall display project detail page with tasks and sessions.
- [x] **FE-PROJ-004**: The system shall use SSE-triggered HTMX updates to re-render the project task board when task state changes.

## Task Pages

- [x] **FE-TASK-001**: The system shall display task list for a project.
- [x] **FE-TASK-002**: The system shall provide a form to create new tasks.
- [x] **FE-TASK-003**: The system shall display task detail with session and agent info.
- [x] **FE-TASK-004**: The system shall display task message history.
- [x] **FE-TASK-005**: The system shall show an optimistic pending task card immediately after create-task submit.
- [x] **FE-TASK-006**: The system shall replace optimistic pending task UI with server-rendered task board content after HTMX response.
- [x] **FE-TASK-007**: The system shall disable the create button and show `Creating...` while create-task request is in flight.
- [x] **FE-TASK-008**: The system shall remember the last selected task model across reloads and HTMX model picker swaps.
- [x] **FE-TASK-009**: The system shall not render optimistic user messages into the task message history while send-message requests are in flight.
- [x] **FE-TASK-010**: The system shall keep the task send button in `Sending...` state until the user message is confirmed by server-rendered (sqlite-backed) history.
- [x] **FE-TASK-011**: The system shall synchronize task-detail message refresh and send-message requests to avoid refresh/send race conditions.
- [x] **FE-TASK-012**: The system shall target `#task-board` for archive-driven swaps to preserve server-evaluated column empty-state placeholders.
- [x] **FE-TASK-013**: The system shall use SSE-triggered HTMX updates for task-detail message, status, and pending-prompt regions.
- [x] **FE-TASK-014**: The system shall preserve default browser navigation semantics while providing fallback redirect reliability for task-detail "Back to Project" interactions during active live updates.
- [x] **FE-TASK-015**: After a successful task follow-up response is ingested, the system shall refresh the task-detail message region via `task-updated` without requiring manual browser reload.
- [x] **FE-TASK-016**: The system shall keep task-detail refresh/navigation responsive while history ingestion runs, avoiding event-loop blocking during live updates.
- [x] **FE-TASK-017**: The system shall consume typed task stream events via `EventSource` and update task status badge text/class immediately on `task-status`.
- [x] **FE-TASK-018**: The system shall refresh message and prompt regions reactively on `task-messages` and `task-prompts` events without changing the existing visual layout.

## Session Pages

- [x] **FE-SESSION-001**: The system shall display session list for a project.
- [x] **FE-SESSION-002**: The system shall display session detail with status and timestamps.

## Agent Pages

- [x] **FE-AGENT-001**: The system shall display agent list.
- [x] **FE-AGENT-002**: The system shall provide a form to register new agents.
- [x] **FE-AGENT-003**: The system shall provide controls to start/stop agents.

## Settings

- [x] **FE-SETTINGS-001**: The system shall display global settings page.
- [x] **FE-SETTINGS-002**: The system shall display agent management in settings.

## Navigation

- [x] **FE-NAV-001**: The system shall provide navigation between projects, tasks, sessions.
- [x] **FE-NAV-002**: The system shall redirect root URL to projects page.

## Design Language

- [x] **FE-DL-001**: The system shall style buttons, links-as-buttons, inputs, selects, and badges according to `docs/design-language.md`.
- [x] **FE-DL-002**: The system shall use shared design tokens/classes rather than ad-hoc inline styles when an equivalent design-language pattern exists.
- [x] **FE-DL-003**: The system shall keep semantic equivalents visually consistent (for example `<a class="btn ...">` and `<button class="btn ...">`).

## Related Documents

- [Frontend LLD](./LLD.md)

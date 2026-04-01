# Frontend - Low-Level Design

**Created**: 2026-03-28
**HLD Link**: ../../high-level-design.md

## Overview

The frontend is a server-rendered HTMX + Alpine.js + CSS application served by the FastAPI backend. It provides project management, task board, session monitoring, and agent output views. HTMX and Alpine.js are loaded via CDN for simplicity.

## Context

Per the HLD, the frontend uses HTMX for server-rendered HTML fragments, Alpine.js for small reactive elements, and vanilla CSS. No build step, no node_modules. Access is local-only in v1 (localhost).

Task creation includes a dynamic model picker populated from OpenCode provider metadata. The picker loads via HTMX fragment endpoint so model options stay server-owned and reflect the currently running agents.

For high-frequency task creation, the create-task flow includes two responsiveness affordances:
- optimistic pending task card insertion in the Running column while create request is in flight
- sticky model preference persistence on the task model selector (`localStorage`) across reload/swap cycles

The frontend is governed by `docs/design-language.md`. Shared tokens and component rules are mandatory for all UI elements, including links styled as buttons, form controls, task cards, badges, and status affordances.

## UI Navigation Structure

```
┌─ OpenCode Orchestrator ─────────────────────────────────────────────────┐
│  [Projects]  [Agents]                                        [⚙ Settings]│
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  (content area — changes based on route)                                │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

Routes:
- `/` → redirects to `/projects`
- `/projects` — Project list
- `/projects/{id}` — Project detail with tasks and recent sessions
- `/projects/{id}/sessions` — Session list
- `/projects/{id}/tasks/{taskId}` — Task detail (agent session, messages)
- `/settings` — Agent registry and settings

## UI Sketches

### Task Board

```
┌─ OpenCode Orchestrator ─────────────────────────────────────────────────┐
│ Projects > my-app > Tasks                                    [+ New]    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─ Created ──────┐  ┌─ Assigned ──────┐  ┌─ Running ───────┐          │
│  │                 │  │                  │  │                  │          │
│  │  ┌───────────┐  │  │  ┌────────────┐  │  │  ┌────────────┐ │          │
│  │  │ #5 Add    │  │  │  │ #3 Fix     │  │  │  │ #2 Search  │ │          │
│  │  │ pagination│  │  │  │ login bug  │  │  │  │ API        │ │          │
│  │  │ P: 3      │  │  │  │ opencode   │  │  │  │ claude     │ │          │
│  │  │           │  │  │  │ ● ● running│  │  │  │ ● ● 5m ago │ │          │
│  │  └───────────┘  │  │  └────────────┘  │  │  └────────────┘ │          │
│  │                 │  │                  │  │                  │          │
│  │  ┌───────────┐  │  │  ┌────────────┐  │  │                  │          │
│  │  │ #8 Update │  │  │  │ #7 Refactor│  │  │                  │          │
│  │  │ README    │  │  │  │ auth module│  │  │                  │          │
│  │  │ P: 7      │  │  │  │ codex      │  │  │                  │          │
│  │  │ 🔄 daily  │  │  │  │ ● ● waiting│  │  │                  │          │
│  │  └───────────┘  │  │  └────────────┘  │  │                  │          │
│  │                 │  │                  │  │                  │          │
│  └─────────────────┘  └──────────────────┘  └──────────────────┘          │
│                                                                          │
│  ┌─ Completed ────┐  ┌─ Failed ────────┐                               │
│  │                 │  │                  │                               │
│  │  ┌───────────┐  │  │  ┌────────────┐  │                               │
│  │  │ #1 Setup  │  │  │  │ #4 Rename  │  │                               │
│  │  │ project   │  │  │  │ variables  │  │                               │
│  │  │ ✓ done    │  │  │  │ ✗ retry 1/3│  │                               │
│  │  └───────────┘  │  │  └────────────┘  │                               │
│  │                 │  │                  │                               │
│  └─────────────────┘  └──────────────────┘                               │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### Agent Registry

```
┌─ OpenCode Orchestrator ─────────────────────────────────────────────────┐
│ Agents                                                        [+ New]   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  opencode                                              available  │  │
│  │  Command: opencode acp                                           │  │
│  │  Model: gpt-4.1                                                  │  │
│  │  Last seen: 2 min ago                                            │  │
│  │  [Ping]  [Edit]  [Delete]                                        │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  claude                                                available  │  │
│  │  Command: claude code acp                                         │  │
│  │  Model: sonnet                                                    │  │
│  │  Last seen: 5 min ago                                             │  │
│  │  [Ping]  [Edit]  [Delete]                                         │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  codex                                                available  │  │
│  │  Command: codex acp                                               │  │
│  │  Model: o3                                                        │  │
│  │  Last seen: 1 hr ago                                              │  │
│  │  [Ping]  [Edit]  [Delete]                                         │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### Mobile Layout (responsive collapse)

On narrow screens (<768px), the task board collapses from columns to a tabbed view:

```
┌─ OpenCode Orchestrator ──────────┐
│ ☰ Projects > my-app      [+ New]│
├──────────────────────────────────┤
│ [Created] [Active] [Done] [Fail]│
├──────────────────────────────────┤
│                                  │
│  ┌────────────────────────────┐  │
│  │ #3 Fix login bug           │  │
│  │ opencode  ● running        │  │
│  │ [View]                     │  │
│  └────────────────────────────┘  │
│                                  │
│  ┌────────────────────────────┐  │
│  │ #7 Refactor auth           │  │
│  │ codex  ● waiting           │  │
│  │ [View]                     │  │
│  └────────────────────────────┘  │
│                                  │
└──────────────────────────────────┘
```

## Technology Stack

### HTMX

Used for all server-driven interactions:
- Task CRUD → HTML fragment swaps
- Session list refresh → `hx-get` polling every 5s for active sessions
- Task board refresh → SSE-triggered HTMX board fragment swaps (`project-updated`)
- Task detail refresh → SSE-triggered HTMX message/status/prompt swaps (`task-updated`)
- Task board drag-and-drop → `hx-post` with status change
- Pagination and filtering

### Alpine.js

Used for client-side interactivity that HTMX doesn't cover:
- Dropdown menus and modals (register project, assign agent)
- Form validation feedback
- Tab switching (mobile task board)
- Auto-scroll toggle in session output view

### CSS

Vanilla CSS with CSS custom properties for theming. No framework.

Layout uses CSS Grid for the task board columns and Flexbox for card layouts. Media queries at 768px and 480px handle tablet and mobile breakpoints.

#### Design Language Conformance Rules

1. Avoid one-off inline styling when a documented class/token exists.
2. Ensure semantic equivalents (for example `<a class="btn">` and `<button class="btn">`) share the same visual geometry.
3. Component variants (`btn-sm`, `btn-danger`, badges, cards) must match documented spacing/typography states.
4. Any new visual pattern must first be added to `docs/design-language.md`, then implemented in templates/CSS.

### SSE / WebSocket

SSE is now used for reactive UI refresh in task-centric views:
- Project detail board subscribes to project-level updates and re-renders `#task-board`.
- Task detail subscribes to task-level updates and re-renders messages/status/prompts.

WebSocket-based bidirectional chat is still not implemented in v1.

### Dynamic Model Picker

The project task creation form includes a model selector that is populated from OpenCode itself:

1. Frontend loads `GET /api/projects/{id}/tasks/model-options-fragment` via HTMX.
2. Backend queries available agents and reads each agent's `GET /config/providers`.
3. Backend renders `<select name="model">` options in `provider/model` format.
4. Task create form submits selected `model` with `description`.

The frontend persists the most recently selected model locally and reapplies it after HTMX reload of the model picker fragment. If the saved value is no longer present in live options, the picker falls back to agent default.

### Optimistic Task Creation Feedback

The create-task form renders immediate client-side feedback before the server round-trip completes:

1. On `htmx:beforeRequest`, the UI inserts a temporary pending card in the Running column.
2. The Create button is disabled and label changes to `Creating...`.
3. On successful response, HTMX swaps in the authoritative task board HTML and replaces the placeholder.
4. On failed response, the pending placeholder is removed and button state is restored.

This mechanism improves perceived latency while preserving server-owned task state.

### Task Detail Message Send Semantics (Reactive Thread)

Task-detail message threads use EventSource-driven typed updates and follow server-confirmed rendering:

1. On send submit, the button transitions to a pending state (`Sending...`, disabled).
2. The UI does not insert optimistic user messages into the visible history.
3. Region refresh and submit requests are synchronized (`hx-sync`) to avoid clobber races.
4. Pending state clears when the submitted message appears in the server-rendered thread.
5. On failure, pending state clears immediately and history remains unchanged.

This preserves thread authority and avoids flicker caused by stale refresh responses overwriting optimistic DOM inserts.

### Task Detail Live-Update Freshness Contract

Task-detail thread freshness relies on a backend publish contract:

1. The task detail page subscribes via `EventSource` to `/api/projects/{id}/tasks/{taskId}/stream`.
2. The backend emits typed events (`task-status`, `task-messages`, `task-prompts`) and a compatibility `task-updated`.
3. `task-status` updates badge text/class immediately; message and prompts events trigger targeted HTMX fragment refresh.
4. Background history ingestion work must not block the FastAPI event loop; expensive sqlite-history reads run off-thread to preserve page responsiveness during refresh/navigation.

This contract ensures operators see assistant turns without manual reload while preserving smooth browser navigation under sustained activity.

### Interaction Reliability (Navigation Under Live Updates)

Live update flows can keep pages in long-lived reactive states. Navigation controls (for example, task-detail "Back to Project") must remain reliably clickable under active SSE/HTMX updates.

Implementation requirement:
1. Primary behavior remains native anchor navigation.
2. A lightweight fallback redirect is allowed when a normal click does not change route within a short interval.
3. Modified-click semantics (new tab/window) must remain unchanged.

### Task Board Mutation Semantics

Archive/unarchive interactions target the board container and trigger full board fragment replacement (`#task-board`), not single-card deletion. This guarantees server-evaluated empty states (for example `No tasks`) are always accurate after mutations.

### Mobile Access (Not Implemented in v1)

Remote access via Tailscale or similar is not implemented. Access is local-only via `http://127.0.0.1:<port>`.

## Data Flow

```
┌──────────┐   HTTP    ┌──────────┐   subprocess   ┌──────────┐
│  Browser │──────────→│ FastAPI  │───────────────→│  Agent   │
│          │←──────────│          │←───────────────│          │
│          │   HTML/   │          │   ACP stdio     │          │
│          │   SSE/WS  │          │                 │          │
└──────────┘           └──────────┘                 └──────────┘
                            │
                            │ SQL
                            ▼
                       ┌──────────┐
                       │  SQLite  │
                       └──────────┘
```

All HTML is rendered server-side by FastAPI using Jinja2 templates. HTMX requests return HTML fragments (partial pages), not JSON. Full page loads return the complete page.

## Template Structure

```
templates/
├── base.html              ← layout shell, nav bar, CSS/JS includes
└── pages/
    ├── projects.html      ← project list page
    ├── project-detail.html
    ├── task-detail.html
    └── settings.html     ← agent registry
```

Templates are rendered server-side via Jinja2, with HTMX partial swaps for dynamic regions (task board, task detail fragments, model picker, and sidebar badge OOB updates).

## API Contracts

The frontend consumes the same REST API documented in the other LLDs. Additionally, the FastAPI server renders HTML for browser requests:

| Route | Returns | HTMX Target |
|-------|---------|-------------|
| `GET /` | HTML (project list) | — |
| `GET /projects/{id}` | HTML (task board) | `#main` |
| `GET /projects/{id}/sessions` | HTML (session list) | `#main` |
| `GET /projects/{id}/sessions/{sid}` | HTML (session detail) | `#main` |
| `GET /agents` | HTML (agent list) | `#main` |

Content negotiation: if `HX-Request: true` header is present, return HTML fragment. Otherwise return full page.

## Error Handling

| Condition | Frontend Behavior |
|-----------|-------------------|
| API returns 4xx | Display error toast (Alpine.js), keep current state |
| API returns 5xx | Display "Something went wrong" banner with retry button |
| SSE disconnect | Auto-reconnect, backfill from server-rendered fragments |
| WebSocket disconnect | Auto-reconnect with backoff, queue outbound messages |
| Page load failure | HTMX error handler shows full-page error with reload link |

## Edge Cases

1. **Browser back/forward navigation**: Works as expected with full page reloads.
2. **No remote access**: The app is only accessible on localhost. Future versions will add Tailscale or similar for remote access.

## Dependencies

- **FastAPI**: Serves HTML templates and static files
- **Jinja2**: Template rendering (included with FastAPI)
- **HTMX**: Frontend library, loaded via CDN
- **Alpine.js**: Frontend reactivity, loaded via CDN

## Design Decisions

### Why HTMX + Alpine.js, not React/Vue?

Per the HLD: no build step, no node_modules, no framework churn. The UI is server-rendered with Jinja2 templates. Alpine.js handles client-side state (dropdowns, modals). The frontend is HTML templates + two JS files loaded via CDN.

### Why CDN instead of vendoring?

For simplicity in v1. CDN resources load from unpkg which is widely available. Can be vendored in future versions for offline support.

## Implementation Status

✅ Implemented (v0.1.0+). Basic pages for projects, project detail, sessions, tasks, settings. SSE-triggered HTMX refresh is implemented for project board and task detail. WebSocket chat remains future work.

## Requirements

- [Frontend EARS](./frontend-EARS.md)

## Related Documents

- [High-Level Design](../../high-level-design.md)
- [Project Management LLD](../project-management/LLD.md)
- [Task Engine LLD](../task-engine/LLD.md)
- [Session Manager LLD](../session-manager/LLD.md)
- [Agent Gateway LLD](../acp-gateway/LLD.md)

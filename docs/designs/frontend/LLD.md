# Frontend - Low-Level Design

**Created**: 2026-03-28
**HLD Link**: ../../high-level-design.md

## Overview

The frontend is a server-rendered HTMX + Alpine.js + CSS application served by the FastAPI backend. It provides project management, task board, session monitoring, and agent output views. HTMX and Alpine.js are loaded via CDN for simplicity.

## Context

Per the HLD, the frontend uses HTMX for server-rendered HTML fragments, Alpine.js for small reactive elements, and vanilla CSS. No build step, no node_modules. Access is local-only in v1 (localhost).

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

### SSE / WebSocket (Not Implemented in v1)

Real-time streaming via SSE or WebSocket is not implemented. Future versions will support:
- SSE for real-time agent output streaming
- WebSocket for bidirectional conversation thread

In v1, messages and outputs are viewed via page refresh or task detail page.

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

Templates are rendered server-side via Jinja2. No partials or HTMX fragment swaps in v1.

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
| SSE disconnect | Auto-reconnect, backfill from session log |
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

✅ Implemented (v0.1.0). Basic pages for projects, project detail, sessions, tasks, settings. No Alpine.js interactivity yet. SSE/WebSocket streaming not implemented.

## Requirements

- [Frontend EARS](./frontend-EARS.md)

## Related Documents

- [High-Level Design](../../high-level-design.md)
- [Project Management LLD](../project-management/LLD.md)
- [Task Engine LLD](../task-engine/LLD.md)
- [Session Manager LLD](../session-manager/LLD.md)
- [Agent Gateway LLD](../acp-gateway/LLD.md)

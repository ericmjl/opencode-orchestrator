# OpenCode Orchestrator - High-Level Design

**Created**: 2026-03-28

## Problem Statement

Developers using AI coding agents (Claude Code, Codex, etc.) face a coordination problem: they run multiple agent sessions in parallel across different tasks, but lack a unified way to manage, monitor, and hand off those sessions across devices. Existing solutions are either cloud-hosted (losing local control), single-agent (no orchestration), or desktop-only (no mobile handoff).

We need a **local-first, project-based orchestrator** that treats AI agent sessions like managed workers — assigning tasks via tickets, isolating work in git worktrees, and allowing seamless device handoff — all while keeping code and state on the developer's own machine.

## Goals

1. **Project-based orchestration** — One project = one directory on disk (git repo, Obsidian vault, or any workspace). All orchestration is scoped to a project.
2. **Worktree-isolated sessions** — Each agent session operates in its own `git worktree`, preventing conflicts and enabling parallel work on the same repo.
3. **Task ticket system** — Inspired by Paperclip: every unit of work is a ticket with status, assigned agent, conversation thread, and audit trail. Atomic checkout prevents duplicate work.
4. **Agent-agnostic via HTTP** — Use the agent's HTTP API (e.g., `opencode serve --port X`) to connect to coding agents. Agents run as persistent background servers. The orchestrator communicates via REST/HTTP.
5. **Local-first, packaged as a CLI tool** — Installable via `uvx opencode-orchestrator` (or `pip install`). Runs a local FastAPI server — no cloud accounts, no external dependencies for core functionality. Data stored in SQLite + git.

## Non-Goals

- **Personas / role-based agent hierarchy** — No org charts or CEO agents. Flat task assignment model.
- **Multi-user / team features** — Single developer use case for v1. No shared state across users.
- **Cloud hosting** — No hosted version. The app runs locally.
- **Agent implementation** — We orchestrate agents, we don't implement them. Agents are external subprocesses connected via HTTP.
- **CI/CD integration** — Not a build system. Agents can trigger CI, but we don't manage pipelines.
- **Scheduled / recurring tasks** — Tasks run on-demand. Scheduling is a future enhancement.
- **Cross-device handoff** — Local access only. Remote access is a future enhancement.

## Target Users

- **Solo developer** running multiple AI agent sessions across tasks in a single project, who wants visibility and control without juggling terminal windows.

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                    Desktop / Mobile UI                        │
│           HTMX-first + server-rendered snippets              │
│   ┌──────────┐  ┌──────────┐  ┌────────────┐  ┌─────────┐  │
│   │ Project  │  │  Task    │  │  Session   │  │  Agent  │  │
│   │  View    │  │  Board   │  │  Monitor   │  │  Output │  │
│   └──────────┘  └──────────┘  └────────────┘  └─────────┘  │
└──────────────────────┬───────────────────────────────────────┘
                         │ HTTP
                         ▼
┌──────────────────────────────────────────────────────────────┐
│                  FastAPI Backend (local)                      │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │   Project    │  │    Task      │  │     Session       │  │
│  │   Manager    │  │   Engine     │  │     Manager       │  │
│  │  (dirs +     │  │  (tickets,   │  │  (worktrees,      │  │
│  │   config)    │  │   assign,    │  │   lifecycle)      │  │
│  │              │  │   track)     │  │                   │  │
│  └──────────────┘  └──────────────┘  └───────────────────┘  │
│                                                              │
│  ┌──────────────┐  ┌─────────────────────────────────────┐ │
│  │    Agent     │  │              Worktree                 │ │
│  │   Registry   │  │              Manager                  │ │
│  │ (start/stop, │  │  (create, remove git worktrees)      │ │
│  │   ping)      │  │                                     │ │
│  └──────────────┘  └─────────────────────────────────────┘ │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              SQLite (local storage)                   │   │
│  │  projects | tasks | sessions | worktrees | agents   │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
                         │ HTTP
                         ▼
┌──────────────────────────────────────────────────────────────┐
│              Agent Layer (via opencode serve)                  │
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │  OpenCode   │  │ Claude Code │  │  any agent with     │ │
│  │  (primary)  │  │             │  │  HTTP API           │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
│        ↑                ↑                    ↑              │
│   opencode serve   <agent> serve      <agent> serve         │
│   (HTTP API)      (HTTP API)         (HTTP API)             │
└──────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### Decision 1: Git Worktrees for Session Isolation

**Choice**: Worktrees provide filesystem isolation for agent sessions. Multiple task tickets can be assigned to a single worktree (e.g., related bug fixes on the same feature branch), but each worktree has at most one active agent session at a time.

**Rationale**: Worktrees provide true filesystem isolation without the overhead of full clones. Multiple agents can work on different features of the same repo simultaneously. Merging results back is standard git merge/rebase. Cleanup is `git worktree remove`. Allowing multiple tickets per worktree avoids worktree sprawl for related tasks.

**Alternatives considered**:
- Docker containers per session: Too heavy for local dev, adds complexity
- Branch-only (shared worktree): Race conditions on filesystem, agents step on each other
- Separate clones: Wastes disk, harder to merge
- Strict 1:1 ticket-to-worktree: Too rigid; related tickets naturally belong on the same branch

### Decision 2: SQLite for Local State

**Choice**: SQLite as the single local database for all orchestrator state (projects, tasks, sessions, logs).

**Rationale**: Zero-config, single-file, reliable, fast for single-user workloads. Supports WAL mode for concurrent reads during WebSocket streaming. No external database process to manage. Fits the local-first philosophy perfectly.

**Alternatives considered**:
- PostgreSQL: Overkill for single-user, requires separate process
- JSON files: No query capability, no ACID guarantees
- TinyDB: Limited query language, less battle-tested

### Decision 3: HTTP-based Agent Communication (via opencode serve)

**Choice**: Use the `opencode serve` HTTP API for agent communication. Agents run as background servers (`opencode serve --port X`), and the orchestrator communicates via HTTP REST calls.

**How it works**: 
- Agent is started with `opencode serve --port <port>` 
- Orchestrator creates sessions via `POST /session`
- Messages sent via `POST /session/{id}/message`
- Available providers/models discovered via `GET /config/providers`
- Agent runs persistently until stopped

**Rationale**: `opencode serve` provides a full HTTP API with session management, message history, and streaming support. It's more robust for orchestrator use than short-lived stdio connections that exit after each request.

The same API is the source of truth for model selection. The UI should not hardcode model IDs; instead it should render model choices from live OpenCode provider metadata.

### Decision 4: Local Access Only (v1)

**Choice**: For v1, the app is accessible only on localhost. Remote access via Tailscale or similar is a future enhancement.

**Rationale**: Keep v1 simple and focused on core orchestration. Remote access adds complexity (TLS, authentication, network resilience) that can be added later.

### Decision 5: HTMX-First Snippet Architecture



**Rationale**: UI interactions are HTMX-mediated by default: endpoints return HTML snippets, and OOB swaps update sidebar badges and status chips. This keeps behavior deterministic and server-owned without SPA complexity.

**Alternatives considered**:
- React/Vue SPA: Adds build complexity, second language ecosystem, overkill for this UI
- Pure HTMX (no JS): Some interactions need a thin JS layer
- Svelte: Nice but adds compilation step, smaller ecosystem

### Decision 6: Pixi for Project Dependencies

**Choice**: Use pixi for managing Python dependencies and development environment.

**Rationale**: User preference. Pixi handles conda + pip packages, lockfiles, and cross-platform reproducibility. Single `pixi.toml` for the project.

### Decision 7: Single-Writer Assistant Message Ingestion

**Choice**: Assistant responses are persisted only from OpenCode sqlite history ingestion (`opencode_sqlite` source). The orchestrator HTTP send path does not persist assistant text payloads directly.

**Rationale**: A single writer for assistant messages prevents duplicate chat entries caused by concurrent ingestion paths (stream payload parsing plus sqlite sync). OpenCode sqlite history is the durable timeline and provides stable `opencode_message_id` values for idempotent inserts.

**Alternatives considered**:
- Dual-write (stream + sqlite): Causes duplicate assistant messages and ambiguous ownership.
- Stream-only: Loses durable replay/cursor semantics from OpenCode history tables.

## Data Model Overview

```
Project
├── id, name, path, has_git, vcs_url, default_branch
├── created_at, updated_at
│
├── Worktree
│   ├── id, project_id, branch_name, path, created_at
│   ├── status (active|archived)
│   │
│   ├── Task (ticket) — optional worktree association
│   │   ├── id, worktree_id, title, description, status
│   │   ├── assigned_agent_id, priority
│   │   ├── schedule_cron, schedule_enabled, schedule_id
│   │   ├── retry_count, max_retries
│   │   ├── created_at, updated_at, completed_at
│   │   └── TaskMessage (conversation thread)
│   │       ├── id, task_id, role (user|assistant), content, timestamp
│   │       ├── source (orchestrator|opencode_sqlite)
│   │       ├── opencode_message_id (dedupe cursor)
│   │       └── metadata (optional)
│   │   └── TaskLog (audit trail)
│   │       ├── id, task_id, event, from_status, to_status
│   │       ├── details (JSON), timestamp
│   │
│   └── Session — may have multiple per task
│       ├── id, worktree_id, agent_id, task_id
│       ├── status (spawned|running|waiting_question|waiting_permission|stopping|completed|failed)
│       ├── pid, started_at, ended_at
│       ├── output_log_path, exit_code, error_message
│
└── AgentRegistry
    ├── id, name
    ├── command (e.g., "opencode serve --port 4000")
    ├── port (e.g., 4000)
    ├── cwd (working directory for agent)
    ├── capabilities (JSON), status (available|offline|error|starting)
    ├── pid (process ID when running)
    ├── config (JSON), last_seen, created_at
```

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Agent processes crash or hang | Add heartbeat monitoring with configurable timeout; auto-fail stuck sessions (future) |
| Git worktree limits on large repos | Monitor worktree count; warn at threshold |
| SQLite write contention under heavy load | WAL mode + single-writer pattern; sufficient for single-user |
| Duplicate assistant chat entries from mixed ingestion paths | Enforce single-writer assistant persistence from OpenCode sqlite sync |

## Implementation Status (v0.1.0)

| Component | Status | Notes |
|-----------|--------|-------|
| Project Management | ✅ Implemented | Full CRUD, git detection |
| Task Engine | ✅ Implemented | CRUD, auto-assign, message passing |
| Agent Gateway | ✅ Implemented | Registration, start/stop, HTTP communication |
| Session Manager | ✅ Implemented | Basic session management, cancel |
| Worktrees | ✅ Implemented | Git worktree creation/removal |
| Frontend | ✅ Implemented | HTMX-first pages with fragment endpoints |
| OpenCode History Sync | ✅ Implemented | Imports message timeline from OpenCode SQLite (`opencode.db`) |
| Scheduler | ⏳ Not implemented | Planned for future |
| SSE Output Streaming | ⏳ Not implemented | Planned for future |
| WebSocket Chat | ⏳ Not implemented | Planned for future |
| Heartbeat Monitoring | ⏳ Not implemented | Planned for future |
| Tailscale Integration | ⏳ Not implemented | Planned for future |

## Related Designs

- [Project Management LLD](./designs/project-management/LLD.md)
- [Task Engine LLD](./designs/task-engine/LLD.md)
- [Session Manager LLD](./designs/session-manager/LLD.md)
- [Agent Gateway LLD](./designs/acp-gateway/LLD.md)
- [Frontend LLD](./designs/frontend/LLD.md)
- [EARS](./designs/ears.md)

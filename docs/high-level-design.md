# OpenCode Orchestrator - High-Level Design

**Created**: 2026-03-28

## Problem Statement

Developers using AI coding agents (Claude Code, Codex, etc.) face a coordination problem: they run multiple agent sessions in parallel across different tasks, but lack a unified way to manage, monitor, and hand off those sessions across devices. Existing solutions are either cloud-hosted (losing local control), single-agent (no orchestration), or desktop-only (no mobile handoff).

We need a **local-first, project-based orchestrator** that treats AI agent sessions like managed workers — assigning tasks via tickets, isolating work in git worktrees, and allowing seamless device handoff — all while keeping code and state on the developer's own machine.

## Goals

1. **Project-based orchestration** — One project = one git repository (GitHub or any VCS provider). All orchestration is scoped to a project.
2. **Worktree-isolated sessions** — Each agent session operates in its own `git worktree`, preventing conflicts and enabling parallel work on the same repo.
3. **Task ticket system** — Inspired by Paperclip: every unit of work is a ticket with status, assigned agent, conversation thread, and audit trail. Atomic checkout prevents duplicate work.
4. **Cross-device handoff** — Inspired by happy.engineering: seamlessly continue monitoring and interacting with agent sessions from a mobile device or another machine.
5. **Agent-agnostic via ACP/A2A** — Use the Agent Communication Protocol (now merged into A2A under Linux Foundation) to connect to any agent runtime. Agents are pluggable — swap in Claude Code, Codex, or custom agents without changing the orchestrator.
6. **Local-first** — Desktop application that runs entirely on the developer's machine. No cloud accounts, no external dependencies for core functionality. Data stored in SQLite + git.

## Non-Goals

- **Personas / role-based agent hierarchy** — No org charts or CEO agents. Flat task assignment model.
- **Multi-user / team features** — Single developer use case for v1. No shared state across users.
- **Cloud hosting** — No hosted version. The app runs locally; mobile access is via network relay.
- **Agent implementation** — We orchestrate agents, we don't implement them. Agents are external processes connected via ACP/A2A.
- **CI/CD integration** — Not a build system. Agents can trigger CI, but we don't manage pipelines.

## Target Users

- **Solo developer** running multiple AI agent sessions across tasks in a single project, who wants visibility and control without juggling terminal windows.

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                    Desktop / Mobile UI                        │
│           HTMX + Alpine.js + CSS (responsive)                │
│   ┌──────────┐  ┌──────────┐  ┌────────────┐  ┌─────────┐  │
│   │ Project  │  │  Task    │  │  Session   │  │  Agent  │  │
│   │  View    │  │  Board   │  │  Monitor   │  │  Output │  │
│   └──────────┘  └──────────┘  └────────────┘  └─────────┘  │
└──────────────────────┬───────────────────────────────────────┘
                       │ HTTP + WebSocket
                       ▼
┌──────────────────────────────────────────────────────────────┐
│                  FastAPI Backend (local)                      │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │   Project    │  │    Task      │  │     Session       │  │
│  │   Manager    │  │   Engine     │  │     Manager       │  │
│  │  (git repos  │  │  (tickets,   │  │  (worktrees,      │  │
│  │   + config)  │  │   assign,    │  │   lifecycle,      │  │
│  │              │  │   track)     │  │   output capture) │  │
│  └──────────────┘  └──────────────┘  └───────────────────┘  │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐                         │
│  │  WebSocket   │  │    ACP/A2A   │                         │
│  │    Hub       │  │   Gateway    │                         │
│  │ (real-time   │  │  (agent      │                         │
│  │  sync +      │  │   discovery  │                         │
│  │  relay)      │  │   + dispatch)│                         │
│  └──────────────┘  └──────────────┘                         │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              SQLite (local storage)                   │   │
│  │  projects | tasks | sessions | agent_registry | logs │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
                       │ ACP/A2A (HTTP + SSE)
                       ▼
┌──────────────────────────────────────────────────────────────┐
│                     Agent Layer                              │
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ Claude Code │  │   Codex     │  │  Custom Agent       │ │
│  │  (ACP srv)  │  │  (ACP srv)  │  │  (any ACP server)   │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### Decision 1: Git Worktrees for Session Isolation

**Choice**: Each task ticket gets a dedicated `git worktree`. The agent assigned to that ticket operates exclusively in that worktree.

**Rationale**: Worktrees provide true filesystem isolation without the overhead of full clones. Multiple agents can work on different features of the same repo simultaneously. Merging results back is standard git merge/rebase. Cleanup is `git worktree remove`.

**Alternatives considered**:
- Docker containers per session: Too heavy for local dev, adds complexity
- Branch-only (shared worktree): Race conditions on filesystem, agents step on each other
- Separate clones: Wastes disk, harder to merge

### Decision 2: SQLite for Local State

**Choice**: SQLite as the single local database for all orchestrator state (projects, tasks, sessions, logs).

**Rationale**: Zero-config, single-file, reliable, fast for single-user workloads. Supports WAL mode for concurrent reads during WebSocket streaming. No external database process to manage. Fits the local-first philosophy perfectly.

**Alternatives considered**:
- PostgreSQL: Overkill for single-user, requires separate process
- JSON files: No query capability, no ACID guarantees
- TinyDB: Limited query language, less battle-tested

### Decision 3: ACP/A2A for Agent Communication

**Choice**: Use the ACP protocol (Python `acp-sdk`) for agent-to-agent communication, with awareness that ACP has merged into A2A.

**Rationale**: ACP provides a clean REST/HTTP-based protocol for discovering and invoking agents. The Python SDK is mature enough for our needs. Framework-agnostic — any agent that implements an ACP server endpoint can be plugged in. Supports sync, async, and SSE streaming. Migration path to A2A when the ecosystem consolidates.

**Alternatives considered**:
- Raw HTTP/custom protocol: Reinventing the wheel, no discovery standard
- MCP only: MCP is for agent-to-tool, not agent-to-agent; complementary, not a replacement
- gRPC: More performant but less developer-friendly, harder to debug

### Decision 4: WebSocket Relay for Mobile Handoff

**Choice**: The FastAPI backend serves as both the local app server and a WebSocket relay. Mobile devices connect to the same backend over the local network (or via a tunnel like Tailscale for remote access).

**Rationale**: Keeps it simple and local-first. No external relay server needed for LAN use. For remote access, Tailscale or similar mesh VPN provides secure connectivity without exposing ports. The HTMX frontend is responsive and works on mobile browsers — no native app needed for v1.

**Alternatives considered**:
- Dedicated relay server (happy.engineering style): Adds infrastructure, defeats local-first for basic use
- Native mobile app: High development cost, unnecessary when responsive web works
- Push notifications: Complex to self-host; polling/WebSocket is sufficient for v1

### Decision 5: HTMX + Alpine.js + CSS for Frontend

**Choice**: Server-rendered HTML via HTMX for most interactions, Alpine.js for small reactive elements (e.g., dropdowns, modals), vanilla CSS for styling. Minimal JavaScript.

**Rationale**: HTMX keeps the frontend simple — FastAPI renders HTML fragments, HTMX swaps them in. No build step, no node_modules, no framework churn. WebSocket extension for HTMX handles real-time agent output streaming. Alpine.js fills the gap for client-side interactivity without a full framework.

**Alternatives considered**:
- React/Vue SPA: Adds build complexity, second language ecosystem, overkill for this UI
- Pure HTMX (no JS): Some interactions (live output streaming, drag-and-drop) need a thin JS layer
- Svelte: Nice but adds compilation step, smaller ecosystem

### Decision 6: Pixi for Project Dependencies

**Choice**: Use pixi for managing Python dependencies and development environment.

**Rationale**: User preference. Pixi handles conda + pip packages, lockfiles, and cross-platform reproducibility. Single `pixi.toml` for the project.

### Decision 7: Desktop App Delivery — Browser Tab (v1), pywebview (v2)

**Choice**: For v1, the app is a FastAPI server that the user opens in their browser. For v2, wrap in pywebview for a native-feeling desktop window.

**Rationale**: Browser-tab approach is zero-friction to develop and test. pywebview can be added later as a thin wrapper without changing the architecture. The HTMX frontend is identical in both cases.

**Alternatives considered**:
- Tauri: Rust-based, powerful but adds significant build complexity for a Python project
- Electron: Heavy, pulls in Node.js ecosystem
- pywebview from day 1: Adds debugging complexity early; browser DevTools are more accessible

## Data Model Overview

```
Project
├── id, name, repo_path, vcs_url, created_at
│
├── Task (ticket)
│   ├── id, project_id, title, description, status
│   ├── assigned_agent_id, priority, created_at, updated_at
│   ├── worktree_path, branch_name
│   └── TaskMessage (conversation thread)
│       ├── id, task_id, role (user|agent|system), content, timestamp
│       └── metadata (token usage, tool calls, etc.)
│
├── Session
│   ├── id, task_id, agent_id, worktree_path
│   ├── status (running|paused|completed|failed)
│   ├── started_at, ended_at
│   └── output_log_path
│
└── AgentRegistry
    ├── id, name, type, acp_endpoint
    ├── capabilities (JSON), status (online|offline)
    └── config (JSON)
```

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| ACP/A2A ecosystem still maturing | Use `acp-sdk` now; keep agent interface thin so we can swap to A2A SDK later |
| Git worktree limits on large repos | Monitor worktree count; auto-cleanup completed sessions; warn at threshold |
| WebSocket reliability on mobile | Implement reconnection with message queue; HTMX has built-in reconnect for SSE |
| Agent processes crash or hang | Heartbeat monitoring with configurable timeout; auto-fail stuck sessions |
| SQLite write contention under heavy load | WAL mode + single-writer pattern; sufficient for single-user |

## Related Designs

- [Project Management LLD](./designs/project-management/LLD.md)
- [Task Engine LLD](./designs/task-engine/LLD.md)
- [Session Manager LLD](./designs/session-manager/LLD.md)
- [ACP Gateway LLD](./designs/acp-gateway/LLD.md)
- [Frontend & Mobile Handoff LLD](./designs/frontend/LLD.md)

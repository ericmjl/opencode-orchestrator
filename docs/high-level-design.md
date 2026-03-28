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
5. **Agent-agnostic via ACP (Agent Client Protocol)** — Use the Agent Client Protocol (JetBrains/Zed standard — JSON-RPC over stdio, bridged to WebSocket) to connect to coding agents. This is the same protocol used by Marimo, Zed, and Neovim to connect to OpenCode, Claude Code, Codex, and Gemini. Agents are pluggable subprocess-based processes.
6. **Local-first** — Desktop application that runs entirely on the developer's machine. No cloud accounts, no external dependencies for core functionality. Data stored in SQLite + git.

## Non-Goals

- **Personas / role-based agent hierarchy** — No org charts or CEO agents. Flat task assignment model.
- **Multi-user / team features** — Single developer use case for v1. No shared state across users.
- **Cloud hosting** — No hosted version. The app runs locally; mobile access is via network relay.
- **Agent implementation** — We orchestrate agents, we don't implement them. Agents are external subprocesses connected via ACP (Agent Client Protocol).
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
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │  WebSocket   │  │     ACP      │  │    Tailscale      │  │
│  │    Hub       │  │   Gateway    │  │    Funnel         │  │
│  │ (real-time   │  │  (subprocess │  │  (HTTPS tunnel    │  │
│  │  sync +      │  │   mgmt,      │  │   for mobile      │  │
│  │  streaming)  │  │   stdio-ws)  │  │   handoff)        │  │
│  └──────────────┘  └──────────────┘  └───────────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              SQLite (local storage)                   │   │
│  │  projects | tasks | sessions | agent_registry | logs │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
                       │ ACP (JSON-RPC over stdio / WebSocket)
                       ▼
┌──────────────────────────────────────────────────────────────┐
│              Agent Layer (subprocesses via ACP)               │
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │  OpenCode   │  │ Claude Code │  │  Codex / Gemini /   │ │
│  │  (primary)  │  │             │  │  any ACP agent      │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
│        ↑                ↑                    ↑              │
│     opencode acp    claude acp         <agent> acp          │
│     (stdio)         (stdio)            (stdio)              │
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

### Decision 3: ACP (Agent Client Protocol) for Agent Communication

**Choice**: Use the Agent Client Protocol (ACP) — the JetBrains/Zed standard — for connecting to coding agents. This is the same protocol Marimo uses to connect to OpenCode, Claude Code, Codex, and Gemini.

**How it works**: Agents run as subprocesses speaking JSON-RPC over stdio. The orchestrator launches each agent in ACP mode (e.g., `opencode acp`, `claude code acp`) and communicates via stdin/stdout. For WebSocket-based consumers (like the frontend), a `stdio-to-ws` bridge exposes each agent on a dedicated port. Python ACP SDK available for implementation.

**Rationale**: ACP is the emerging standard for editor-to-agent communication, adopted by Zed, Neovim, Marimo, and JetBrains. Using the same protocol means any agent that supports ACP works out of the box. Subprocess-based — fits local-first perfectly. No external servers needed.

**Alternatives considered**:
- IBM ACP / A2A (agent-to-agent): Different protocol, designed for agent-to-agent not editor-to-agent; overkill for subprocess management
- Raw HTTP/custom protocol: Reinventing the wheel, no ecosystem compatibility
- MCP only: MCP is for agent-to-tool, not orchestrator-to-agent; complementary, not a replacement
- gRPC: More performant but less developer-friendly, no existing agent support

### Decision 4: Tailscale Tunnel for Mobile Handoff

**Choice**: The FastAPI backend serves as both the local app server and a WebSocket relay. Mobile devices connect via **Tailscale Funnel** (or Tailscale mesh VPN) for secure access from anywhere on the internet. Tailscale is a required dependency, not optional.

**Rationale**: The user needs to orchestrate agents from anywhere — coffee shop, phone on the go, another machine. Tailscale Funnel exposes the local FastAPI server to the internet over HTTPS with automatic TLS, authenticated by Tailscale identity. No port forwarding, no relay server infrastructure, no cloud hosting. The HTMX frontend is responsive and works on mobile browsers.

**Alternatives considered**:
- LAN-only: Too limiting; user explicitly needs internet-wide access
- Dedicated relay server (happy.engineering style): Adds infrastructure to host and maintain
- Cloudflare Tunnel: Good but Tailscale offers mesh VPN for device-to-device too
- Native mobile app: High development cost, unnecessary when responsive web works
- ngrok: Less integrated, no mesh VPN, less secure identity model

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
├── Worktree
│   ├── id, project_id, branch_name, path, created_at
│   ├── status (active|merged|archived)
│   │
│   ├── Task (ticket) — multiple tasks per worktree
│   │   ├── id, worktree_id, title, description, status
│   │   ├── assigned_agent_id, priority, created_at, updated_at
│   │   └── TaskMessage (conversation thread)
│   │       ├── id, task_id, role (user|agent|system), content, timestamp
│   │       └── metadata (token usage, tool calls, etc.)
│   │
│   └── Session — one active session per worktree at a time
│       ├── id, worktree_id, agent_id
│       ├── status (running|paused|completed|failed)
│       ├── started_at, ended_at, pid
│       └── output_log_path
│
└── AgentRegistry
    ├── id, name, acp_command (e.g., "opencode acp")
    ├── capabilities (JSON), status (online|offline)
    └── config (JSON)
```

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| ACP ecosystem still evolving | ACP is adopted by JetBrains, Zed, Marimo — momentum is strong; keep agent interface thin regardless |
| Tailscale as hard dependency | Tailscale is free for personal use; document manual alternatives (ngrok, Cloudflare Tunnel) for users who can't use it |
| Git worktree limits on large repos | Monitor worktree count; auto-cleanup completed sessions; warn at threshold |
| WebSocket reliability on mobile | Implement reconnection with message queue; HTMX has built-in reconnect for SSE |
| Agent processes crash or hang | Heartbeat monitoring with configurable timeout; auto-fail stuck sessions |
| SQLite write contention under heavy load | WAL mode + single-writer pattern; sufficient for single-user |

## Related Designs

- [Project Management LLD](./designs/project-management/LLD.md)
- [Task Engine LLD](./designs/task-engine/LLD.md)
- [Session Manager LLD](./designs/session-manager/LLD.md)
- [ACP Agent Gateway LLD](./designs/acp-gateway/LLD.md)
- [Frontend & Mobile Handoff LLD](./designs/frontend/LLD.md)

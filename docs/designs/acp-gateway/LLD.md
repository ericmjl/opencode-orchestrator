# Agent Gateway - Low-Level Design

**Created**: 2026-03-28
**Updated**: 2026-03-29
**HLD Link**: ../../high-level-design.md

## Overview

The Agent Gateway manages communication between the orchestrator and coding agents. It handles agent discovery and registration, subprocess lifecycle (spawn, HTTP communication, kill), and provides a unified interface for sending messages to agents.

## Context

Per the HLD, agents connect via HTTP. The orchestrator uses the agent's HTTP API (`opencode serve --port X` or similar) to communicate with agents. Agents run as persistent background servers.

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│                      Agent Gateway                          │
│                                                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │   Agent      │  │  Subprocess  │  │    HTTP         │  │
│  │   Registry   │  │  Manager     │  │    Client        │  │
│  │  (discover,  │  │  (spawn,     │  │  (requests to    │  │
│  │   register,  │  │   health,    │  │   opencode       │  │
│  │   query)     │  │   kill)      │  │   serve)         │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
│                                                            │
└────────────────────────────────────────────────────────────┘
         │                │                │
         ▼                ▼                ▼
    SQLite          subprocesses      HTTP Clients
   (agent configs)  (agent PIDs)     (agent servers)
```

## Agent Discovery and Registration

Agents are registered explicitly via the API. The user specifies:
- **name**: Human-readable name (e.g., "opencode")
- **port**: Port number for the agent server
- **cwd**: Working directory (defaults to project root)

The orchestrator builds the command: `opencode serve --port <port>`

### AgentRegistry

| Field | Type | Description |
|-------|------|-------------|
| id | String (UUID) | Primary key |
| name | String | Human-readable name (e.g., "opencode") |
| command | String | Command to launch agent (e.g., "opencode serve") |
| port | Integer | Port number for the agent server |
| cwd | String | Working directory for the agent |
| capabilities | JSON (nullable) | Agent-reported capabilities after handshake |
| status | Enum | `available`, `offline`, `error`, `starting` |
| pid | Integer (nullable) | Process ID when running |
| config | JSON (nullable) | Extra configuration |
| last_seen | Timestamp (nullable) | Last successful heartbeat |
| created_at | Timestamp | Registration time |

## Subprocess Lifecycle

### Start Sequence

```
┌───────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ Session   │───→│  Build      │───→│  subprocess  │───→│  HTTP       │
│ Manager   │    │  command    │    │  .Popen      │    │  health     │
│ (request) │    │             │    │  (serve      │    │  check      │
│           │    │             │    │   mode)      │    │             │
└───────────┘    └──────────────┘    └──────────────┘    └──────────────┘
                                              │
                                              ▼
                                       ┌──────────────┐
                                       │  opencode   │
                                       │  serve      │  agent server
                                       │  --port X   │
                                       └──────────────┘
```

1. **Build command**: Use `opencode serve --port <port>`
2. **Launch subprocess**: `asyncio.create_subprocess_shell(...)` with `cwd` set to the project/worktree path
3. **Health check**: Send HTTP request to `http://127.0.0.1:<port>/global/health`
4. **Mark available**: Update status in database

### Communication Protocol

The orchestrator uses the opencode serve HTTP API:

**Create session**:
```
POST http://127.0.0.1:<port>/session
{"title": "task description"}
```

**Send message**:
```
POST http://127.0.0.1:<port>/session/<session_id>/message
{"parts": [{"type": "text", "text": "user message"}]}
```

**Response**:
```json
{
  "info": {"id": "msg-uuid", "role": "agent", ...},
  "parts": [{"type": "text", "text": "agent response"}]
}
```

### Shutdown Sequence

1. Send SIGTERM to the process
2. Wait up to 5 seconds for graceful shutdown
3. If still alive, SIGKILL

## Auto-restart Logic

The gateway includes auto-restart logic for resilience:

- If an agent is not running when a request is made, it automatically starts the agent
- The `ensure_agent_running()` function checks if the stored PID is alive
- If not alive, it spawns a new subprocess and updates the database

## API Contracts

### Agent Registry

| Endpoint | Method | Request | Response |
|----------|--------|---------|----------|
| `/api/agents` | GET | — | `AgentListResponse` |
| `/api/agents` | POST | `AgentCreateRequest` | `AgentResponse` (201) |
| `/api/agents/{id}` | GET | — | `AgentResponse` |
| `/api/agents/{id}` | PATCH | `AgentUpdateRequest` | `AgentResponse` |
| `/api/agents/{id}` | DELETE | — | 204 |

**POST /api/agents** — `AgentCreateRequest`:

```json
{
  "name": "opencode",
  "port": 4000
}
```

The orchestrator builds: `opencode serve --port 4000`

### Agent Control

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/agents/{id}/start` | POST | Start the agent server |
| `/api/agents/{id}/stop` | POST | Stop the agent server |
| `/api/agents/{id}/ping` | POST | Health check |
| `/api/agents/{id}/message` | POST | Send message to agent |

**POST /api/agents/{id}/message** — `AgentMessageRequest`:

```json
{
  "message": "say hello in 3 words"
}
```

**Response**:

```json
{
  "status": "ok",
  "message": "Hello there, friend!"
}
```

## Error Handling

| Code | Condition | Message |
|------|-----------|---------|
| 400 | Invalid port | "Port must be a number" |
| 404 | Agent not found | "Agent '{id}' not found" |
| 409 | Agent name already exists | "Agent '{name}' already registered" |
| 500 | Agent startup failed | "Failed to start: {error}" |
| 500 | Agent not responding | "Agent did not respond within 30s" |
| 500 | HTTP request failed | {error message} |

## Edge Cases

1. **Agent binary not found**: Fail at registration time with a clear error
2. **Port already in use**: Try next port or report error to user
3. **Agent crashes during request**: Auto-restart on next request
4. **Network timeout**: 30-second timeout on health checks, 120-second on message requests
5. **Multiple frontend clients**: Each request is independent - no WebSocket streaming in current implementation

## Design Decisions

### Why HTTP instead of stdio/ACP?

The original ACP-over-stdio approach (`opencode acp`) is designed for editor integration where:
- Agent starts, handles one request, exits
- Editor starts new process for next request

This doesn't work for orchestration because:
- Each request would spawn a new agent process
- No session continuity between requests
- High latency overhead

`opencode serve` provides:
- Persistent server process
- Session management
- Message history
- Better error handling

### Why not WebSocket?

HTTP is simpler for the current use case. WebSocket could be added for streaming responses in the future.

## Implementation Status

✅ Implemented (v0.1.0). Registration, start/stop, ping, message endpoints working. Uses HTTP via `opencode serve`.

## Implementation Status

✅ Implemented (v0.1.0). Registration, start/stop, ping, message endpoints working. Uses HTTP via `opencode serve`.

## Requirements

- [Agent Management EARS](./agent-management-EARS.md)

## Dependencies

- **asyncio**: Subprocess management
- **SQLite**: AgentRegistry storage
- **httpx**: HTTP client for agent communication

## Related Documents

- [High-Level Design](../../high-level-design.md)
- [Session Manager LLD](../session-manager/LLD.md)
- [Task Engine LLD](../task-engine/LLD.md)

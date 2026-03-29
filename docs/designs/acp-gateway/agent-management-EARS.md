# Agent Management - EARS

**Parent LLD**: ./LLD.md

## Agent Registration

- [x] **AGENT-REG-001**: The system shall register an agent with a unique name.
- [x] **AGENT-REG-002**: The system shall reject duplicate agent names.
- [x] **AGENT-REG-003**: The system shall auto-generate command as "opencode serve --port {port}".

## Agent Listing

- [x] **AGENT-LIST-001**: The system shall list all registered agents.
- [x] **AGENT-LIST-002**: The system shall display agent name, port, and status.

## Agent Control

- [x] **AGENT-START-001**: The system shall start the agent as a subprocess.
- [x] **AGENT-START-002**: The system shall store the process ID when agent starts.
- [x] **AGENT-START-003**: The system shall set status to "starting" on start.
- [x] **AGENT-STOP-001**: The system shall stop the agent by sending SIGTERM.
- [x] **AGENT-STOP-002**: The system shall send SIGKILL if agent doesn't stop gracefully.
- [x] **AGENT-STOP-003**: The system shall set status to "offline" on stop.

## Agent Health

- [x] **AGENT-PING-001**: The system shall perform HTTP health check to agent endpoint.
- [x] **AGENT-PING-002**: Where health check succeeds, the system shall set status to "available".
- [x] **AGENT-PING-003**: Where health check fails, the system shall set status to "error".
- [x] **AGENT-PING-004**: The system shall update last_seen timestamp on successful ping.

## Agent Communication

- [x] **AGENT-MSG-001**: The system shall create a new session with the agent.
- [x] **AGENT-MSG-002**: The system shall send messages to the agent via HTTP.
- [x] **AGENT-MSG-003**: The system shall parse agent response parts (text, thought).
- [x] **AGENT-MSG-004**: The system shall handle HTTP errors gracefully.

## Agent Deletion

- [x] **AGENT-DEL-001**: The system shall stop the agent before deletion if running.
- [x] **AGENT-DEL-002**: The system shall delete the agent registration.

## Related Documents

- [ACP Agent Gateway LLD](./LLD.md)

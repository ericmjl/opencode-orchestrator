# Scheduler - Low-Level Design

**Created**: 2026-03-28
**HLD Link**: ../../high-level-design.md

## Overview

The Scheduler translates recurring task schedules into OS-native job registrations. It is a thin adapter between the Task Engine (which owns the schedule configuration) and the host operating system's scheduler (launchd, systemd, or cron). It does not implement its own timer or cron engine.

## Context

Per the HLD, scheduled tasks are inspired by opencode-scheduler — recurring jobs that run autonomously using the OS's native scheduling infrastructure. The Scheduler component is responsible for registering, updating, and removing OS-level jobs, and for providing the entry point that the OS calls at each scheduled tick.

Inspired by: https://github.com/different-ai/opencode-scheduler

## Architecture

```
┌──────────────┐    register/remove     ┌──────────────┐    install/remove    ┌──────────────┐
│  Task Engine │───────────────────────→│   Scheduler  │────────────────────→│  OS-native   │
│  (owns cron  │                        │  (adapter)   │                     │  scheduler   │
│   config)    │                        │              │                     │  (launchd /  │
│              │←──────────────────────│              │←────────────────────│  systemd /   │
│              │    job status/health    │              │   invocation        │  cron)       │
└──────────────┘                        └──────────────┘                     └──────────────┘
                                               │
                                               │ on tick
                                               ▼
                                        ┌──────────────┐
                                        │  Callback    │
                                        │  handler     │
                                        │  (POST to    │
                                        │  Task Engine │
                                        │  /run)       │
                                        └──────────────┘
```

## Platform Backends

### macOS: launchd

Jobs are registered as plist files in `~/Library/LaunchAgents/`:

```
com.opencode-orchestrator.<project-scope>.<job-slug>.plist
```

The plist wraps a call to the orchestrator's CLI:

```xml
<key>ProgramArguments</key>
<array>
    <string>opencode-orchestrator</string>
    <string>scheduler</string>
    <string>run</string>
    <string>--project</string>
    <string>{project_id}</string>
    <string>--task</string>
    <string>{task_id}</string>
</array>
```

Schedule is translated from cron expression to `StartCalendarInterval` keys. For complex cron expressions that don't map cleanly to `StartCalendarInterval`, multiple plist entries are created (one per distinct schedule).

Load: `launchctl load <plist>`
Unload: `launchctl unload <plist>`

### Linux: systemd

Jobs are registered as systemd user service + timer units in `~/.config/systemd/user/`:

```
opencode-orchestrator-<scope>-<job-slug>.service
opencode-orchestrator-<scope>-<job-slug>.timer
```

The timer unit translates the cron expression to `OnCalendar` directives:

```ini
[Timer]
OnCalendar=*-*-* 09:00:00
Persistent=true
```

Enable: `systemctl --user enable --now <timer>`
Disable: `systemctl --user disable --now <timer>`

### Fallback: cron

When neither launchd nor systemd is available, fall back to user crontab:

```
0 9 * * * opencode-orchestrator scheduler run --project {project_id} --task {task_id}
```

Cron jobs are managed by editing the user's crontab via `crontab -`. Each job is tagged with a comment for identification:

```
# opencode-orchestrator:project=<scope>:task=<job-slug>
0 9 * * * opencode-orchestrator scheduler run --project {project_id} --task {task_id}
```

### Full Path Resolution

System-level schedulers (launchd, systemd, cron) do NOT inherit the user's shell PATH. All executables referenced in job artifacts must use fully resolved absolute paths. At registration time, the Scheduler resolves:

- **`opencode-orchestrator`** binary path via `shutil.which()` and bakes the absolute path into the plist/service/crontab entry
- **Any agent commands** referenced in the task's agent config are similarly resolved

If the binary cannot be found in PATH at registration time, the schedule request fails with a 400 error. This prevents silent failures where the OS fires a job but the command is not found.

### Platform Detection

On startup, detect the available backend:

1. macOS → use launchd
2. Linux with `systemctl --user` available → use systemd
3. Otherwise → fall back to cron

Detection is done once and cached. The active backend is logged at startup.

## Cron Expression Parsing

The Scheduler accepts standard 5-field cron expressions:

```
┌───────────── minute (0-59)
│ ┌───────────── hour (0-23)
│ │ ┌───────────── day of month (1-31)
│ │ │ ┌───────────── month (1-12)
│ │ │ │ ┌───────────── day of week (0-6, Sunday=0)
│ │ │ │ │
* * * * *
```

Validation is performed at schedule registration time. Invalid cron expressions result in a 400 error before any OS-level registration happens.

Common patterns:

| Expression | Meaning |
|------------|---------|
| `0 9 * * *` | Daily at 9:00 AM |
| `0 */6 * * *` | Every 6 hours |
| `30 8 * * 1` | Mondays at 8:30 AM |
| `0 9,17 * * *` | 9 AM and 5 PM daily |

## Callback Handler

When the OS scheduler fires a job, it calls:

```
opencode-orchestrator scheduler run --project <project_id> --task <task_id>
```

This CLI subcommand:

1. Starts a minimal FastAPI app (or sends an HTTP request to a running instance)
2. Calls the Task Engine's `/run` endpoint internally to create a new session for the task
3. Exits

### No-overlap Guarantee

The callback handler checks whether a session for this task is already `running` before starting a new one. If so, it skips this tick and logs a "skipped (previous run still active)" event.

This is a defense-in-depth measure. launchd and systemd both support `PreventIdleSleep` / no-overlap natively, but the orchestrator verifies independently.

### Timeout

Scheduled runs support an optional timeout (configurable per task, default: no timeout). If a timeout is set, the callback handler starts a watchdog that sends SIGTERM after the specified duration.

## Data Models

The Scheduler has no SQLite tables of its own. Schedule state is stored on the Task record (`schedule_cron`, `schedule_enabled`, `schedule_id`). The Scheduler reads and writes these fields via the Task Engine's API.

OS-level artifacts (plist files, systemd units, crontab entries) are the source of truth for when jobs actually fire. The `schedule_id` on the Task record is the link between the two.

## API Contracts

The Scheduler does not expose its own HTTP endpoints. It is invoked programmatically by the Task Engine:

### Internal Interface

| Method | Parameters | Description |
|--------|------------|-------------|
| `register(project_id, task_id, cron)` | project_id, task_id, cron expression | Create OS scheduler job, return schedule_id |
| `unregister(schedule_id)` | schedule_id | Remove OS scheduler job |
| `get_status(schedule_id)` | schedule_id | Check if OS job is installed and active |
| `list_jobs(project_scope)` | project scope identifier | List all OS jobs for a project scope |

The Task Engine calls these methods when the user creates, updates, or deletes a task schedule via the Task API.

## Scope and File Locations

Jobs are scoped per project to prevent collisions. The scope is derived from the project's `id`.

| Artifact | macOS | Linux (systemd) | Fallback (cron) |
|----------|-------|------------------|-----------------|
| Job config | `~/Library/LaunchAgents/com.opencode-orchestrator.<scope>.<slug>.plist` | `~/.config/systemd/user/opencode-orchestrator-<scope>-<slug>.timer` + `.service` | User crontab (tagged) |
| Logs | `~/.config/opencode-orchestrator/scheduler/<scope>/<slug>.log` | Same | Same |

## Error Handling

| Condition | Handling |
|-----------|----------|
| Invalid cron expression | 400 error at registration, no OS artifact created |
| `launchctl load` fails | Log error, return 500 from Task Engine schedule endpoint |
| `systemctl` fails | Same as above |
| `crontab` edit fails | Same as above |
| Job fires but orchestrator not running | OS scheduler retries on next tick (standard behavior). If the callback CLI can't reach the FastAPI server, it logs and exits. |
| Orphaned OS jobs (task deleted without unschedule) | Startup reconciliation: scan OS jobs, check if corresponding task exists, remove orphans |

## Edge Cases

1. **User edits OS job directly**: On next schedule update, the Scheduler overwrites the OS artifact. Manual edits are not preserved.
2. **Clock drift / timezone**: All cron expressions are interpreted in the server's local timezone. No UTC conversion. This matches the user's expectation (9 AM means 9 AM local).
3. **DST transitions**: Handled natively by launchd and systemd. Cron may behave unexpectedly during DST transitions — documented as a known limitation.
4. **Multiple projects, same cron**: Each project scope has independent OS artifacts. No collision.
5. **Orchestrator upgraded, CLI path changes**: The plist/systemd unit uses the full path to `opencode-orchestrator` resolved at registration time. If the binary moves (e.g., upgrading from `uvx` which creates a new venv), existing jobs break. Startup reconciliation detects and re-registers using the current resolved path.
6. **Project deleted with active schedules**: The project delete endpoint must call `unregister` for all scheduled tasks before deleting.

## Dependencies

- **Task Engine**: Owns the schedule configuration, calls Scheduler methods
- **CLI (`opencode-orchestrator scheduler run`)**: Entry point for scheduled invocations
- **Platform tools**: `launchctl` (macOS), `systemctl` (Linux), `crontab` (fallback)
- **subprocess**: Invoking platform tools for job management

## Design Decisions

### Why OS-native, not Python-based scheduling?

Python schedulers (APScheduler, Celery, etc.) require a running process. If the orchestrator restarts, in-memory schedules are lost. OS-native schedulers persist across reboots and orchestrator restarts. They're the right tool for "run this thing at 9 AM every day."

### Why no own SQLite tables?

The Scheduler is a thin adapter. Its only job is translating between cron expressions and OS artifacts. State lives on the Task record, which the Task Engine already manages. Adding Scheduler-specific tables would create a dual-source-of-truth problem.

### Why cron fallback?

Not all Linux systems have systemd (WSL, minimal containers, old distros). Cron is universally available on POSIX systems. The fallback ensures the feature works everywhere, even with reduced guarantees (no missed-run catch-up).

### Why a CLI subcommand for the callback, not a direct API call?

The OS scheduler needs an executable to run. The CLI subcommand is that executable. It can either start a minimal orchestrator instance or (preferred) HTTP-POST to a running instance. The CLI approach decouples the OS scheduler from the orchestrator's uptime.

## Implementation Status

⏳ Not implemented (v0.1.0). Scheduling is planned for future. Database schema supports schedule_cron, schedule_enabled, schedule_id fields but no OS-native scheduler integration yet.

## Related Documents

- [High-Level Design](../../high-level-design.md)
- [Task Engine LLD](../task-engine/LLD.md)

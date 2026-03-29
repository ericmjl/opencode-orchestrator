# Project Management - Low-Level Design

**Created**: 2026-03-28
**HLD Link**: ../../high-level-design.md

## Overview

Project Management is the entry point for the orchestrator. A **project** represents any local directory the user wants to orchestrate agent sessions against — a git repository, an Obsidian vault, a documents folder, or any other workspace. Registering a project links a directory to the orchestrator, enabling task assignment, agent session management, and (when git is present) worktree isolation.

## Context

Per the HLD, all orchestration is scoped to a project. A project is the root entity — tasks, sessions, and agent registrations all live under it. Git features (worktrees, branching) are activated automatically when the registered directory is a git repository, but git is not required for core project functionality.

The Project Manager is responsible for:

1. Registering and validating local directories as projects
2. Detecting whether the directory is a git repository and extracting git metadata when available
3. Storing project metadata in SQLite
4. Serving as the parent entity for all other features

## UI Sketch — Project List

```
┌─ OpenCode Orchestrator ─────────────────────────────────────────────────┐
│ Projects                                                      [+ New]   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  my-app                                             git ● main   │  │
│  │  /Users/dev/my-app                                               │  │
│  │  git@github.com:dev/my-app.git                                   │  │
│  │                                                                   │  │
│  │  3 tasks  │  1 running  │  2 worktrees  │  last: 2 min ago       │  │
│  │                                                                   │  │
│  │  [Tasks]  [Sessions]  [Agents]  [Settings]                       │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  obsidian-vault                                         no git   │  │
│  │  /Users/dev/obsidian-vault                                        │  │
│  │                                                                   │  │
│  │  5 tasks  │  2 running  │  last: 15 min ago                      │  │
│  │                                                                   │  │
│  │  [Tasks]  [Sessions]  [Agents]  [Settings]                       │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  data-pipeline                                      git ● main   │  │
│  │  /Users/dev/data-pipeline                                         │  │
│  │  git@github.com:dev/data-pipeline.git                             │  │
│  │                                                                   │  │
│  │  1 task   │  0 running  │  1 worktree   │  last: 1 hr ago        │  │
│  │                                                                   │  │
│  │  [Tasks]  [Sessions]  [Agents]  [Settings]                       │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

When the user clicks "+ New" to register a project:

```
┌─ Register Project ──────────────────────────────────────────────────────┐
│                                                                         │
│  Project Path:                                                         │
│  ┌─────────────────────────────────────────────────────────────┐ [📁]  │
│  │ /Users/dev/                                                │        │
│  └─────────────────────────────────────────────────────────────┘        │
│                                                                         │
│  Name (optional):                                                      │
│  ┌─────────────────────────────────────────────────────────────┐        │
│  │                                                             │        │
│  └─────────────────────────────────────────────────────────────┘        │
│                                                                         │
│                                              [Cancel]  [Register]      │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## Registration Flow

When a user registers a project, the orchestrator validates that the path exists and is a directory, then probes for git metadata (remote URL, default branch) if `.git` is present. No files are copied — the project references the existing directory on disk.

```
┌───────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────┐
│  User     │───→│  Validate    │───→│  Probe git   │───→│  Store   │
│  provides │    │  directory   │    │  metadata    │    │  in      │
│  path     │    │  exists      │    │  (optional)  │    │  SQLite  │
└───────────┘    └──────────────┘    └──────────────┘    └──────────┘
                       │
                       ▼
                 ┌──────────┐
                 │  Return   │
                 │  error    │
                 │  if not a │
                 │  directory│
                 └──────────┘
```

## Data Models

### Project

| Field | Type | Description |
|-------|------|-------------|
| id | String (UUID) | Primary key |
| name | String | Human-readable name, defaults to directory name |
| path | String (absolute path) | Absolute path to the project directory on disk |
| has_git | Boolean | Whether the directory contains a `.git` folder |
| vcs_url | String (nullable) | Remote origin URL, if git repo with remote configured |
| default_branch | String (nullable) | Default branch name (e.g., `main`), if git repo |
| created_at | Timestamp | Registration time |
| updated_at | Timestamp | Last modification time |

`has_git` is set once at registration by checking for `.git` presence. If the user initializes git later, they can re-register or trigger a re-scan.

## API Contracts

| Endpoint | Method | Request | Response |
|----------|--------|---------|----------|
| `/api/projects` | GET | — | `ProjectListResponse` |
| `/api/projects` | POST | `ProjectCreateRequest` | `ProjectResponse` (201) |
| `/api/projects/{id}` | GET | — | `ProjectDetailResponse` |
| `/api/projects/{id}` | DELETE | — | 204 No Content |
| `/api/projects/{id}/status` | GET | — | `ProjectStatusResponse` |

### POST /api/projects

**Request:**
```json
{
  "path": "/Users/dev/my-project",
  "name": "My Project"
}
```

`name` is optional. If omitted, defaults to the directory basename.

**Response (201):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "My Project",
  "path": "/Users/dev/my-project",
  "has_git": true,
  "vcs_url": "git@github.com:dev/my-project.git",
  "default_branch": "main",
  "created_at": "2026-03-28T10:00:00Z",
  "updated_at": "2026-03-28T10:00:00Z"
}
```

**Error Responses:**
- 400: Path does not exist or is not a directory
- 409: Project already registered for this path

### GET /api/projects

**Response (200):**
```json
{
  "projects": [
    {
      "id": "...",
      "name": "My Project",
      "path": "/Users/dev/my-project",
      "has_git": true,
      "vcs_url": "git@github.com:dev/my-project.git",
      "default_branch": "main",
      "active_sessions": 1,
      "created_at": "2026-03-28T10:00:00Z"
    }
  ]
}
```

### GET /api/projects/{id}

Returns full project detail including summary counts of tasks, sessions, and (if git) worktrees.

### GET /api/projects/{id}/status

**Response (200):**
```json
{
  "id": "...",
  "path_exists": true,
  "has_git": true,
  "repo_clean": true,
  "current_branch": "main",
  "active_sessions": 1,
  "pending_tasks": 5,
  "last_activity": "2026-03-28T12:00:00Z"
}
```

For non-git projects, `repo_clean` and `current_branch` are omitted.

## Error Handling

| Code | Condition | Message |
|------|-----------|---------|
| 400 | Path does not exist | "Path '/foo/bar' does not exist" |
| 400 | Path is not a directory | "Path '/foo/bar' is not a directory" |
| 404 | Project not found | "Project '{id}' not found" |
| 409 | Duplicate project path | "A project is already registered at '/foo/bar'" |

## Edge Cases

1. **Directory moved or deleted after registration**: The `/status` endpoint checks disk state. If the path is missing, the response includes `path_exists: false`. The user can update the path or delete the project.
2. **Directory initialized as git repo after registration**: User can trigger a re-scan via a future endpoint, or delete and re-register. `has_git` reflects state at registration time.
3. **No remote configured**: `vcs_url` is null. Projects without remotes (local-only git repos, non-git dirs) work fine for orchestration.
4. **Default branch detection**: Read from `git symbolic-ref refs/remotes/origin/HEAD` or fall back to `main`, then `master`. Null if not a git repo.
5. **Symlinked directories**: Resolve symlinks to their real path before storing. Prevents registering the same physical directory via different symlink paths.

## Dependencies

- **SQLite**: Project storage via the shared local database
- **git (CLI)**: Optional. Used for metadata extraction and status checks when the project directory is a git repo. Invoked via subprocess, no Python git library.
- **FastAPI**: HTTP server exposing the API endpoints
- **pathlib**: Path manipulation and validation

## Design Decisions

### Why any directory, not just git repos?

The orchestrator's core value is managing agent sessions and tasks. Git worktree isolation is a powerful feature for code projects, but many valuable use cases don't involve git — orchestrating an agent to reorganize an Obsidian vault, process a documents folder, or manage a data pipeline. Making git optional expands the tool's applicability without sacrificing its strengths for code projects.

### Why `has_git` as a stored field?

Downstream features (Session Manager, Task Engine) need to know whether worktree isolation is available. Storing this flag avoids re-probing the filesystem on every operation. The cost is that it can become stale if the user initializes git after registration — mitigated by the re-scan option.

### Why git CLI over GitPython/pygit2?

The git CLI is already a dependency for worktree management. Using subprocess calls avoids adding a heavy Python git library. The operations here are simple (check for `.git`, read remote, read default branch) and don't warrant a full git bindings library.

### Why absolute paths?

Storing absolute paths avoids ambiguity when the user runs the orchestrator from different working directories. Symlinks are resolved to their real path to prevent duplicate registrations.

## Implementation Status

✅ Implemented (v0.1.0). Full CRUD endpoints working with git detection.

## Requirements

- [Project Registration EARS](./project-registration-EARS.md)

## Related Documents

- [High-Level Design](../../high-level-design.md)

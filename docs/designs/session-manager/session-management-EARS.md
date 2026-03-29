# Session Management - EARS

**Parent LLD**: ./LLD.md

## Session Listing

- [x] **SESSION-LIST-001**: The system shall list all sessions for a project.
- [x] **SESSION-LIST-002**: The system shall filter sessions by status when requested.
- [x] **SESSION-LIST-003**: The system shall order sessions by start time (newest first).

## Session Detail

- [x] **SESSION-DETAIL-001**: The system shall display session ID, status, PID.
- [x] **SESSION-DETAIL-002**: The system shall display start and end timestamps.
- [x] **SESSION-DETAIL-003**: The system shall display associated task and agent info.

## Session Cancellation

- [x] **SESSION-CANCEL-001**: The system shall send SIGTERM to the session process on cancel.
- [x] **SESSION-CANCEL-002**: The system shall update session status to "stopping".
- [x] **SESSION-CANCEL-003**: The system shall reject cancellation of non-running sessions.

## Session Worktrees

- [x] **WORKTREE-CREATE-001**: The system shall create a git worktree for the branch.
- [x] **WORKTREE-CREATE-002**: The system shall reject worktree creation for non-git projects.
- [x] **WORKTREE-CREATE-003**: The system shall reject worktree creation if path exists.
- [x] **WORKTREE-LIST-001**: The system shall list all worktrees for a project.
- [x] **WORKTREE-DEL-001**: The system shall reject deletion of worktrees with active sessions.
- [x] **WORKTREE-DEL-002**: The system shall archive worktree in database on deletion.
- [x] **WORKTREE-DEL-003**: The system shall run git worktree remove on deletion.

## Related Documents

- [Session Manager LLD](./LLD.md)

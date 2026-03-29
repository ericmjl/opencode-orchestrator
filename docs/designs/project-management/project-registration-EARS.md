# Project Registration - EARS

**Parent LLD**: ./LLD.md

## Project Registration

- [x] **PROJ-REG-001**: The system shall validate that the provided path exists.
- [x] **PROJ-REG-002**: The system shall validate that the provided path is a directory.
- [x] **PROJ-REG-003**: The system shall detect if the directory contains a .git folder.
- [x] **PROJ-REG-004**: Where git is present, the system shall extract the remote URL.
- [x] **PROJ-REG-005**: Where git is present, the system shall detect the default branch.
- [x] **PROJ-REG-006**: The system shall reject duplicate project registrations for the same path.
- [x] **PROJ-REG-007**: The system shall auto-generate project name from directory basename if not provided.

## Project Listing

- [x] **PROJ-LIST-001**: The system shall list all registered projects ordered by creation time.
- [x] **PROJ-LIST-002**: The system shall display project name, path, and git status in the list.

## Project Detail

- [x] **PROJ-DETAIL-001**: The system shall display project name, path, and git metadata.
- [x] **PROJ-DETAIL-002**: The system shall display task count per project.
- [x] **PROJ-DETAIL-003**: The system shall display active session count per project.

## Project Status

- [x] **PROJ-STATUS-001**: The system shall verify that the project path still exists on disk.
- [x] **PROJ-STATUS-002**: Where git is present, the system shall display current branch.
- [x] **PROJ-STATUS-003**: Where git is present, the system shall display repo clean/dirty status.

## Project Deletion

- [x] **PROJ-DEL-001**: The system shall delete the project and all associated tasks, sessions, and worktrees.

## Related Documents

- [Project Management LLD](./LLD.md)

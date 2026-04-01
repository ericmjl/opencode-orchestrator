#!/usr/bin/env python3
"""
Compare OpenCode session status with orchestrator task status (HTTP only).

Use this to verify background session sync: when OpenCode reports ``busy`` for a
session, the orchestrator should flip the linked task to ``running`` (within a
few seconds). When OpenCode is ``idle`` and the session has a truthy ``summary``,
the orchestrator marks the task ``completed``.

Examples::

    pixi run python scripts/verify_session_sync.py

    pixi run python scripts/verify_session_sync.py --watch 45

    pixi run python scripts/verify_session_sync.py \\
      --orchestrator http://127.0.0.1:8179 \\
      --opencode-port 4000 \\
      --project 8c5d05d2-4db4-4508-978b-7c3c15bff7d3 \\
      --task ed063187-c7f5-4467-be92-2a7e735b8d00 \\
      --session ses_2c36af73cffeGXmANPxVjysmY7

Environment (optional, matches :mod:`opencode_orchestrator.opencode_client`)::

    OPENCODE_SERVER_PASSWORD / OPENCODE_SERVER_USERNAME — if OpenCode uses HTTP basic auth.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any

import httpx


def _auth() -> tuple[str, str] | None:
    pwd = os.environ.get("OPENCODE_SERVER_PASSWORD")
    if not pwd:
        return None
    return (os.environ.get("OPENCODE_SERVER_USERNAME", "opencode"), pwd)


def fetch_opencode_session_status(port: int, session_id: str) -> tuple[dict[str, Any], bool]:
    """Return (status object for session_id, found_in_map).

    If the session id is missing from the map, returns ``({}, False)``.
    """
    url = f"http://127.0.0.1:{port}/session/status"
    with httpx.Client(timeout=10.0, auth=_auth()) as client:
        r = client.get(url)
        r.raise_for_status()
        data = r.json()
    if not isinstance(data, dict):
        return {}, False
    entry = data.get(session_id)
    if not isinstance(entry, dict):
        return {}, False
    return entry, True


def fetch_orchestrator(
    base: str, project_id: str, task_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (task_detail_json, session_status_json)."""
    base = base.rstrip("/")
    with httpx.Client(timeout=10.0) as client:
        d = client.get(f"{base}/api/projects/{project_id}/tasks/{task_id}")
        d.raise_for_status()
        detail = d.json()
        s = client.get(f"{base}/api/projects/{project_id}/tasks/{task_id}/session-status")
        s.raise_for_status()
        session_status = s.json()
    return detail, session_status


def print_snapshot(
    opencode_port: int,
    session_id: str,
    orchestrator: str,
    project_id: str,
    task_id: str,
) -> None:
    oc, oc_seen = fetch_opencode_session_status(opencode_port, session_id)
    oc_type = oc.get("type", "?") if oc_seen else None
    detail, sess = fetch_orchestrator(orchestrator, project_id, task_id)
    task = detail.get("task") or {}
    orch_status = task.get("status", "?")
    poll_status = sess.get("status", "?")

    print("OpenCode GET /session/status")
    print(f"  session_id: {session_id}")
    if not oc_seen:
        print("  type:       (session not in map — idle or not tracked; try again while agent is active)")
    else:
        print(f"  type:       {oc_type!r}  (busy => orchestrator should drive task -> running)")
    print()
    print("Orchestrator")
    print(f"  GET .../tasks/{{id}}           task.status: {orch_status!r}")
    print(f"  GET .../session-status         status:      {poll_status!r}")
    print()
    if oc_seen and oc_type == "busy" and orch_status == "running":
        print("OK: OpenCode busy and orchestrator task is running.")
    elif oc_seen and oc_type == "busy" and orch_status != "running":
        print(
            "NOTE: OpenCode is busy but task is not running yet. "
            "Wait up to ~5s for sync, or ensure the task/session/agent match this session."
        )
    elif oc_seen and oc_type == "idle" and orch_status == "completed":
        print("OK: OpenCode idle and task completed in orchestrator.")
    else:
        print("Compare manually against your expected state (use --watch while sending a message).")


def watch_loop(
    opencode_port: int,
    session_id: str,
    orchestrator: str,
    project_id: str,
    task_id: str,
    seconds: float,
    interval: float,
) -> int:
    """Poll until ``seconds`` elapses; return 0 if busy->running observed once."""
    deadline = time.monotonic() + seconds
    saw_match = False
    while time.monotonic() < deadline:
        oc, oc_seen = fetch_opencode_session_status(opencode_port, session_id)
        oc_type = oc.get("type") if oc_seen else None
        detail, _ = fetch_orchestrator(orchestrator, project_id, task_id)
        orch_status = (detail.get("task") or {}).get("status", "?")

        ts = time.strftime("%H:%M:%S")
        ot = repr(oc_type) if oc_type is not None else "not_in_map"
        print(f"{ts}  opencode.type={ot}  orchestrator.task.status={orch_status!r}")

        if oc_type == "busy" and orch_status == "running":
            saw_match = True
            print("OK: observed busy + running (sync is working for this pair).")
            return 0

        time.sleep(interval)

    if not saw_match:
        print(
            "Exit 1: did not observe opencode.type=busy together with task.status=running. "
            "Send a message in the live session while watching, or check agent port/session id.",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Verify OpenCode vs orchestrator task status")
    p.add_argument("--orchestrator", default="http://127.0.0.1:8179", help="Orchestrator base URL")
    p.add_argument("--opencode-port", type=int, default=4000, help="OpenCode agent port")
    p.add_argument(
        "--project",
        default="8c5d05d2-4db4-4508-978b-7c3c15bff7d3",
        help="Project id",
    )
    p.add_argument(
        "--task",
        default="ed063187-c7f5-4467-be92-2a7e735b8d00",
        help="Task id",
    )
    p.add_argument(
        "--session",
        default="ses_2c36af73cffeGXmANPxVjysmY7",
        help="OpenCode session id (ses_...)",
    )
    p.add_argument(
        "--watch",
        type=float,
        metavar="SECONDS",
        default=0,
        help="Poll every 2s for this many seconds; exit 0 if busy+running seen",
    )
    p.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Poll interval when using --watch",
    )
    args = p.parse_args()

    if args.watch > 0:
        return watch_loop(
            args.opencode_port,
            args.session,
            args.orchestrator,
            args.project,
            args.task,
            args.watch,
            args.interval,
        )

    print_snapshot(
        args.opencode_port,
        args.session,
        args.orchestrator,
        args.project,
        args.task,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

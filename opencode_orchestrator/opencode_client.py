"""OpenCode HTTP API helpers for the orchestrator.

``GET /session/status`` returns a map of session id to status objects. Each value
has a ``type`` field: ``\"busy\"`` while the agent is working (including when the
user chats from the OpenCode UI), or ``\"idle\"`` when idle.

``GET /session/:id`` returns a session object. The ``summary`` field may be a
string or structured object; we treat a truthy ``summary`` as the completion
heuristic used historically by :func:`session_summary_indicates_complete`.
"""

from __future__ import annotations

import os
from typing import Any

import httpx


def opencode_http_auth() -> tuple[str, str] | None:
    """Return ``(username, password)`` when ``OPENCODE_SERVER_PASSWORD`` is set."""
    password = os.environ.get("OPENCODE_SERVER_PASSWORD")
    if not password:
        return None
    username = os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")
    return (username, password)


def httpx_auth_kw() -> dict[str, Any]:
    """Keyword args for :class:`httpx.AsyncClient` auth, if configured."""
    auth = opencode_http_auth()
    if auth is None:
        return {}
    return {"auth": auth}


def is_session_busy(status_entry: dict[str, Any] | None) -> bool:
    """Return True when OpenCode reports the session as busy."""
    if not status_entry:
        return False
    return status_entry.get("type") == "busy"


def session_summary_indicates_complete(session_json: dict[str, Any]) -> bool:
    """Match the historical orchestrator rule: truthy ``summary`` on the session body."""
    if "summary" not in session_json:
        return False
    summary = session_json["summary"]
    if isinstance(summary, str):
        return bool(summary.strip())
    return bool(summary)


async def fetch_session_status_map(
    client: httpx.AsyncClient, port: int
) -> dict[str, dict[str, Any]]:
    """GET ``/session/status`` for one agent; returns empty dict on failure."""
    try:
        resp = await client.get(
            f"http://127.0.0.1:{port}/session/status",
            timeout=httpx.Timeout(5.0),
        )
        if resp.status_code != 200:
            return {}
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


async def fetch_session_json(
    client: httpx.AsyncClient, port: int, session_id: str
) -> dict[str, Any] | None:
    """GET ``/session/:id``; returns None on failure."""
    try:
        resp = await client.get(
            f"http://127.0.0.1:{port}/session/{session_id}",
            timeout=httpx.Timeout(5.0),
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception:
        return None


async def fetch_path_info(client: httpx.AsyncClient, port: int) -> dict[str, Any] | None:
    """GET ``/path`` from OpenCode instance; returns None on failure."""
    try:
        resp = await client.get(
            f"http://127.0.0.1:{port}/path",
            timeout=httpx.Timeout(5.0),
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception:
        return None


async def fetch_pending_permissions(
    client: httpx.AsyncClient, port: int
) -> list[dict[str, Any]]:
    """GET ``/permission``; returns pending permission requests."""
    try:
        resp = await client.get(
            f"http://127.0.0.1:{port}/permission",
            timeout=httpx.Timeout(5.0),
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []


async def fetch_pending_questions(
    client: httpx.AsyncClient, port: int
) -> list[dict[str, Any]]:
    """GET ``/question``; returns pending question requests."""
    try:
        resp = await client.get(
            f"http://127.0.0.1:{port}/question",
            timeout=httpx.Timeout(5.0),
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []

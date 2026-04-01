"""Read OpenCode SQLite history for session timeline hydration."""

from __future__ import annotations

import datetime
import json
import sqlite3
from pathlib import Path
from typing import Any


def _iso_from_unix_ms(unix_ms: int) -> str:
    dt = datetime.datetime.fromtimestamp(unix_ms / 1000, tz=datetime.UTC)
    return dt.isoformat()


def resolve_opencode_db_path(path_info: dict[str, Any] | None) -> Path | None:
    """Resolve OpenCode sqlite database path from ``/path`` payload.

    :param path_info: JSON payload from OpenCode ``GET /path`` endpoint.
    :returns: Existing sqlite database path or ``None`` if unavailable.
    """
    if not path_info:
        return None

    candidates: list[Path] = []

    # Newer builds expose data directly.
    data_dir = path_info.get("data")
    if isinstance(data_dir, str) and data_dir:
        candidates.append(Path(data_dir) / "opencode.db")

    # /path currently exposes "home" + "state". Derive known fallback.
    home_dir = path_info.get("home")
    if isinstance(home_dir, str) and home_dir:
        candidates.append(Path(home_dir) / ".local" / "share" / "opencode" / "opencode.db")

    # Legacy fallback from state directory (if data path is colocated).
    state_dir = path_info.get("state")
    if isinstance(state_dir, str) and state_dir:
        candidates.append(Path(state_dir).parent / "share" / "opencode" / "opencode.db")

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return None


def load_session_messages(
    db_path: Path,
    session_id: str,
    since_time_created: int | None = None,
    since_message_id: str | None = None,
) -> list[dict[str, Any]]:
    """Load OpenCode message timeline from sqlite for one session.

    :param db_path: Path to ``opencode.db``.
    :param session_id: OpenCode session identifier.
    :param since_time_created: Cursor lower-bound for ``message.time_created``.
    :param since_message_id: Cursor tie-breaker when timestamps are equal.
    :returns: Ordered list of normalized message records.
    """
    if not db_path.exists():
        return []

    query = [
        "SELECT m.id AS message_id, m.time_created AS message_time, m.data AS message_data,",
        "       p.id AS part_id, p.time_created AS part_time, p.data AS part_data",
        "FROM message m",
        "LEFT JOIN part p ON p.message_id = m.id",
        "WHERE m.session_id = ?",
    ]
    params: list[Any] = [session_id]
    if since_time_created is not None:
        query.append("AND (m.time_created > ? OR (m.time_created = ? AND m.id > ?))")
        params.extend([since_time_created, since_time_created, since_message_id or ""])
    query.append("ORDER BY m.time_created ASC, m.id ASC, p.time_created ASC, p.id ASC")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("\n".join(query), params).fetchall()
    finally:
        conn.close()

    by_message: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in rows:
        msg_id = str(row["message_id"])
        if msg_id not in by_message:
            order.append(msg_id)
            try:
                msg_data = json.loads(row["message_data"])
            except Exception:
                msg_data = {}
            by_message[msg_id] = {
                "opencode_message_id": msg_id,
                "time_created": int(row["message_time"]),
                "role": msg_data.get("role", "assistant"),
                "message_data": msg_data,
                "parts": [],
            }

        raw_part = row["part_data"]
        if raw_part:
            try:
                part_data = json.loads(raw_part)
            except Exception:
                part_data = {}
            by_message[msg_id]["parts"].append(part_data)

    normalized: list[dict[str, Any]] = []
    for msg_id in order:
        message = by_message[msg_id]
        content_parts: list[str] = []
        for part in message["parts"]:
            part_type = part.get("type")
            if part_type == "text" and isinstance(part.get("text"), str):
                content_parts.append(part["text"])
            elif part_type == "thought" and isinstance(part.get("text"), str):
                content_parts.append(part["text"])
            elif part_type == "tool":
                state = part.get("state", {})
                output = state.get("output")
                if isinstance(output, str) and output.strip():
                    content_parts.append(output)

        if not content_parts:
            # Some OpenCode assistant failures are only recorded in message.data.error
            # without any corresponding part rows. Surface those in the timeline.
            msg_data = message.get("message_data", {})
            error_data = msg_data.get("error")
            if isinstance(error_data, dict):
                error_name = error_data.get("name")
                details = error_data.get("data")
                detail_message = ""
                status_code = None
                if isinstance(details, dict):
                    detail_message = str(details.get("message") or "").strip()
                    status_code = details.get("statusCode")
                if not detail_message:
                    detail_message = str(error_data.get("message") or "").strip()

                summary = "OpenCode error"
                if detail_message:
                    summary += f": {detail_message}"
                if status_code is not None:
                    summary += f" (status {status_code})"
                if error_name:
                    summary += f" [{error_name}]"
                content_parts.append(summary)

        normalized.append(
            {
                "opencode_message_id": message["opencode_message_id"],
                "role": message["role"],
                "content": "\n\n".join(content_parts).strip(),
                "timestamp": _iso_from_unix_ms(message["time_created"]),
                "time_created": message["time_created"],
            }
        )

    return normalized

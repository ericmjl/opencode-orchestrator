"""Background sync for OpenCode runtime + sqlite history ingestion."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

import httpx

from opencode_orchestrator.models import get_db, now
from opencode_orchestrator.orchestrator_state import transition_task_status
from opencode_orchestrator.opencode_history import (
    load_session_messages,
    resolve_opencode_db_path,
)
from opencode_orchestrator.opencode_client import (
    fetch_path_info,
    fetch_pending_permissions,
    fetch_pending_questions,
    fetch_session_json,
    fetch_session_status_map,
    httpx_auth_kw,
    is_session_busy,
    session_summary_indicates_complete,
)
from opencode_orchestrator.realtime import TaskEvent, task_event_broker
from opencode_orchestrator.realtime import publish_project_updated

logger = logging.getLogger(__name__)
_SYNC_RUN_IN_PROGRESS = False
_SYNC_NUDGE_QUEUE: asyncio.Queue[tuple[str | None, str | None, str]] = asyncio.Queue(maxsize=512)
_SYNC_PENDING_KEYS: set[str] = set()
_SYNC_PENDING_LOCK = asyncio.Lock()


async def _publish_task_updated(project_id: str, task_id: str) -> None:
    status = "unknown"
    async for db in get_db():
        status_row = await db.execute("SELECT status FROM tasks WHERE id = ?", (task_id,))
        task = await status_row.fetchone()
        status = task["status"] if task else "unknown"
        break
    await task_event_broker.publish(
        project_id, task_id, TaskEvent(name="task-status", data={"status": status})
    )
    await task_event_broker.publish(
        project_id, task_id, TaskEvent(name="task-messages", data={"taskId": task_id})
    )
    await task_event_broker.publish(
        project_id, task_id, TaskEvent(name="task-prompts", data={"taskId": task_id})
    )
    await task_event_broker.publish(
        project_id, task_id, TaskEvent(name="task-updated", data={"status": status})
    )
    await publish_project_updated(project_id)


def _nudge_key(project_id: str | None, task_id: str | None) -> str:
    return f"{project_id or '*'}:{task_id or '*'}"


async def enqueue_sync_nudge(
    project_id: str | None = None, task_id: str | None = None, reason: str = "unspecified"
) -> bool:
    """Queue a sync nudge and coalesce duplicates.

    :returns: True when enqueued, False when dropped/coalesced.
    """
    key = _nudge_key(project_id, task_id)
    async with _SYNC_PENDING_LOCK:
        if key in _SYNC_PENDING_KEYS:
            return False
        _SYNC_PENDING_KEYS.add(key)
    try:
        _SYNC_NUDGE_QUEUE.put_nowait((project_id, task_id, reason))
        return True
    except asyncio.QueueFull:
        async with _SYNC_PENDING_LOCK:
            _SYNC_PENDING_KEYS.discard(key)
        logger.warning("sync nudge queue full; dropping nudge key=%s reason=%s", key, reason)
        return False


async def _release_nudge_keys(nudges: list[tuple[str | None, str | None, str]]) -> None:
    async with _SYNC_PENDING_LOCK:
        for project_id, task_id, _reason in nudges:
            _SYNC_PENDING_KEYS.discard(_nudge_key(project_id, task_id))


async def _mark_task_and_session_running(project_id: str, task_id: str, session_id: str) -> None:
    timestamp = now()
    await transition_task_status(task_id, "running", "opencode status busy")
    async for db in get_db():
        await db.execute(
            "UPDATE sessions SET status = 'running', ended_at = NULL WHERE id = ?",
            (session_id,),
        )
        await db.commit()
    await _publish_task_updated(project_id, task_id)


async def _mark_task_and_session_completed(project_id: str, task_id: str, session_id: str) -> None:
    timestamp = now()
    await transition_task_status(task_id, "completed", "opencode session summary available")
    async for db in get_db():
        await db.execute("UPDATE tasks SET is_new = 1 WHERE id = ?", (task_id,))
        await db.execute(
            "UPDATE sessions SET status = 'completed', ended_at = ? WHERE id = ?",
            (timestamp, session_id),
        )
        await db.commit()
    await _publish_task_updated(project_id, task_id)


async def _set_waiting_state(
    project_id: str, task_id: str, session_id: str, waiting_state: str
) -> None:
    timestamp = now()
    await transition_task_status(task_id, waiting_state, f"opencode reported {waiting_state}")
    async for db in get_db():
        await db.execute(
            "UPDATE sessions SET status = ? WHERE id = ?",
            (waiting_state, session_id),
        )
        await db.commit()
    await _publish_task_updated(project_id, task_id)


async def _task_has_pending_assistant_reply(task_id: str) -> bool:
    """Return True when latest user turn is newer than imported assistant turn."""
    async for db in get_db():
        recency_row = await db.execute(
            """
            SELECT
                (
                    SELECT MAX(timestamp)
                    FROM task_messages
                    WHERE task_id = ?
                      AND role = 'user'
                      AND source = 'orchestrator'
                ) AS latest_user_timestamp,
                (
                    SELECT MAX(timestamp)
                    FROM task_messages
                    WHERE task_id = ?
                      AND role = 'assistant'
                      AND source = 'opencode_sqlite'
                ) AS latest_assistant_timestamp
            """,
            (task_id, task_id),
        )
        recency = await recency_row.fetchone()
        break

    if not recency:
        return False

    latest_user = recency["latest_user_timestamp"]
    latest_assistant = recency["latest_assistant_timestamp"]
    if latest_user is None:
        return False
    if latest_assistant is None:
        return True
    return bool(str(latest_user) > str(latest_assistant))


async def _import_session_history(
    project_id: str,
    task_id: str,
    session_id: str,
    opencode_db_path: str | None,
) -> None:
    if not opencode_db_path:
        return

    async for db in get_db():
        cursor_row = await db.execute(
            "SELECT last_time_created, last_message_id FROM opencode_sync_cursor WHERE session_id = ?",
            (session_id,),
        )
        cursor = await cursor_row.fetchone()
        legacy_truncated_row = await db.execute(
            """
            SELECT 1
            FROM task_messages
            WHERE task_id = ?
              AND source = 'opencode_sqlite'
              AND length(content) = 10000
            LIMIT 1
            """,
            (task_id,),
        )
        has_legacy_truncation = bool(await legacy_truncated_row.fetchone())
        break
    since_time = cursor["last_time_created"] if cursor and not has_legacy_truncation else None
    since_message_id = cursor["last_message_id"] if cursor and not has_legacy_truncation else None

    try:
        history = await asyncio.to_thread(
            load_session_messages,
            db_path=Path(opencode_db_path),
            session_id=session_id,
            since_time_created=since_time,
            since_message_id=since_message_id,
        )
    except Exception:
        logger.exception("failed to load OpenCode sqlite history for session=%s", session_id)
        return

    if cursor and since_message_id:
        async for db in get_db():
            exists_row = await db.execute(
                """
                SELECT 1
                FROM task_messages
                WHERE task_id = ? AND opencode_message_id = ?
                LIMIT 1
                """,
                (task_id, since_message_id),
            )
            cursor_message_exists = bool(await exists_row.fetchone())
            break
        if not cursor_message_exists:
            # Cursor may have advanced in older builds while content parsing skipped
            # some messages (e.g., assistant error-only records). Re-scan the session.
            try:
                history = await asyncio.to_thread(
                    load_session_messages,
                    db_path=Path(opencode_db_path),
                    session_id=session_id,
                    since_time_created=None,
                    since_message_id=None,
                )
            except Exception:
                logger.exception("failed to backfill OpenCode sqlite history for session=%s", session_id)
                return

    if not history:
        return

    last = history[-1]
    timestamp = now()
    inserted_message = False
    async for db in get_db():
        for msg in history:
            if not msg["content"]:
                continue
            if msg["role"] == "user":
                duplicate_user = await db.execute(
                    """
                    SELECT 1
                    FROM task_messages
                    WHERE task_id = ?
                      AND role = 'user'
                      AND source = 'orchestrator'
                      AND content = ?
                      AND ABS((julianday(timestamp) - julianday(?)) * 86400.0) <= 30
                    LIMIT 1
                    """,
                    (task_id, msg["content"], msg["timestamp"]),
                )
                if await duplicate_user.fetchone():
                    continue
            await db.execute(
                """
                INSERT INTO task_messages
                (id, task_id, role, content, metadata, source, opencode_message_id, timestamp)
                VALUES (?, ?, ?, ?, NULL, 'opencode_sqlite', ?, ?)
                ON CONFLICT(task_id, opencode_message_id) DO UPDATE SET
                    role = excluded.role,
                    content = excluded.content,
                    source = excluded.source,
                    timestamp = excluded.timestamp
                """,
                (
                    str(uuid.uuid4()),
                    task_id,
                    msg["role"],
                    msg["content"],
                    msg["opencode_message_id"],
                    msg["timestamp"],
                ),
            )
            inserted_message = True

        await db.execute(
            """
            INSERT INTO opencode_sync_cursor (session_id, last_time_created, last_message_id, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                last_time_created = excluded.last_time_created,
                last_message_id = excluded.last_message_id,
                updated_at = excluded.updated_at
            """,
            (session_id, last["time_created"], last["opencode_message_id"], timestamp),
        )
        await db.commit()
    if inserted_message:
        await _publish_task_updated(project_id, task_id)


async def sync_opencode_session_tasks_once() -> None:
    """Poll OpenCode and align task/session state + chat history."""
    global _SYNC_RUN_IN_PROGRESS
    if _SYNC_RUN_IN_PROGRESS:
        logger.debug("sync_opencode_session_tasks_once skipped: run already in progress")
        return

    _SYNC_RUN_IN_PROGRESS = True
    try:
        async for db in get_db():
            rows = await db.execute(
                """
                SELECT t.id, t.status, t.project_id, s.id AS session_id, s.agent_id, a.port
                FROM tasks t
                JOIN sessions s ON s.id = (
                    SELECT id FROM sessions WHERE task_id = t.id ORDER BY started_at DESC LIMIT 1
                )
                JOIN agent_registry a ON a.id = s.agent_id
                WHERE t.archived = 0
                  AND t.status IN ('created', 'running', 'waiting_question', 'waiting_permission')
                """
            )
            task_rows = await rows.fetchall()
            break

        if not task_rows:
            return

        by_port: dict[int, list[tuple[Any, ...]]] = {}
        for row in task_rows:
            port = row[5]
            if port is None:
                continue
            by_port.setdefault(int(port), []).append(row)

        async with httpx.AsyncClient(**httpx_auth_kw()) as client:
            for port, group in by_port.items():
                status_map = await fetch_session_status_map(client, port)
                permissions = await fetch_pending_permissions(client, port)
                questions = await fetch_pending_questions(client, port)
                path_info = await fetch_path_info(client, port)
                db_path = None
                resolved = resolve_opencode_db_path(path_info)
                if resolved:
                    db_path = str(resolved)

                waiting_permissions = {
                    item.get("sessionID")
                    for item in permissions
                    if isinstance(item, dict) and item.get("sessionID")
                }
                waiting_questions = {
                    item.get("sessionID")
                    for item in questions
                    if isinstance(item, dict) and item.get("sessionID")
                }

                for row in group:
                    task_id = row[0]
                    task_status = row[1]
                    session_id = row[3]

                    try:
                        status_entry = status_map.get(session_id)
                        busy = is_session_busy(status_entry)

                        await _import_session_history(
                            project_id=row[2],
                            task_id=task_id,
                            session_id=session_id,
                            opencode_db_path=db_path,
                        )

                        if session_id in waiting_permissions:
                            if task_status != "waiting_permission":
                                await _set_waiting_state(
                                    row[2], task_id, session_id, "waiting_permission"
                                )
                            continue

                        if session_id in waiting_questions:
                            if task_status != "waiting_question":
                                await _set_waiting_state(
                                    row[2], task_id, session_id, "waiting_question"
                                )
                            continue

                        if busy:
                            if task_status in ("completed", "waiting", "waiting_question", "waiting_permission"):
                                await _mark_task_and_session_running(row[2], task_id, session_id)
                                logger.info(
                                    "OpenCode busy: task %s -> running (session %s)",
                                    task_id,
                                    session_id,
                                )
                            continue

                        session_json = await fetch_session_json(client, port, session_id)
                        if not session_json:
                            continue

                        if not session_summary_indicates_complete(session_json):
                            continue

                        if task_status in ("running", "waiting", "waiting_question", "waiting_permission"):
                            if await _task_has_pending_assistant_reply(task_id):
                                logger.info(
                                    "OpenCode idle with summary but user turn still pending for task %s; keeping running",
                                    task_id,
                                )
                                continue
                            await _mark_task_and_session_completed(row[2], task_id, session_id)
                            logger.info(
                                "OpenCode idle with summary: task %s -> completed (session %s)",
                                task_id,
                                session_id,
                            )
                    except Exception:
                        logger.exception(
                            "session sync failed for task=%s session=%s", task_id, session_id
                        )
    finally:
        _SYNC_RUN_IN_PROGRESS = False


async def sync_opencode_nudge_worker_forever(batch_window_seconds: float = 0.12) -> None:
    """Consume queued sync nudges and run coalesced sync passes."""
    if os.environ.get("OC_DISABLE_BACKGROUND_SYNC") == "1":
        return

    while True:
        first = await _SYNC_NUDGE_QUEUE.get()
        batch = [first]
        while True:
            try:
                await asyncio.sleep(batch_window_seconds)
                while True:
                    batch.append(_SYNC_NUDGE_QUEUE.get_nowait())
            except asyncio.QueueEmpty:
                break
        await _release_nudge_keys(batch)
        try:
            await sync_opencode_session_tasks_once()
        except Exception:
            logger.exception("sync nudge worker run failed")


async def _list_active_opencode_ports() -> set[int]:
    """Return OpenCode ports for non-terminal, non-archived tasks."""
    async for db in get_db():
        rows = await db.execute(
            """
            SELECT DISTINCT a.port
            FROM tasks t
            JOIN sessions s ON s.id = (
                SELECT id FROM sessions WHERE task_id = t.id ORDER BY started_at DESC LIMIT 1
            )
            JOIN agent_registry a ON a.id = s.agent_id
            WHERE t.archived = 0
              AND t.status IN ('created', 'running', 'waiting_question', 'waiting_permission')
              AND a.port IS NOT NULL
            """
        )
        ports = {int(row[0]) for row in await rows.fetchall()}
        return ports
    return set()


def _event_payload_should_trigger_sync(raw_payload: str) -> bool:
    """Return True when a global event is relevant enough to nudge sync."""
    try:
        obj = json.loads(raw_payload)
    except Exception:
        # Unknown payload shape: play it safe and trigger.
        return True

    payload = obj.get("payload", obj) if isinstance(obj, dict) else {}
    event_type = payload.get("type") if isinstance(payload, dict) else None
    return event_type not in {"server.connected"}


async def _watch_opencode_events_for_port(
    port: int,
    *,
    min_sync_interval_seconds: float,
    reconnect_delay_seconds: float,
) -> None:
    """Watch OpenCode global SSE events and trigger debounced sync nudges."""
    loop = None
    last_sync_at = 0.0
    while True:
        try:
            async with httpx.AsyncClient(**httpx_auth_kw()) as client:
                async with client.stream(
                    "GET",
                    f"http://127.0.0.1:{port}/global/event",
                    timeout=None,
                ) as response:
                    if response.status_code != 200:
                        logger.warning(
                            "OpenCode event stream unavailable for port=%s status=%s",
                            port,
                            response.status_code,
                        )
                        await asyncio.sleep(reconnect_delay_seconds)
                        continue
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        if not _event_payload_should_trigger_sync(line[6:]):
                            continue
                        if loop is None:
                            loop = asyncio.get_running_loop()
                        now_ts = loop.time()
                        if now_ts - last_sync_at < min_sync_interval_seconds:
                            continue
                        last_sync_at = now_ts
                        try:
                            await enqueue_sync_nudge(reason=f"event:{port}")
                        except Exception:
                            logger.exception("event-driven sync nudge failed for port=%s", port)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("OpenCode event stream watcher crashed for port=%s", port)
            await asyncio.sleep(reconnect_delay_seconds)


async def sync_opencode_event_bridge_forever(port_refresh_seconds: float = 10.0) -> None:
    """Maintain per-port SSE watchers that trigger event-driven sync nudges."""
    if os.environ.get("OC_DISABLE_BACKGROUND_SYNC") == "1":
        return

    min_sync_interval_seconds = float(
        os.environ.get("OC_EVENT_SYNC_MIN_INTERVAL_SECONDS", "2.0")
    )
    reconnect_delay_seconds = float(os.environ.get("OC_EVENT_RECONNECT_SECONDS", "2.0"))
    watcher_tasks: dict[int, asyncio.Task[None]] = {}
    try:
        while True:
            active_ports = await _list_active_opencode_ports()
            existing_ports = set(watcher_tasks)

            for port in active_ports - existing_ports:
                watcher_tasks[port] = asyncio.create_task(
                    _watch_opencode_events_for_port(
                        port,
                        min_sync_interval_seconds=min_sync_interval_seconds,
                        reconnect_delay_seconds=reconnect_delay_seconds,
                    )
                )

            for port in existing_ports - active_ports:
                watcher_tasks[port].cancel()
                try:
                    await watcher_tasks[port]
                except asyncio.CancelledError:
                    pass
                watcher_tasks.pop(port, None)

            await asyncio.sleep(port_refresh_seconds)
    except asyncio.CancelledError:
        pass
    finally:
        for task in watcher_tasks.values():
            task.cancel()
        for task in watcher_tasks.values():
            try:
                await task
            except asyncio.CancelledError:
                pass


async def sync_opencode_session_tasks_forever(interval_seconds: float = 30.0) -> None:
    """Loop used by app lifespan; set ``OC_DISABLE_BACKGROUND_SYNC=1`` in tests."""
    if os.environ.get("OC_DISABLE_BACKGROUND_SYNC") == "1":
        return

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await enqueue_sync_nudge(reason="periodic")
        except Exception:
            logger.exception("failed to enqueue periodic sync nudge")

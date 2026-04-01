"""In-process pub/sub helpers for task-level realtime updates."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True, frozen=True)
class TaskEvent:
    """Realtime event scoped to a task stream."""

    name: str
    data: Any = "1"


class TaskEventBroker:
    """Publish/subscribe broker for task SSE streams."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[TaskEvent]]] = defaultdict(set)
        self._lock = asyncio.Lock()

    @staticmethod
    def stream_key(project_id: str, task_id: str) -> str:
        """Return stable key for task stream fanout."""
        return f"{project_id}:{task_id}"

    @asynccontextmanager
    async def subscribe(self, project_id: str, task_id: str):
        """Register and cleanup a queue subscriber for a task stream."""
        key = self.stream_key(project_id, task_id)
        queue: asyncio.Queue[TaskEvent] = asyncio.Queue(maxsize=32)
        async with self._lock:
            self._subscribers[key].add(queue)
        try:
            yield queue
        finally:
            async with self._lock:
                subscribers = self._subscribers.get(key)
                if subscribers is not None:
                    subscribers.discard(queue)
                    if not subscribers:
                        self._subscribers.pop(key, None)

    async def publish(self, project_id: str, task_id: str, event: TaskEvent) -> None:
        """Publish an event to all subscribers on the task stream."""
        key = self.stream_key(project_id, task_id)
        async with self._lock:
            subscribers = list(self._subscribers.get(key, set()))
        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    # If a slow consumer cannot keep up, drop this event.
                    continue


task_event_broker = TaskEventBroker()

PROJECT_BOARD_TASK_KEY = "__project_board__"


async def publish_project_updated(project_id: str) -> None:
    """Broadcast that a project's task board should refresh."""
    await task_event_broker.publish(
        project_id,
        PROJECT_BOARD_TASK_KEY,
        TaskEvent(name="project-updated"),
    )


@asynccontextmanager
async def subscribe_project_updates(project_id: str):
    """Subscribe to project-level task board updates."""
    async with task_event_broker.subscribe(project_id, PROJECT_BOARD_TASK_KEY) as queue:
        yield queue

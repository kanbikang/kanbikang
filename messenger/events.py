"""Realtime fan-out. Services queue events on the DB session; they are published only after the
transaction commits, from whichever thread committed, to the WebSocket connections of the recipients."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

_QUEUE_SIZE = 500


def emit(db: Session, user_ids: Iterable[int], payload: dict[str, Any]) -> None:
    db.info.setdefault("events", []).append((tuple(user_ids), payload))


class EventBus:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queues: defaultdict[int, set[asyncio.Queue]] = defaultdict(set)

    def bind(self, loop: asyncio.AbstractEventLoop | None) -> None:
        self._loop = loop

    # subscribe/unsubscribe/_deliver run on the event loop thread only.

    def subscribe(self, user_id: int) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_SIZE)
        self._queues[user_id].add(queue)
        return queue

    def unsubscribe(self, user_id: int, queue: asyncio.Queue) -> None:
        self._queues[user_id].discard(queue)
        if not self._queues[user_id]:
            del self._queues[user_id]

    def _deliver(self, user_ids: tuple[int, ...], payload: dict[str, Any]) -> None:
        for user_id in user_ids:
            for queue in self._queues.get(user_id, ()):
                if not queue.full():  # A client this far behind resyncs when it reconnects.
                    queue.put_nowait(payload)

    def publish(self, user_ids: tuple[int, ...], payload: dict[str, Any]) -> None:
        """Thread-safe."""
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._deliver, user_ids, payload)


def install(session_factory: sessionmaker[Session], bus: EventBus) -> None:
    @event.listens_for(session_factory, "after_commit")
    def _publish(session: Session) -> None:
        for user_ids, payload in session.info.pop("events", []):
            bus.publish(user_ids, payload)

    @event.listens_for(session_factory, "after_rollback")
    def _discard(session: Session) -> None:
        session.info.pop("events", None)

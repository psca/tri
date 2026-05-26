from __future__ import annotations

import json
import queue
import threading
from collections.abc import Iterator

from pydantic import BaseModel

from tri_timing.review import ReviewState
from tri_timing_service.models import RaceStateView


class EventBroadcaster:
    def __init__(self) -> None:
        self._subscribers: set[queue.Queue[str]] = set()
        self._lock = threading.Lock()

    def stream(self, initial_state: RaceStateView) -> Iterator[str]:
        subscriber: queue.Queue[str] = queue.Queue()
        with self._lock:
            self._subscribers.add(subscriber)

        yield "event: connected\ndata: {}\n\n"
        yield self._format_event("state", initial_state)

        try:
            while True:
                try:
                    yield subscriber.get(timeout=15)
                except queue.Empty:
                    yield ": keep-alive\n\n"
        finally:
            with self._lock:
                self._subscribers.discard(subscriber)

    def publish_state(self, state: RaceStateView) -> None:
        event = self._format_event("state", state)
        with self._lock:
            subscribers = tuple(self._subscribers)

        for subscriber in subscribers:
            subscriber.put_nowait(event)

    def publish_review(self, review: ReviewState) -> None:
        event = self._format_event("review_state", review)
        with self._lock:
            subscribers = tuple(self._subscribers)

        for subscriber in subscribers:
            subscriber.put_nowait(event)

    def _format_event(self, event: str, payload: BaseModel) -> str:
        data = json.dumps(payload.model_dump(mode="json"))
        return f"event: {event}\ndata: {data}\n\n"

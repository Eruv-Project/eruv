"""In-process event bus (KTD11: one worker, so in-memory pub/sub is enough).

The status engine publishes after each database commit; U6 subscribes for the
WebSocket fan-out and push. Handlers are called synchronously on the publishing
thread (a request worker thread or the watchdog thread), so they must be quick
and thread-safe, e.g. hand the event to an asyncio loop with
``loop.call_soon_threadsafe``. A failing handler is logged and does not affect
ingest or other handlers.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StatusChanged:
    """One status_events row: a line_state or device_health transition."""

    event_id: int
    city_id: int
    dimension: str  # "line" | "device"
    from_state: str
    to_state: str
    occurred_at: datetime  # server time
    replayed: bool  # from a backlog message: log it, do not push it individually (R22)
    mapping: dict[str, Any] | None  # break mapping on transitions into BREAK (app.mapping)
    detail: str | None
    result_id: int | None


@dataclass(frozen=True)
class ResultReceived:
    """A device message was accepted (updates "last checked" in live views)."""

    city_id: int
    result_id: int
    kind: str  # "result" | "fault"
    received_at: datetime
    backlog: bool
    end_event_distance_m: float | None


Event = StatusChanged | ResultReceived
Handler = Callable[[Event], None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: list[Handler] = []
        self._lock = threading.Lock()

    def subscribe(self, handler: Handler) -> Callable[[], None]:
        """Register a handler; returns a function that unsubscribes it."""
        with self._lock:
            self._handlers.append(handler)

        def unsubscribe() -> None:
            with self._lock:
                if handler in self._handlers:
                    self._handlers.remove(handler)

        return unsubscribe

    def publish(self, event: Event) -> None:
        with self._lock:
            handlers = list(self._handlers)
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                log.exception("event handler failed for %r", event)

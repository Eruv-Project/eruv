"""Expo push notifications for status transitions (R22).

Flow: the event bus handler (any thread) hands each event to one asyncio worker
task through ``loop.call_soon_threadsafe``, so request threads never wait on
Expo. The worker handles events in publish order.

What is pushed:
- Live line transitions into BREAK ("break") and BREAK -> OK ("recovered").
  SUSPECT_BREAK edges and AWAITING_REFERENCE -> OK are not pushed.
- Every live device transition: to DISCONNECTED, to FAULT, back to ONLINE.
- Replayed (backlog) transitions are never pushed individually (AE9). The first
  replayed event of a city records, per dimension, the visible state users last
  knew. When a live (non-backlog) message of that city arrives, the drain is
  over: one "current_state" push goes out if the city's visible state now differs
  from that baseline, and the live transitions caused by that same message in a
  dimension the baseline covers are not pushed again. A live transition of that
  message in a dimension the replay never touched (e.g. a fault after a line-only
  backlog) is not in the summary, so it is pushed as usual. This bookkeeping is
  in memory: the server is one process (KTD11); a restart mid-drain loses at most
  that one summary push.

Recipients: approved users whose ``approved_city_id`` is the city. Admins are
included only for the city they are approved for (admins read every city, but
get alerts only for their own).

Tickets and receipts: a ticket error ``DeviceNotRegistered`` deletes the token at
once; receipts are fetched ``receipt_delay_s`` later (Expo keeps them for a day)
and ``DeviceNotRegistered`` receipts delete the token too.

Sending retries a batch up to ``SEND_ATTEMPTS`` times on transport errors
(including timeouts), HTTP 5xx and 429, so a transient Expo outage does not drop
a break alert. Other 4xx answers are not retried.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from typing import Any, NamedTuple

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.events import Event, ResultReceived, StatusChanged
from app.models import ApprovalState, City, DeviceHealth, LineState, PushToken, StatusDimension, User
from app.services.status import latest_event
from app.status_engine import visible_line_state

log = logging.getLogger(__name__)

EXPO_SEND_URL = "https://exp.host/--/api/v2/push/send"
EXPO_RECEIPTS_URL = "https://exp.host/--/api/v2/push/getReceipts"
SEND_BATCH = 100  # Expo's limit per send request
RECEIPT_BATCH = 1000  # Expo's limit per getReceipts request
SEND_BACKOFF_S = (1.0, 5.0)  # wait before attempt 2 and attempt 3 (plus jitter)
SEND_ATTEMPTS = len(SEND_BACKOFF_S) + 1
SEND_JITTER_S = 0.5

TEXT_INTACT = "העירוב תקין"
TEXT_DISCONNECTED = "ניטור מנותק"
TEXT_FAULT = "תקלת ציוד"
TEXT_ONLINE = "הניטור חזר לפעול"


def break_text(mapping: dict[str, Any] | None) -> str:
    kind = (mapping or {}).get("kind")
    if kind == "between":
        return f"קרע בין עמוד {mapping['pole_a']} לעמוד {mapping['pole_b']}"
    if kind == "at_cabinet":
        return "קרע בארון הבקרה / launch box"
    if kind == "beyond_ring":
        return "קרע מעבר לטבעת הממופה (מיקום משוער)"
    return "קרע בסיב"  # "unknown": no pole ring to map onto


_DEVICE_TEXT = {
    DeviceHealth.DISCONNECTED.value: ("disconnected", TEXT_DISCONNECTED),
    DeviceHealth.FAULT.value: ("fault", TEXT_FAULT),
    DeviceHealth.ONLINE.value: ("online", TEXT_ONLINE),
}


def live_message(event: StatusChanged) -> tuple[str, str] | None:
    """(type, body) for a live transition that R22 pushes, else None."""
    if event.dimension == StatusDimension.DEVICE.value:
        return _DEVICE_TEXT.get(event.to_state)
    if event.to_state == LineState.BREAK.value:
        return "break", break_text(event.mapping)
    if event.from_state == LineState.BREAK.value and event.to_state == LineState.OK.value:
        return "recovered", TEXT_INTACT
    return None


def _visible(dimension: str, state: str) -> str:
    return visible_line_state(state).value if dimension == StatusDimension.LINE.value else state


class _CoveredResult(NamedTuple):
    """The live result whose drain summary already covered these dimensions."""

    result_id: int
    dimensions: frozenset[str]


@dataclass(frozen=True)
class _Outgoing:
    city_id: int
    type: str
    body: str


class PushService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        # Tests swap in an httpx.MockTransport; read on every request.
        self.transport: httpx.AsyncBaseTransport | None = None
        self.receipt_delay_s: float = 15 * 60
        # Backoff sleep between send attempts; tests swap in a no-op.
        self.sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[Event] | None = None
        self._worker: asyncio.Task[None] | None = None
        self._receipt_tasks: set[asyncio.Task[None]] = set()
        # city_id -> {dimension: visible state before the backlog replay}
        self._drain: dict[int, dict[str, str]] = {}
        # city_id -> (result, dimensions) whose live transitions the current-state push covered
        self._covered_result: dict[int, _CoveredResult] = {}

    # --- lifecycle (called from the app lifespan) ---------------------------------

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        self._worker = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._loop = None
        tasks = [t for t in (self._worker, *self._receipt_tasks) if t is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def wait_idle(self) -> None:
        """Wait until every queued event and due receipt check is handled (tests)."""
        if self._queue is None:
            return
        await self._queue.join()
        while self._receipt_tasks:
            await asyncio.gather(*list(self._receipt_tasks), return_exceptions=True)

    def on_event(self, event: Event) -> None:
        """Event bus handler: any thread, returns at once."""
        loop, queue = self._loop, self._queue
        if loop is None or queue is None:
            return
        with contextlib.suppress(RuntimeError):  # loop closing during shutdown
            loop.call_soon_threadsafe(queue.put_nowait, event)

    # --- event handling --------------------------------------------------------------

    async def _run(self) -> None:
        assert self._queue is not None
        while True:
            event = await self._queue.get()
            try:
                await self._handle(event)
            except Exception:
                log.exception("push handling failed for %r", event)
            finally:
                self._queue.task_done()

    async def _handle(self, event: Event) -> None:
        if isinstance(event, ResultReceived):
            if not event.backlog and event.city_id in self._drain:
                baseline = self._drain.pop(event.city_id)
                self._covered_result[event.city_id] = _CoveredResult(event.result_id, frozenset(baseline))
                outgoing = await asyncio.to_thread(self._current_state_message, event.city_id, baseline)
                if outgoing is not None:
                    await self._send(outgoing)
            return

        if event.replayed:
            self._drain.setdefault(event.city_id, {}).setdefault(
                event.dimension, _visible(event.dimension, event.from_state)
            )
            return
        covered = self._covered_result.get(event.city_id)
        if (
            covered is not None
            and event.result_id is not None
            and covered.result_id == event.result_id
            and event.dimension in covered.dimensions
        ):
            return
        message = live_message(event)
        if message is not None:
            await self._send(_Outgoing(event.city_id, *message))

    def _current_state_message(self, city_id: int, baseline: dict[str, str]) -> _Outgoing | None:
        with self._session_factory() as db:
            city = db.get(City, city_id)
            if city is None:
                return None
            texts = []
            line_now = visible_line_state(city.line_state).value
            if StatusDimension.LINE.value in baseline and baseline[StatusDimension.LINE.value] != line_now:
                if line_now == LineState.BREAK.value:
                    event = latest_event(db, city_id, StatusDimension.LINE, LineState.BREAK.value)
                    texts.append(break_text(event.mapping if event else None))
                elif line_now == LineState.OK.value:
                    texts.append(TEXT_INTACT)
            device_now = city.device_health.value
            if StatusDimension.DEVICE.value in baseline and baseline[StatusDimension.DEVICE.value] != device_now:
                texts.append(_DEVICE_TEXT[device_now][1])
        if not texts:
            return None
        return _Outgoing(city_id, "current_state", "\n".join(texts))

    # --- Expo --------------------------------------------------------------------------

    def _recipients(self, city_id: int) -> tuple[str, list[str]]:
        with self._session_factory() as db:
            city = db.get(City, city_id)
            tokens = db.scalars(
                select(PushToken.token)
                .join(User, User.id == PushToken.user_id)
                .where(User.approval_state == ApprovalState.APPROVED, User.approved_city_id == city_id)
                .order_by(PushToken.id)
            ).all()
        return (city.name if city else ""), list(tokens)

    def _delete_tokens(self, tokens: list[str]) -> None:
        if not tokens:
            return
        log.info("removing %d push token(s) Expo reports as DeviceNotRegistered", len(tokens))
        with self._session_factory() as db:
            db.execute(delete(PushToken).where(PushToken.token.in_(tokens)))
            db.commit()

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport, timeout=30.0)

    async def _send(self, outgoing: _Outgoing) -> None:
        city_name, tokens = await asyncio.to_thread(self._recipients, outgoing.city_id)
        if not tokens:
            return
        messages = [
            {
                "to": token,
                "title": city_name,
                "body": outgoing.body,
                "data": {"city_id": outgoing.city_id, "type": outgoing.type},
                "sound": "default",
                "priority": "high",
            }
            for token in tokens
        ]
        async with self._client() as client:
            for start in range(0, len(messages), SEND_BATCH):
                batch = messages[start : start + SEND_BATCH]
                tickets = await self._post_batch(client, outgoing.city_id, batch)
                if tickets is None:
                    continue
                ticket_tokens: dict[str, str] = {}
                gone: list[str] = []
                for message, ticket in zip(batch, tickets):
                    if ticket.get("status") == "ok" and ticket.get("id"):
                        ticket_tokens[ticket["id"]] = message["to"]
                    elif (ticket.get("details") or {}).get("error") == "DeviceNotRegistered":
                        gone.append(message["to"])
                    else:
                        log.warning("Expo push ticket error for city %s: %s", outgoing.city_id, ticket)
                await asyncio.to_thread(self._delete_tokens, gone)
                if ticket_tokens:
                    task = asyncio.create_task(self._check_receipts(ticket_tokens))
                    self._receipt_tasks.add(task)
                    task.add_done_callback(self._receipt_tasks.discard)

    async def _post_batch(
        self, client: httpx.AsyncClient, city_id: int, batch: list[dict[str, Any]]
    ) -> list[dict[str, Any]] | None:
        """POST one batch with bounded retries; the tickets, or None after a final failure."""
        for attempt in range(1, SEND_ATTEMPTS + 1):
            try:
                response = await client.post(EXPO_SEND_URL, json=batch)
                response.raise_for_status()
                return response.json()["data"]
            except httpx.TransportError as exc:  # includes timeouts
                error: Exception = exc
                retryable = True
            except httpx.HTTPStatusError as exc:
                error = exc
                code = exc.response.status_code
                retryable = code == 429 or code >= 500
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                error = exc
                retryable = False
            if not retryable or attempt == SEND_ATTEMPTS:
                log.error(
                    "Expo push send failed for city %s (%d messages) after %d attempt(s)",
                    city_id, len(batch), attempt, exc_info=error,
                )
                return None
            delay = SEND_BACKOFF_S[attempt - 1] + random.uniform(0, SEND_JITTER_S)
            log.warning(
                "Expo push send attempt %d for city %s failed (%r); retrying in %.1f s",
                attempt, city_id, error, delay,
            )
            await self.sleep(delay)
        return None

    async def _check_receipts(self, ticket_tokens: dict[str, str]) -> None:
        await asyncio.sleep(self.receipt_delay_s)
        ids = list(ticket_tokens)
        gone: list[str] = []
        async with self._client() as client:
            for start in range(0, len(ids), RECEIPT_BATCH):
                try:
                    response = await client.post(EXPO_RECEIPTS_URL, json={"ids": ids[start : start + RECEIPT_BATCH]})
                    response.raise_for_status()
                    receipts = response.json()["data"]
                except (httpx.HTTPError, ValueError, KeyError):
                    log.exception("Expo receipt check failed")
                    continue
                for ticket_id, receipt in receipts.items():
                    if receipt.get("status") == "ok":
                        continue
                    if (receipt.get("details") or {}).get("error") == "DeviceNotRegistered" and ticket_id in ticket_tokens:
                        gone.append(ticket_tokens[ticket_id])
                    else:
                        log.warning("Expo push receipt error: %s", receipt)
        await asyncio.to_thread(self._delete_tokens, gone)


def delete_user_tokens(db: Session, user_id: int) -> None:
    """Remove a user's push tokens (caller commits). Used when access is revoked (R20)."""
    db.execute(delete(PushToken).where(PushToken.user_id == user_id))

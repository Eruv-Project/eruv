"""Live status over WebSocket (R16, R17) and live-access revocation (R20).

Endpoint: ``GET /ws?token=<access token>[&city_id=<id>]`` (upgrade).
- The token is the same short-lived access JWT the REST API uses. The user must
  be approved. Maintainers are subscribed to their approved city (a different
  ``city_id`` is refused); admins may pass any ``city_id`` and default to their
  own approved city if they have one.
- The server always accepts, then closes with an application code on refusal:
  4401 invalid token / not approved / access revoked later, 4403 city not
  allowed, 4400 no city to subscribe to, 4404 unknown city.
- Server -> client messages (JSON):
  ``{"type": "hello", "status": <CityStatusOut>}`` first, then
  ``{"type": "status_changed", ...}`` per transition of that city,
  ``{"type": "result_received", ...}`` per accepted device result or fault
  ("last check" updates), and ``{"type": "pong"}`` answering a client
  ``{"type": "ping"}``.

The hub lives on the event loop: registry changes happen only on the loop, and
other threads reach it through ``loop.call_soon_threadsafe`` (event bus
handlers run on request threads and the watchdog thread).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, FastAPI, WebSocket
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.cities import city_status
from app.events import Event, ResultReceived
from app.models import ApprovalState, City, Role, StatusDimension, User
from app.push import delete_user_tokens
from app.security import TokenError, decode_token
from app.status_engine import visible_line_state

router = APIRouter()

CLOSE_BAD_REQUEST = 4400
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_NOT_FOUND = 4404


@dataclass(frozen=True)
class _Close:
    code: int


class _Connection:
    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        self.city_id: int | None = None  # set once authorized
        self.queue: asyncio.Queue[dict[str, Any] | _Close] = asyncio.Queue()


def event_message(event: Event) -> dict[str, Any]:
    if isinstance(event, ResultReceived):
        return {
            "type": "result_received",
            "city_id": event.city_id,
            "result_id": event.result_id,
            "kind": event.kind,
            "received_at": event.received_at.isoformat(),
            "backlog": event.backlog,
            "end_event_distance_m": event.end_event_distance_m,
        }
    is_line = event.dimension == StatusDimension.LINE.value
    return {
        "type": "status_changed",
        "event_id": event.event_id,
        "city_id": event.city_id,
        "dimension": event.dimension,
        "from_state": event.from_state,
        "to_state": event.to_state,
        # Line events only: the banner state after this event (SUSPECT_BREAK shows as OK).
        "display_line_state": visible_line_state(event.to_state).value if is_line else None,
        "occurred_at": event.occurred_at.isoformat(),
        "replayed": event.replayed,
        "mapping": event.mapping,
        "detail": event.detail,
        "result_id": event.result_id,
    }


class LiveHub:
    """Open sockets keyed by user id."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._by_user: dict[int, set[_Connection]] = {}

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()

    def stop(self) -> None:
        self._loop = None

    def _call(self, fn, *args) -> None:
        loop = self._loop
        if loop is None:
            return
        with contextlib.suppress(RuntimeError):  # loop closing during shutdown
            loop.call_soon_threadsafe(fn, *args)

    # any thread
    def on_event(self, event: Event) -> None:
        self._call(self._dispatch, event)

    def close_user(self, user_id: int, code: int = CLOSE_UNAUTHORIZED) -> None:
        self._call(self._close_user, user_id, code)

    # loop thread only
    def _dispatch(self, event: Event) -> None:
        message = event_message(event)
        for connections in self._by_user.values():
            for conn in connections:
                if conn.city_id == event.city_id:
                    conn.queue.put_nowait(message)

    def _close_user(self, user_id: int, code: int) -> None:
        for conn in self._by_user.get(user_id, ()):
            conn.queue.put_nowait(_Close(code))

    def register(self, conn: _Connection) -> None:
        self._by_user.setdefault(conn.user_id, set()).add(conn)

    def unregister(self, conn: _Connection) -> None:
        connections = self._by_user.get(conn.user_id)
        if connections is not None:
            connections.discard(conn)
            if not connections:
                del self._by_user[conn.user_id]


def revoke_live_access(app: FastAPI, db: Session, user_id: int) -> None:
    """Delete the user's push tokens and close their sockets (R20).

    Call after committing the change that revoked or narrowed the user's access
    (disable, reject, city change; role changes when U9 adds them).
    """
    delete_user_tokens(db, user_id)
    db.commit()
    app.state.live_hub.close_user(user_id)


def _authorize(app: FastAPI, user_id: int, city_id: int | None) -> tuple[int | None, int | None]:
    """(close code, None) on refusal, else (None, subscribed city id)."""
    with app.state.session_factory() as db:
        user = db.get(User, user_id)
        if user is None or user.approval_state != ApprovalState.APPROVED:
            return CLOSE_UNAUTHORIZED, None
        if user.role == Role.ADMIN:
            target = city_id if city_id is not None else user.approved_city_id
        else:
            if city_id is not None and city_id != user.approved_city_id:
                return CLOSE_FORBIDDEN, None
            target = user.approved_city_id
        if target is None:
            return CLOSE_BAD_REQUEST, None
        if db.get(City, target) is None:
            return CLOSE_NOT_FOUND, None
        return None, target


def _hello(app: FastAPI, city_id: int) -> dict[str, Any] | None:
    with app.state.session_factory() as db:
        city = db.get(City, city_id)
        if city is None:
            return None
        return {"type": "hello", "status": city_status(db, city).model_dump(mode="json")}


async def _pump(websocket: WebSocket, conn: _Connection) -> None:
    async def send() -> None:
        while True:
            item = await conn.queue.get()
            if isinstance(item, _Close):
                await websocket.close(item.code)
                return
            await websocket.send_json(item)

    async def receive() -> None:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            try:
                data = json.loads(message.get("text") or "null")
            except ValueError:
                continue
            if isinstance(data, dict) and data.get("type") == "ping":
                # Through the queue, so a pong follows everything already queued.
                conn.queue.put_nowait({"type": "pong"})

    tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task


@router.websocket("/ws")
async def live_updates(websocket: WebSocket, token: str | None = None, city_id: int | None = None) -> None:
    app: FastAPI = websocket.app
    hub: LiveHub = app.state.live_hub
    await websocket.accept()
    try:
        user_id = decode_token(app.state.settings, token, "access") if token else None
    except TokenError:
        user_id = None
    if user_id is None:
        await websocket.close(CLOSE_UNAUTHORIZED)
        return

    conn = _Connection(user_id)
    # Registered before the approval check, so a revocation committed meanwhile still closes it.
    hub.register(conn)
    try:
        code, target = await run_in_threadpool(_authorize, app, user_id, city_id)
        if code is not None:
            await websocket.close(code)
            return
        conn.city_id = target
        hello = await run_in_threadpool(_hello, app, target)
        if hello is None:
            await websocket.close(CLOSE_NOT_FOUND)
            return
        await websocket.send_json(hello)
        await _pump(websocket, conn)
    finally:
        hub.unregister(conn)

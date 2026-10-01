"""Helpers shared by the U6 tests (live updates, push, logs).

Imported as a plain module (pytest puts `tests/` on sys.path), not a fixture file.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import ApprovalState, City, Device, Pole, PushToken, Role, User
from app.security import create_token, sha256_hex
from app.services.status import set_reference

EXAMPLES = Path(__file__).resolve().parents[2] / "contracts" / "examples"
REF = 47210.0
T0 = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
EXPO_SEND = "https://exp.host/--/api/v2/push/send"
EXPO_RECEIPTS = "https://exp.host/--/api/v2/push/getReceipts"


class FakeClock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def at(self, seconds: float) -> datetime:
        self.now = T0 + timedelta(seconds=seconds)
        return self.now


def install_clock(app: FastAPI) -> FakeClock:
    clock = FakeClock()
    app.state.clock = clock
    app.state.started_at = T0 - timedelta(hours=1)
    return clock


def seed_city(db: Session, name: str, device_key: str | None = None) -> int:
    """A city with 4 poles 5 km apart along a meridian and, optionally, a device."""
    city = City(name=name, launch_offset_m=1000.0, break_tolerance_m=50.0)
    db.add(city)
    db.flush()
    if device_key:
        db.add(Device(city_id=city.id, api_key_hash=sha256_hex(device_key)))
    for n in range(4):
        lat = 31.25 + math.degrees(n * 5000.0 / 6371008.8)
        db.add(Pole(city_id=city.id, number=n + 1, lat=lat, lon=34.79))
    db.commit()
    return city.id


def seed_user(
    db: Session,
    email: str,
    city_id: int | None,
    *,
    state: ApprovalState = ApprovalState.APPROVED,
    role: Role = Role.MAINTAINER,
    push_token: str | None = None,
) -> User:
    user = User(
        name=email.split("@")[0],
        phone="050-0000000",
        email=email,
        password_hash="x",
        role=role,
        approval_state=state,
        approved_city_id=city_id,
    )
    db.add(user)
    db.flush()
    if push_token:
        db.add(PushToken(user_id=user.id, token=push_token, platform="android"))
    db.commit()
    return user


def access_token(app: FastAPI, user: User) -> str:
    return create_token(app.state.settings, user.id, "access")


def auth(app: FastAPI, user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token(app, user)}"}


def load(name: str) -> dict[str, Any]:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


class Pi:
    """Posts device messages the way the agent does, sharing one seq counter."""

    def __init__(self, client: TestClient, clock: FakeClock, key: str) -> None:
        self.client, self.clock, self.headers, self.seq = client, clock, {"X-Device-Key": key}, 0

    def heartbeat(self, at: float) -> None:
        self.clock.at(at)
        r = self.client.post("/api/device/v1/heartbeat", json=load("heartbeat.valid.json"), headers=self.headers)
        assert r.status_code == 200, r.text

    def result(self, end: float, at: float, queued_s: float = 0.4) -> None:
        self.clock.at(at)
        self.seq += 1
        body = load("result.valid.json")
        body.update(seq=self.seq, end_event_distance_m=end, fiber_length_m=end, queued_s=queued_s)
        r = self.client.post("/api/device/v1/results", json=body, headers=self.headers)
        assert r.status_code == 201, r.text

    def fault(self, at: float, queued_s: float = 0.2) -> None:
        self.clock.at(at)
        self.seq += 1
        body = load("fault.valid.json")
        body.update(seq=self.seq, queued_s=queued_s)
        r = self.client.post("/api/device/v1/faults", json=body, headers=self.headers)
        assert r.status_code == 201, r.text


def set_ref(app: FastAPI, city_id: int, length: float = REF) -> None:
    with app.state.session_factory() as s:
        set_reference(s, app.state.event_bus, city_id, length, app.state.clock())


class ExpoRecorder:
    """An httpx transport that records Expo calls and answers like Expo."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []  # every message, flattened across batches
        self.batches: list[list[dict[str, Any]]] = []
        self.receipt_requests: list[list[str]] = []
        # token -> ticket to return; default {"status": "ok", "id": "ticket-<token>"}
        self.tickets: dict[str, dict[str, Any]] = {}
        # ticket id -> receipt; default {"status": "ok"}
        self.receipts: dict[str, dict[str, Any]] = {}
        # Answers for the next send attempts, consumed in order before the normal reply:
        # an int is an HTTP status to return, an exception instance is raised.
        self.send_failures: list[int | Exception] = []
        self.send_attempts = 0
        self.sleeps: list[float] = []  # backoff delays the push sender asked for

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if str(request.url) == EXPO_SEND:
            self.send_attempts += 1
            if self.send_failures:
                failure = self.send_failures.pop(0)
                if isinstance(failure, Exception):
                    raise failure
                return httpx.Response(failure, json={"errors": [{"code": "TEST"}]})
            self.batches.append(body)
            self.sent.extend(body)
            data = [self.tickets.get(m["to"], {"status": "ok", "id": f"ticket-{m['to']}"}) for m in body]
            return httpx.Response(200, json={"data": data})
        if str(request.url) == EXPO_RECEIPTS:
            self.receipt_requests.append(body["ids"])
            return httpx.Response(200, json={"data": {i: self.receipts.get(i, {"status": "ok"}) for i in body["ids"]}})
        return httpx.Response(404)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def install_expo(app: FastAPI) -> ExpoRecorder:
    """Route the push sender to a recorder; must run before the TestClient starts."""
    recorder = ExpoRecorder()
    app.state.push.transport = recorder.transport
    app.state.push.receipt_delay_s = 0.0
    app.state.push.sleep = recorder.sleep
    return recorder


def wait_push(client: TestClient, app: FastAPI) -> None:
    """Block until the push worker has handled everything queued so far."""
    client.portal.call(app.state.push.wait_idle)

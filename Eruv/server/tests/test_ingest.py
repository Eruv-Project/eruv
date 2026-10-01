"""Device ingest wired to the status engine, watchdog and event bus (U5)."""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.events import ResultReceived, StatusChanged
from app.main import create_app
from app.db import Base
from app.models import City, Device, DeviceHealth, LineState, Pole, Result, StatusEvent
from app.security import sha256_hex
from app.services.status import set_reference
from app.services.watchdog import watchdog_tick

EXAMPLES = Path(__file__).resolve().parents[2] / "contracts" / "examples"
KEY = "device-key-for-tests"
HEADERS = {"X-Device-Key": KEY}
REF = 47210.0
T0 = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def at(self, seconds: float) -> datetime:
        self.now = T0 + timedelta(seconds=seconds)
        return self.now


@pytest.fixture
def clock(app: FastAPI) -> FakeClock:
    c = FakeClock(T0)
    app.state.clock = c
    app.state.started_at = T0 - timedelta(hours=1)
    return c


@pytest.fixture
def bus_log(app: FastAPI) -> list[Any]:
    seen: list[Any] = []
    app.state.event_bus.subscribe(seen.append)
    return seen


@pytest.fixture
def city_id(db: Session) -> int:
    city = City(name="Be'er Sheva", launch_offset_m=1000.0, break_tolerance_m=50.0)
    db.add(city)
    db.flush()
    db.add(Device(city_id=city.id, api_key_hash=sha256_hex(KEY)))
    # A straight line of 4 poles along a meridian, 5 km apart; ring closes 4 -> 1.
    for n in range(4):
        lat = 31.25 + math.degrees(n * 5000.0 / 6371008.8)
        db.add(Pole(city_id=city.id, number=n + 1, lat=lat, lon=34.79))
    db.commit()
    return city.id


def load(name: str) -> dict[str, Any]:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def result_body(seq: int, end: float | None, queued_s: float = 0.4) -> dict[str, Any]:
    body = load("result.valid.json")
    body.update(seq=seq, end_event_distance_m=end, fiber_length_m=end, queued_s=queued_s)
    return body


def fault_body(seq: int, queued_s: float = 0.2) -> dict[str, Any]:
    body = load("fault.valid.json")
    body.update(seq=seq, queued_s=queued_s)
    return body


class Pi:
    """Posts messages the way the agent does, sharing one seq counter."""

    def __init__(self, client: TestClient, clock: FakeClock) -> None:
        self.client, self.clock, self.seq = client, clock, 0

    def heartbeat(self, at: float | None = None) -> None:
        if at is not None:
            self.clock.at(at)
        r = self.client.post("/api/device/v1/heartbeat", json=load("heartbeat.valid.json"), headers=HEADERS)
        assert r.status_code == 200, r.text

    def result(self, end: float | None, at: float | None = None, queued_s: float = 0.4) -> int:
        if at is not None:
            self.clock.at(at)
        self.seq += 1
        r = self.client.post("/api/device/v1/results", json=result_body(self.seq, end, queued_s), headers=HEADERS)
        assert r.status_code == 201, r.text
        return self.seq

    def fault(self, at: float | None = None, queued_s: float = 0.2) -> None:
        if at is not None:
            self.clock.at(at)
        self.seq += 1
        r = self.client.post("/api/device/v1/faults", json=fault_body(self.seq, queued_s), headers=HEADERS)
        assert r.status_code == 201, r.text


@pytest.fixture
def pi(client: TestClient, clock: FakeClock, city_id: int) -> Pi:
    return Pi(client, clock)


def tick(app: FastAPI, at: float) -> None:
    now = app.state.clock.at(at)
    watchdog_tick(app.state.session_factory, app.state.event_bus, app.state.settings, now, app.state.started_at)


def reference(app: FastAPI, city_id: int, length: float = REF) -> None:
    with app.state.session_factory() as s:
        set_reference(s, app.state.event_bus, city_id, length, app.state.clock())


def city(app: FastAPI, city_id: int) -> City:
    with app.state.session_factory() as s:
        return s.get(City, city_id)


def log(app: FastAPI, city_id: int) -> list[tuple[str, str, str, bool]]:
    with app.state.session_factory() as s:
        rows = s.scalars(select(StatusEvent).where(StatusEvent.city_id == city_id).order_by(StatusEvent.id)).all()
        return [(e.dimension.value, e.from_state, e.to_state, e.replayed) for e in rows]


def events(app: FastAPI, city_id: int) -> list[StatusEvent]:
    with app.state.session_factory() as s:
        return list(s.scalars(select(StatusEvent).where(StatusEvent.city_id == city_id).order_by(StatusEvent.id)))


# --- contract -------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/device/v1/heartbeat", load("heartbeat.valid.json")),
        ("/api/device/v1/results", result_body(1, REF)),
        ("/api/device/v1/faults", fault_body(1)),
    ],
)
def test_unknown_or_missing_device_key_is_401(client: TestClient, city_id: int, path: str, body: dict) -> None:
    assert client.post(path, json=body, headers={"X-Device-Key": "nope"}).status_code == 401
    assert client.post(path, json=body).status_code == 401


def test_schema_invalid_bodies_are_422(client: TestClient, city_id: int, db: Session) -> None:
    missing = result_body(1, REF)
    del missing["events"]
    extra = result_body(2, REF) | {"surprise": 1}
    bad_date = result_body(3, REF) | {"measured_at": "yesterday"}
    for body in (missing, extra, bad_date):
        assert client.post("/api/device/v1/results", json=body, headers=HEADERS).status_code == 422
    assert client.post("/api/device/v1/faults", json={"seq": 1}, headers=HEADERS).status_code == 422
    assert client.post("/api/device/v1/heartbeat", json={"sent_at": "x"}, headers=HEADERS).status_code == 422
    assert (
        client.post("/api/device/v1/results", content=b"not json", headers=HEADERS | {"Content-Type": "application/json"}).status_code
        == 422
    )
    assert db.scalar(select(func.count()).select_from(Result)) == 0


def test_heartbeat_returns_server_time_and_brings_device_online(
    app: FastAPI, client: TestClient, clock: FakeClock, city_id: int, bus_log: list
) -> None:
    r = client.post("/api/device/v1/heartbeat", json=load("heartbeat.valid.json"), headers=HEADERS)
    assert r.status_code == 200
    assert datetime.fromisoformat(r.json()["server_time"]) == T0
    assert city(app, city_id).device_health == DeviceHealth.ONLINE
    assert log(app, city_id) == [("device", "DISCONNECTED", "ONLINE", False)]
    changes = [e for e in bus_log if isinstance(e, StatusChanged)]
    assert [(c.city_id, c.dimension, c.to_state) for c in changes] == [(city_id, "device", "ONLINE")]


# --- line state through ingest ------------------------------------------------------


def test_ae1_two_break_results_give_one_break_event_with_mapping(app: FastAPI, pi: Pi, city_id: int, bus_log: list) -> None:
    pi.heartbeat(0)
    reference(app, city_id)
    pi.result(13400.0, at=10)
    pi.result(13420.0, at=100)
    pi.result(13410.0, at=190)
    assert city(app, city_id).line_state == LineState.BREAK
    into_break = [e for e in events(app, city_id) if e.to_state == "BREAK"]
    assert len(into_break) == 1
    # geo 12,420 m on a ring with poles every 5 km: between pole 3 (10 km) and pole 4 (15 km), 2,420 m past 3.
    m = into_break[0].mapping
    assert (m["kind"], m["pole_a"], m["pole_b"]) == ("between", 3, 4)
    assert m["offset_from_a_m"] == pytest.approx(2420.0, abs=0.5)
    assert into_break[0].result_id is not None
    pushed = [e for e in bus_log if isinstance(e, StatusChanged) and e.to_state == "BREAK"]
    assert len(pushed) == 1 and pushed[0].replayed is False and pushed[0].mapping == m
    assert sum(isinstance(e, ResultReceived) for e in bus_log) == 3


def test_ae2_break_then_intact_logs_a_suspect_reading_only(app: FastAPI, pi: Pi, city_id: int) -> None:
    pi.heartbeat(0)
    reference(app, city_id)
    pi.result(13400.0, at=10)
    pi.result(47205.0, at=100)
    assert city(app, city_id).line_state == LineState.OK
    assert [x for x in log(app, city_id) if x[0] == "line"] == [
        ("line", "AWAITING_REFERENCE", "OK", False),
        ("line", "OK", "SUSPECT_BREAK", False),
        ("line", "SUSPECT_BREAK", "OK", False),
    ]


def test_duplicate_seq_identical_payload_is_409_and_not_double_counted(
    app: FastAPI, client: TestClient, pi: Pi, city_id: int, db: Session
) -> None:
    pi.heartbeat(0)
    reference(app, city_id)
    pi.result(13400.0, at=10)
    # same message retried after sitting in the spool: only queued_s differs
    r = client.post("/api/device/v1/results", json=result_body(1, 13400.0, queued_s=95.0), headers=HEADERS)
    assert r.status_code == 409
    assert city(app, city_id).line_state == LineState.SUSPECT_BREAK
    assert db.scalar(select(func.count()).select_from(Result)) == 1
    # duplicate fault as well
    pi.fault(at=20)
    assert client.post("/api/device/v1/faults", json=fault_body(2, queued_s=40.0), headers=HEADERS).status_code == 409


def test_lower_seq_with_different_payload_is_accepted_as_device_reset(
    app: FastAPI, client: TestClient, pi: Pi, city_id: int, db: Session
) -> None:
    pi.heartbeat(0)
    for _ in range(5):
        pi.result(REF)
    r = client.post("/api/device/v1/results", json=result_body(1, REF - 1.0), headers=HEADERS)
    assert r.status_code == 201
    assert db.scalar(select(Device.highest_seq)) == 1
    r = client.post("/api/device/v1/results", json=result_body(2, REF - 2.0), headers=HEADERS)
    assert r.status_code == 201
    assert db.scalar(select(func.count()).select_from(Result)) == 7


def test_ae8_city_without_reference_logs_results_and_never_breaks(app: FastAPI, pi: Pi, city_id: int, db: Session) -> None:
    pi.heartbeat(0)
    for i in range(4):
        pi.result(13400.0, at=10 + 90 * i)
    assert city(app, city_id).line_state == LineState.AWAITING_REFERENCE
    assert db.scalar(select(func.count()).select_from(Result)) == 4
    assert [x for x in log(app, city_id) if x[0] == "line"] == []


def test_break_then_result_120m_past_reference_is_ok_with_rebaseline_warning(app: FastAPI, pi: Pi, city_id: int) -> None:
    pi.heartbeat(0)
    reference(app, city_id)
    pi.result(13400.0, at=10)
    pi.result(13400.0, at=100)
    pi.result(REF + 120.0, at=190)
    assert city(app, city_id).line_state == LineState.OK
    last = events(app, city_id)[-1]
    assert (last.from_state, last.to_state) == ("BREAK", "OK")
    assert "fiber longer than reference" in (last.detail or "")


def test_null_end_event_is_stored_but_changes_no_state(app: FastAPI, pi: Pi, city_id: int, db: Session) -> None:
    pi.heartbeat(0)
    reference(app, city_id)
    pi.result(13400.0, at=10)
    pi.fault(at=50)
    assert city(app, city_id).device_health == DeviceHealth.FAULT
    pi.result(None, at=100)
    c = city(app, city_id)
    assert c.line_state == LineState.SUSPECT_BREAK
    assert c.device_health == DeviceHealth.FAULT  # an unusable reading is not a valid result
    assert c.last_result_at == T0 + timedelta(seconds=10)
    assert db.scalar(select(func.count()).select_from(Result)) == 3
    pi.result(13410.0, at=190)
    assert city(app, city_id).line_state == LineState.BREAK


# --- device health ----------------------------------------------------------------


def test_fault_message_then_valid_result(app: FastAPI, pi: Pi, city_id: int) -> None:
    pi.heartbeat(0)
    reference(app, city_id)
    pi.result(REF, at=5)
    pi.fault(at=10)
    c = city(app, city_id)
    assert (c.device_health, c.line_state) == (DeviceHealth.FAULT, LineState.OK)
    pi.heartbeat(15)
    assert city(app, city_id).device_health == DeviceHealth.FAULT
    pi.result(REF, at=100)
    c = city(app, city_id)
    assert (c.device_health, c.line_state) == (DeviceHealth.ONLINE, LineState.OK)


def test_ae6_disconnected_at_30s_and_heartbeat_at_31s_returns_online(app: FastAPI, pi: Pi, city_id: int) -> None:
    pi.heartbeat(0)
    tick(app, 29)
    assert city(app, city_id).device_health == DeviceHealth.ONLINE
    tick(app, 30)
    assert city(app, city_id).device_health == DeviceHealth.DISCONNECTED
    pi.heartbeat(31)
    assert city(app, city_id).device_health == DeviceHealth.ONLINE


def test_break_survives_disconnect_and_one_intact_result_returns_ok(app: FastAPI, pi: Pi, city_id: int) -> None:
    pi.heartbeat(0)
    reference(app, city_id)
    pi.result(13400.0, at=1)
    pi.result(13400.0, at=2)
    tick(app, 40)
    c = city(app, city_id)
    assert (c.device_health, c.line_state) == (DeviceHealth.DISCONNECTED, LineState.BREAK)
    pi.heartbeat(600)
    pi.result(REF, at=601)
    c = city(app, city_id)
    assert (c.device_health, c.line_state) == (DeviceHealth.ONLINE, LineState.OK)


@pytest.mark.parametrize("before", [[], [13400.0]])
def test_reconnect_then_one_break_result_is_suspect_not_break(app: FastAPI, pi: Pi, city_id: int, before: list) -> None:
    pi.heartbeat(0)
    reference(app, city_id)
    for d in before:
        pi.result(d, at=1)
    tick(app, 40)
    assert city(app, city_id).device_health == DeviceHealth.DISCONNECTED
    pi.heartbeat(600)
    pi.result(13400.0, at=601)
    assert city(app, city_id).line_state == LineState.SUSPECT_BREAK


def test_server_start_after_last_heartbeat_does_not_disconnect(app: FastAPI, pi: Pi, city_id: int, clock: FakeClock) -> None:
    pi.heartbeat(0)
    pi.result(REF, at=1)
    app.state.started_at = T0 + timedelta(minutes=5)
    tick(app, 300 + 5)
    tick(app, 300 + 25)
    pi.heartbeat(300 + 28)
    tick(app, 300 + 45)
    assert city(app, city_id).device_health == DeviceHealth.ONLINE
    assert ("device", "ONLINE", "DISCONNECTED", False) not in log(app, city_id)


def test_no_result_for_three_cadences_is_fault(app: FastAPI, pi: Pi, city_id: int) -> None:
    pi.heartbeat(0)
    pi.result(REF, at=1)
    for t in range(10, 181, 10):
        pi.heartbeat(t)
    tick(app, 180)
    assert city(app, city_id).device_health == DeviceHealth.ONLINE
    pi.heartbeat(181)
    tick(app, 181)
    assert city(app, city_id).device_health == DeviceHealth.FAULT
    pi.result(REF, at=190)
    assert city(app, city_id).device_health == DeviceHealth.ONLINE


# --- backlog --------------------------------------------------------------------


def test_ae9_drained_backlog_replays_break_and_repair(app: FastAPI, pi: Pi, city_id: int, bus_log: list) -> None:
    pi.heartbeat(0)
    reference(app, city_id)
    pi.result(REF, at=1)
    tick(app, 40)  # uplink lost
    pi.heartbeat(7200)
    # 200 spooled results: intact, then a break (from #50), then repaired (from #120)
    for i in range(200):
        end = 13400.0 if 50 <= i < 120 else REF
        pi.result(end, at=7201 + i * 0.05, queued_s=7200 - i * 36 + 181)
    assert city(app, city_id).line_state == LineState.OK
    line = [x for x in log(app, city_id) if x[0] == "line"]
    assert line[1:] == [
        ("line", "OK", "SUSPECT_BREAK", True),
        ("line", "SUSPECT_BREAK", "BREAK", True),
        ("line", "BREAK", "OK", True),
    ]
    live_breaks = [e for e in bus_log if isinstance(e, StatusChanged) and e.to_state == "BREAK" and not e.replayed]
    assert live_breaks == []


def test_backlog_fault_is_replayed(app: FastAPI, pi: Pi, city_id: int) -> None:
    pi.heartbeat(0)
    pi.fault(at=5, queued_s=500.0)
    assert log(app, city_id)[-1] == ("device", "ONLINE", "FAULT", True)


def test_fault_reported_while_disconnected_reconnects_then_faults(app: FastAPI, pi: Pi, city_id: int) -> None:
    pi.heartbeat(0)
    pi.result(REF, at=1)
    tick(app, 40)
    pi.fault(at=50, queued_s=45.0)
    assert city(app, city_id).device_health == DeviceHealth.FAULT
    assert log(app, city_id)[-2:] == [
        ("device", "DISCONNECTED", "ONLINE", False),
        ("device", "ONLINE", "FAULT", False),
    ]
    pi.heartbeat(60)
    tick(app, 61)
    assert city(app, city_id).device_health == DeviceHealth.FAULT


def test_result_before_first_heartbeat_after_outage_needs_two_break_results(
    app: FastAPI, pi: Pi, city_id: int
) -> None:
    pi.heartbeat(0)
    reference(app, city_id)
    pi.result(13400.0, at=1)
    assert city(app, city_id).line_state == LineState.SUSPECT_BREAK
    tick(app, 40)
    assert city(app, city_id).device_health == DeviceHealth.DISCONNECTED
    # the spool drains before the heartbeat loop gets through
    pi.result(13400.0, at=600)
    c = city(app, city_id)
    assert (c.device_health, c.line_state) == (DeviceHealth.ONLINE, LineState.SUSPECT_BREAK)
    assert ("device", "DISCONNECTED", "ONLINE", False) in log(app, city_id)
    tick(app, 605)  # the result also counts as a sign of life: no flap back to DISCONNECTED
    assert city(app, city_id).device_health == DeviceHealth.ONLINE
    pi.result(13410.0, at=690)
    assert city(app, city_id).line_state == LineState.BREAK


# --- a scripted day ---------------------------------------------------------------


def test_scripted_day_produces_expected_transition_log(app: FastAPI, pi: Pi, city_id: int) -> None:
    t = 0.0

    def run_until(end: float, line_end: float | None = REF, heartbeats: bool = True, results: bool = True) -> None:
        nonlocal t
        while t < end:
            t += 10
            if heartbeats:
                pi.heartbeat(t)
            if results and int(t) % 90 == 0:
                pi.result(line_end, at=t)
            tick(app, t)

    pi.heartbeat(0)
    reference(app, city_id)
    run_until(540)  # intact
    run_until(720, line_end=13400.0)  # line cut: two break results
    run_until(840, heartbeats=False, results=False)  # power cut in the cabinet
    run_until(1080, line_end=13400.0)  # back, still broken
    run_until(1350)  # repaired
    pi.fault(at=t + 1)
    run_until(1530)  # results resume: FAULT clears
    run_until(1530 + 400, results=False)  # OTDR stuck, heartbeats continue
    run_until(2100)

    assert log(app, city_id) == [
        ("device", "DISCONNECTED", "ONLINE", False),
        ("line", "AWAITING_REFERENCE", "OK", False),
        ("line", "OK", "SUSPECT_BREAK", False),
        ("line", "SUSPECT_BREAK", "BREAK", False),
        ("device", "ONLINE", "DISCONNECTED", False),
        ("device", "DISCONNECTED", "ONLINE", False),
        ("line", "BREAK", "OK", False),
        ("device", "ONLINE", "FAULT", False),
        ("device", "FAULT", "ONLINE", False),
        ("device", "ONLINE", "FAULT", False),
        ("device", "FAULT", "ONLINE", False),
    ]


# --- lifespan watchdog ------------------------------------------------------------


def test_lifespan_starts_watchdog_and_records_last_run(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'wd.db').as_posix()}",
        jwt_secret="test-secret-" + "x" * 40,
        public_base_url="https://testserver",
        watchdog_enabled=True,
    )
    application = create_app(settings)
    Base.metadata.create_all(application.state.engine)
    with TestClient(application):
        deadline = time.monotonic() + 5
        while application.state.watchdog_last_run is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert application.state.watchdog_last_run is not None

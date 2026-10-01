"""Live updates over WebSocket, the status and poles reads, and /health (R16, R17, R20, KTD12)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect

from app.models import ApprovalState, Role
from support import (
    REF,
    T0,
    Pi,
    access_token,
    auth,
    install_clock,
    install_expo,
    seed_city,
    seed_user,
    set_ref,
    wait_push,
)

KEY_A = "device-key-a"


def _until(ws, predicate, limit: int = 20) -> dict:
    for _ in range(limit):
        msg = ws.receive_json()
        if predicate(msg):
            return msg
    raise AssertionError("expected message not received")


def _assert_quiet(ws) -> None:
    """Nothing is queued for this socket: the next message is the reply to a ping."""
    ws.send_json({"type": "ping"})
    assert ws.receive_json() == {"type": "pong"}


def test_break_reaches_subscribers_of_that_city_only(app: FastAPI, client: TestClient, db: Session) -> None:
    """Verification: device ingest end to end -> WebSocket message and a recorded push."""
    clock = install_clock(app)
    expo = install_expo(app)
    city_a = seed_city(db, "Be'er Sheva", KEY_A)
    city_b = seed_city(db, "Ashdod")
    user_a = seed_user(db, "a@x.org", city_a, push_token="tok-a")
    user_b = seed_user(db, "b@x.org", city_b)
    pi = Pi(client, clock, KEY_A)
    pi.heartbeat(0)
    set_ref(app, city_a)

    with client.websocket_connect(f"/ws?token={access_token(app, user_a)}") as ws_a, client.websocket_connect(
        f"/ws?token={access_token(app, user_b)}"
    ) as ws_b:
        hello_a = ws_a.receive_json()
        assert hello_a["type"] == "hello"
        assert hello_a["status"]["id"] == city_a
        assert hello_a["status"]["line_state"] == "OK"
        assert ws_b.receive_json()["status"]["id"] == city_b

        pi.result(13400.0, at=10)
        pi.result(13410.0, at=100)

        msg = _until(ws_a, lambda m: m["type"] == "status_changed" and m["to_state"] == "BREAK")
        assert msg["city_id"] == city_a
        assert msg["dimension"] == "line"
        assert msg["from_state"] == "SUSPECT_BREAK"
        assert msg["display_line_state"] == "BREAK"
        assert msg["replayed"] is False
        assert (msg["mapping"]["kind"], msg["mapping"]["pole_a"], msg["mapping"]["pole_b"]) == ("between", 3, 4)
        _assert_quiet(ws_b)

    wait_push(client, app)
    assert [(m["to"], m["data"]["type"]) for m in expo.sent] == [("tok-a", "online"), ("tok-a", "break")]


def test_ws_streams_result_received_and_hides_suspect(app: FastAPI, client: TestClient, db: Session) -> None:
    clock = install_clock(app)
    install_expo(app)
    city_a = seed_city(db, "Be'er Sheva", KEY_A)
    user = seed_user(db, "a@x.org", city_a)
    pi = Pi(client, clock, KEY_A)
    pi.heartbeat(0)
    set_ref(app, city_a)
    with client.websocket_connect(f"/ws?token={access_token(app, user)}") as ws:
        ws.receive_json()
        pi.result(13400.0, at=10)
        first = ws.receive_json()
        assert first["type"] == "result_received"
        assert first["city_id"] == city_a and first["kind"] == "result" and first["backlog"] is False
        assert first["received_at"].startswith("2026-09-30T12:00:10")
        change = ws.receive_json()
        assert (change["to_state"], change["display_line_state"]) == ("SUSPECT_BREAK", "OK")


def test_ws_auth_and_city_scoping(app: FastAPI, client: TestClient, db: Session) -> None:
    install_expo(app)
    city_a = seed_city(db, "Be'er Sheva")
    city_b = seed_city(db, "Ashdod")
    maint = seed_user(db, "a@x.org", city_a)
    pending = seed_user(db, "p@x.org", city_a, state=ApprovalState.PENDING)
    admin = seed_user(db, "admin2@x.org", None, role=Role.ADMIN)

    def close_code(url: str) -> int:
        with client.websocket_connect(url) as ws, pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        return exc.value.code

    assert close_code("/ws?token=garbage") == 4401
    assert close_code("/ws") == 4401
    assert close_code(f"/ws?token={access_token(app, pending)}") == 4401
    assert close_code(f"/ws?token={access_token(app, maint)}&city_id={city_b}") == 4403
    assert close_code(f"/ws?token={access_token(app, admin)}") == 4400
    assert close_code(f"/ws?token={access_token(app, admin)}&city_id=999") == 4404

    with client.websocket_connect(f"/ws?token={access_token(app, admin)}&city_id={city_b}") as ws:
        assert ws.receive_json()["status"]["id"] == city_b


def test_disabling_a_user_closes_their_websocket(
    app: FastAPI, client: TestClient, db: Session, admin_headers: dict[str, str]
) -> None:
    install_expo(app)
    city_a = seed_city(db, "Be'er Sheva")
    user = seed_user(db, "a@x.org", city_a)
    other = seed_user(db, "o@x.org", city_a)
    with client.websocket_connect(f"/ws?token={access_token(app, user)}") as ws, client.websocket_connect(
        f"/ws?token={access_token(app, other)}"
    ) as ws_other:
        ws.receive_json()
        ws_other.receive_json()
        assert client.post(f"/api/admin/users/{user.id}/disable", headers=admin_headers).status_code == 200
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401
        _assert_quiet(ws_other)


def test_city_change_closes_the_users_websocket(app: FastAPI, client: TestClient, db: Session) -> None:
    install_expo(app)
    city_a = seed_city(db, "Be'er Sheva")
    city_b = seed_city(db, "Ashdod")
    user = seed_user(db, "a@x.org", city_a)
    with client.websocket_connect(f"/ws?token={access_token(app, user)}") as ws:
        ws.receive_json()
        assert client.post("/api/auth/city-change", json={"city_id": city_b}, headers=auth(app, user)).status_code == 200
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401


# --- status and poles ----------------------------------------------------------------


def test_status_reports_active_break_mapping_and_since_times(app: FastAPI, client: TestClient, db: Session) -> None:
    clock = install_clock(app)
    install_expo(app)
    city_a = seed_city(db, "Be'er Sheva", KEY_A)
    city_b = seed_city(db, "Ashdod")
    user = seed_user(db, "a@x.org", city_a)
    pi = Pi(client, clock, KEY_A)
    pi.heartbeat(0)
    set_ref(app, city_a)

    ok = client.get(f"/api/cities/{city_a}/status", headers=auth(app, user)).json()
    assert ok["line_state"] == "OK" and ok["display_line_state"] == "OK"
    assert ok["device_health"] == "ONLINE"
    assert ok["device_health_since"].startswith("2026-09-30T12:00:00")
    assert ok["active_break"] is None
    assert ok["last_result_at"] is None

    pi.result(13400.0, at=10)
    suspect = client.get(f"/api/cities/{city_a}/status", headers=auth(app, user)).json()
    assert (suspect["line_state"], suspect["display_line_state"]) == ("SUSPECT_BREAK", "OK")
    assert suspect["last_result_at"].startswith("2026-09-30T12:00:10")

    pi.result(13410.0, at=100)
    broken = client.get(f"/api/cities/{city_a}/status", headers=auth(app, user)).json()
    assert broken["display_line_state"] == "BREAK"
    assert broken["active_break"]["mapping"]["pole_a"] == 3
    assert broken["active_break"]["mapping"]["pole_b"] == 4
    assert broken["active_break"]["occurred_at"].startswith("2026-09-30T12:01:40")

    pi.result(REF, at=190)
    fixed = client.get(f"/api/cities/{city_a}/status", headers=auth(app, user)).json()
    assert fixed["line_state"] == "OK" and fixed["active_break"] is None

    assert client.get(f"/api/cities/{city_b}/status", headers=auth(app, user)).status_code == 403


def test_poles_are_scoped_and_ordered(app: FastAPI, client: TestClient, db: Session) -> None:
    city_a = seed_city(db, "Be'er Sheva")
    city_b = seed_city(db, "Ashdod")
    user = seed_user(db, "a@x.org", city_a)
    r = client.get(f"/api/cities/{city_a}/poles", headers=auth(app, user))
    assert r.status_code == 200
    poles = r.json()
    assert [p["number"] for p in poles] == [1, 2, 3, 4]
    assert set(poles[0]) == {"number", "lat", "lon"}
    assert client.get(f"/api/cities/{city_b}/poles", headers=auth(app, user)).status_code == 403


# --- /health (KTD12) -------------------------------------------------------------------


def test_health_fails_when_watchdog_has_not_run_for_30_s(app: FastAPI, client: TestClient) -> None:
    clock = install_clock(app)
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["watchdog_last_run"] is None

    app.state.watchdog_last_run = T0
    clock.at(29)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "watchdog_last_run": T0.isoformat()}

    clock.at(31)
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["status"] == "stale"
    assert T0 + timedelta(seconds=31) == clock()

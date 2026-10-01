"""Admin API: users, cities, device keys, reference setting (R24, R25, R27, AE10)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect

from app.models import City, Device, LineState, PushToken, Result, ResultKind, Role, StatusEvent, User
from conftest import create_city
from support import access_token, auth, install_expo, load, seed_city, seed_user

KEY = "device-key-a"
# seed_city: 4 poles 5 km apart on a meridian -> ring 5 + 5 + 5 + 15 = 30 km; launch 1000 m.
PERIMETER = 30000.0


def _add_message(db: Session, city_id: int, seq: int, *, fault: bool = False, end: float | None = 31000.0) -> None:
    device = db.scalar(select(Device).where(Device.city_id == city_id))
    db.add(
        Result(
            device_id=device.id,
            city_id=city_id,
            kind=ResultKind.FAULT if fault else ResultKind.RESULT,
            seq=seq,
            payload_sha256="0" * 64,
            agent_version="test",
            end_event_distance_m=None if fault else end,
            fault_kind="otdr_unresponsive" if fault else None,
            fault_detail="timeout" if fault else None,
        )
    )
    db.commit()


def _set_state(db: Session, city_id: int, state: LineState, ref: float | None = None) -> None:
    city = db.get(City, city_id)
    city.line_state = state
    city.reference_fiber_length_m = ref
    db.commit()


def _reference(client: TestClient, headers, city_id: int, **body):
    return client.post(f"/api/admin/cities/{city_id}/reference", json=body, headers=headers)


# --- access ---------------------------------------------------------------------------


def test_maintainer_gets_403_on_admin_endpoints(app: FastAPI, client: TestClient, db: Session) -> None:
    city = seed_city(db, "Be'er Sheva")
    maint = auth(app, seed_user(db, "m@x.org", city))
    assert client.get("/api/admin/cities", headers=maint).status_code == 403
    assert client.get("/api/admin/users", headers=maint).status_code == 403
    assert client.patch(f"/api/admin/cities/{city}", json={"break_tolerance_m": 10}, headers=maint).status_code == 403
    assert _reference(client, maint, city).status_code == 403
    assert client.put(f"/api/admin/cities/{city}/poles", json={"poles": []}, headers=maint).status_code == 403


# --- users ----------------------------------------------------------------------------


def test_user_list_includes_created_at(app: FastAPI, client: TestClient, db: Session, admin_headers) -> None:
    city = seed_city(db, "Be'er Sheva")
    seed_user(db, "m@x.org", city)
    items = client.get("/api/admin/users", headers=admin_headers).json()
    assert {"id", "name", "email", "phone", "role", "approval_state", "approved_city_id",
            "requested_city_id", "created_at"} <= set(items[0])


def test_promote_makes_admin_and_revokes_live_access(
    app: FastAPI, client: TestClient, db: Session, admin_headers
) -> None:
    install_expo(app)
    city = seed_city(db, "Be'er Sheva")
    user = seed_user(db, "m@x.org", city, push_token="ExponentPushToken[m]")
    with client.websocket_connect(f"/ws?token={access_token(app, user)}") as ws:
        ws.receive_json()
        r = client.post(f"/api/admin/users/{user.id}/promote", headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "admin"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401
    db.expire_all()
    assert db.get(User, user.id).role == Role.ADMIN
    assert db.scalars(select(PushToken).where(PushToken.user_id == user.id)).all() == []


def test_admin_cannot_promote_self(client: TestClient, db: Session, admin_headers) -> None:
    me = client.get("/api/admin/users", headers=admin_headers).json()[0]
    assert client.post(f"/api/admin/users/{me['id']}/promote", headers=admin_headers).status_code == 409


# --- cities and devices -----------------------------------------------------------------


def test_city_list_and_patch(client: TestClient, db: Session, admin_headers) -> None:
    city = seed_city(db, "Be'er Sheva")
    empty = create_city(client, admin_headers, "Ashdod")
    cities = {c["id"]: c for c in client.get("/api/admin/cities", headers=admin_headers).json()}
    c = cities[city]
    assert c["pole_count"] == 4 and c["has_device"] is False and c["device_key_rotated_at"] is None
    assert c["perimeter_m"] == pytest.approx(PERIMETER, rel=1e-6)
    assert cities[empty]["perimeter_m"] is None
    assert {"launch_offset_m", "break_tolerance_m", "reference_fiber_length_m", "reference_set_at",
            "line_state", "device_health"} <= set(c)

    r = client.patch(f"/api/admin/cities/{city}", json={"launch_offset_m": 800, "break_tolerance_m": 30},
                     headers=admin_headers)
    assert r.status_code == 200, r.text
    assert (r.json()["launch_offset_m"], r.json()["break_tolerance_m"]) == (800, 30)
    for bad in ({"break_tolerance_m": 0}, {"launch_offset_m": -1}, {"break_tolerance_m": None}):
        assert client.patch(f"/api/admin/cities/{city}", json=bad, headers=admin_headers).status_code == 422


def test_device_key_shown_once_and_rotation_invalidates_old_key(client: TestClient, admin_headers) -> None:
    city = create_city(client, admin_headers, "Be'er Sheva")
    r = client.post(f"/api/admin/cities/{city}/device-key", headers=admin_headers)
    assert r.status_code == 201
    old_key = r.json()["api_key"]
    listing = client.get("/api/admin/cities", headers=admin_headers)
    assert old_key not in listing.text and "api_key" not in listing.text
    assert listing.json()[0]["has_device"] is True

    hb = load("heartbeat.valid.json")
    assert client.post("/api/device/v1/heartbeat", json=hb, headers={"X-Device-Key": old_key}).status_code == 200
    new_key = client.post(f"/api/admin/cities/{city}/device-key", headers=admin_headers).json()["api_key"]
    assert new_key != old_key
    assert client.post("/api/device/v1/heartbeat", json=hb, headers={"X-Device-Key": old_key}).status_code == 401
    assert client.post("/api/device/v1/heartbeat", json=hb, headers={"X-Device-Key": new_key}).status_code == 200


# --- reference (R27, AE10) ----------------------------------------------------------------


def test_reference_moves_awaiting_to_ok(client: TestClient, db: Session, admin_headers) -> None:
    city = seed_city(db, "Be'er Sheva", device_key=KEY)
    _add_message(db, city, 1, end=31000.0)
    r = _reference(client, admin_headers, city)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reference_fiber_length_m"] == 31000.0
    assert body["line_state"] == "OK" and body["reference_set_at"]
    events = db.scalars(select(StatusEvent).where(StatusEvent.city_id == city)).all()
    assert [(e.from_state, e.to_state) for e in events] == [("AWAITING_REFERENCE", "OK")]


def test_reference_rebaselines_ok_city(client: TestClient, db: Session, admin_headers) -> None:
    city = seed_city(db, "Be'er Sheva", device_key=KEY)
    _set_state(db, city, LineState.OK, ref=30500.0)
    _add_message(db, city, 1, end=31200.0)
    r = _reference(client, admin_headers, city)
    assert r.status_code == 200, r.text
    assert r.json()["reference_fiber_length_m"] == 31200.0 and r.json()["line_state"] == "OK"


def test_reference_refused_when_latest_message_is_fault(client: TestClient, db: Session, admin_headers) -> None:
    city = seed_city(db, "Be'er Sheva", device_key=KEY)
    _add_message(db, city, 1)
    _add_message(db, city, 2, fault=True)
    r = _reference(client, admin_headers, city)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "no_valid_result"


def test_reference_refused_without_results_or_end_event(client: TestClient, db: Session, admin_headers) -> None:
    city = seed_city(db, "Be'er Sheva", device_key=KEY)
    assert _reference(client, admin_headers, city).json()["detail"]["code"] == "no_valid_result"
    _add_message(db, city, 1, end=None)
    assert _reference(client, admin_headers, city).json()["detail"]["code"] == "no_valid_result"


@pytest.mark.parametrize("state", [LineState.BREAK, LineState.SUSPECT_BREAK])
def test_ae10_reference_refused_during_break(client: TestClient, db: Session, admin_headers, state) -> None:
    city = seed_city(db, "Be'er Sheva", device_key=KEY)
    _set_state(db, city, state, ref=31000.0)
    _add_message(db, city, 1, end=12000.0)
    r = _reference(client, admin_headers, city, confirm_short=True)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "break_active"
    db.expire_all()
    c = db.get(City, city)
    assert c.reference_fiber_length_m == 31000.0 and c.line_state == state and c.reference_set_at is None


def test_reference_20_percent_short_requires_confirmation(client: TestClient, db: Session, admin_headers) -> None:
    city = seed_city(db, "Be'er Sheva", device_key=KEY)
    _add_message(db, city, 1, end=1000.0 + PERIMETER * 0.8)
    r = _reference(client, admin_headers, city)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "confirm_required"
    assert detail["fiber_length_m"] == pytest.approx(PERIMETER * 0.8)
    assert detail["perimeter_m"] == pytest.approx(PERIMETER, rel=1e-6)
    assert detail["shortfall_pct"] == pytest.approx(20.0, rel=1e-4)
    db.expire_all()
    assert db.get(City, city).reference_fiber_length_m is None

    r = _reference(client, admin_headers, city, confirm_short=True)
    assert r.status_code == 200, r.text
    assert r.json()["line_state"] == "OK"
    assert r.json()["reference_fiber_length_m"] == pytest.approx(1000.0 + PERIMETER * 0.8)

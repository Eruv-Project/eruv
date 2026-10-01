"""Push notifications (R22): recipients, Hebrew text, backlog handling, receipts, tokens."""

from __future__ import annotations

import logging

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApprovalState, PushToken, Role
from support import (
    REF,
    Pi,
    auth,
    install_clock,
    install_expo,
    seed_city,
    seed_user,
    set_ref,
    wait_push,
)

KEY_A = "device-key-a"


def _setup(app: FastAPI, client: TestClient, db: Session):
    clock = install_clock(app)
    expo = install_expo(app)
    city_a = seed_city(db, "Be'er Sheva", KEY_A)
    city_b = seed_city(db, "Ashdod")
    return clock, expo, city_a, city_b


def test_break_pushes_once_per_approved_user_of_the_city(app: FastAPI, client: TestClient, db: Session) -> None:
    clock, expo, city_a, city_b = _setup(app, client, db)
    seed_user(db, "a1@x.org", city_a, push_token="tok-a1")
    seed_user(db, "a2@x.org", city_a, push_token="tok-a2")
    seed_user(db, "pending@x.org", city_a, state=ApprovalState.PENDING, push_token="tok-pending")
    seed_user(db, "disabled@x.org", city_a, state=ApprovalState.DISABLED, push_token="tok-disabled")
    seed_user(db, "b@x.org", city_b, push_token="tok-b")
    # Admins get pushes only for the city they are approved for (R22 wording).
    seed_user(db, "admin2@x.org", None, role=Role.ADMIN, push_token="tok-admin")

    pi = Pi(client, clock, KEY_A)
    pi.heartbeat(0)
    set_ref(app, city_a)
    wait_push(client, app)
    expo.sent.clear()

    pi.result(13400.0, at=10)  # OK -> SUSPECT_BREAK: hidden, no push
    wait_push(client, app)
    assert expo.sent == []

    pi.result(13410.0, at=100)  # SUSPECT_BREAK -> BREAK
    wait_push(client, app)
    assert sorted(m["to"] for m in expo.sent) == ["tok-a1", "tok-a2"]
    msg = expo.sent[0]
    assert msg["title"] == "Be'er Sheva"
    # 13410 m - 1000 m launch box = 12410 m: between pole 3 (10 km) and pole 4 (15 km).
    assert msg["body"] == "קרע בין עמוד 3 לעמוד 4"
    assert msg["data"] == {"city_id": city_a, "type": "break"}

    expo.sent.clear()
    pi.result(REF, at=190)  # BREAK -> OK: recovery push
    wait_push(client, app)
    assert sorted(m["to"] for m in expo.sent) == ["tok-a1", "tok-a2"]
    assert expo.sent[0]["body"] == "העירוב תקין"
    assert expo.sent[0]["data"] == {"city_id": city_a, "type": "recovered"}


def test_device_transitions_push_hebrew_text(app: FastAPI, client: TestClient, db: Session) -> None:
    clock, expo, city_a, _ = _setup(app, client, db)
    seed_user(db, "a1@x.org", city_a, push_token="tok-a1")
    pi = Pi(client, clock, KEY_A)

    pi.heartbeat(0)  # DISCONNECTED -> ONLINE
    set_ref(app, city_a)  # AWAITING_REFERENCE -> OK: not pushed
    wait_push(client, app)
    assert [(m["body"], m["data"]["type"]) for m in expo.sent] == [("הניטור חזר לפעול", "online")]

    from support import FakeClock  # noqa: F401  (clock is the installed FakeClock)
    from app.services.watchdog import watchdog_tick

    expo.sent.clear()
    now = clock.at(60)  # 60 s without a heartbeat -> DISCONNECTED
    watchdog_tick(app.state.session_factory, app.state.event_bus, app.state.settings, now, app.state.started_at)
    wait_push(client, app)
    assert [(m["body"], m["data"]["type"]) for m in expo.sent] == [("ניטור מנותק", "disconnected")]


def test_break_text_for_cabinet_and_beyond_ring(app: FastAPI, client: TestClient, db: Session) -> None:
    from app.push import break_text

    assert break_text({"kind": "at_cabinet", "pole_a": 1, "pole_b": None}) == "קרע בארון הבקרה / launch box"
    assert break_text({"kind": "beyond_ring", "pole_a": 4, "pole_b": 1}) == "קרע מעבר לטבעת הממופה (מיקום משוער)"
    assert break_text({"kind": "between", "pole_a": 7, "pole_b": 8}) == "קרע בין עמוד 7 לעמוד 8"


def test_ae9_backlog_break_and_repair_sends_no_push(app: FastAPI, client: TestClient, db: Session) -> None:
    clock, expo, city_a, _ = _setup(app, client, db)
    seed_user(db, "a1@x.org", city_a, push_token="tok-a1")
    pi = Pi(client, clock, KEY_A)
    pi.heartbeat(0)
    set_ref(app, city_a)
    pi.result(REF, at=10)
    wait_push(client, app)
    expo.sent.clear()

    # The spool drains: a break confirmed and repaired, all hours old.
    pi.heartbeat(7200)
    pi.result(13400.0, at=7201, queued_s=6000)
    pi.result(13410.0, at=7202, queued_s=5900)
    pi.result(REF, at=7203, queued_s=5800)
    pi.result(REF, at=7204, queued_s=0.3)  # first live result: drain over
    wait_push(client, app)
    # The state before and after the outage is OK: nothing to report.
    assert expo.sent == []


def test_backlog_ending_in_break_sends_one_current_state_push(app: FastAPI, client: TestClient, db: Session) -> None:
    clock, expo, city_a, _ = _setup(app, client, db)
    seed_user(db, "a1@x.org", city_a, push_token="tok-a1")
    pi = Pi(client, clock, KEY_A)
    pi.heartbeat(0)
    set_ref(app, city_a)
    pi.result(REF, at=10)
    wait_push(client, app)
    expo.sent.clear()

    pi.heartbeat(7200)
    pi.result(13400.0, at=7201, queued_s=6000)
    pi.result(13410.0, at=7202, queued_s=5900)  # replayed BREAK: no push of its own
    wait_push(client, app)
    assert expo.sent == []
    pi.result(13405.0, at=7203, queued_s=0.3)  # live: drain over, still BREAK
    wait_push(client, app)
    assert len(expo.sent) == 1
    assert expo.sent[0]["body"] == "קרע בין עמוד 3 לעמוד 4"
    assert expo.sent[0]["data"] == {"city_id": city_a, "type": "current_state"}


def test_backlog_break_repaired_by_the_first_live_result_sends_nothing(
    app: FastAPI, client: TestClient, db: Session
) -> None:
    """The live BREAK -> OK that ends a drain is covered by the drain summary, which is empty here."""
    clock, expo, city_a, _ = _setup(app, client, db)
    seed_user(db, "a1@x.org", city_a, push_token="tok-a1")
    pi = Pi(client, clock, KEY_A)
    pi.heartbeat(0)
    set_ref(app, city_a)
    pi.result(REF, at=10)
    wait_push(client, app)
    expo.sent.clear()

    pi.heartbeat(7200)
    pi.result(13400.0, at=7201, queued_s=6000)
    pi.result(13410.0, at=7202, queued_s=5900)  # replayed BREAK
    pi.result(REF, at=7203, queued_s=0.3)  # live BREAK -> OK: users never saw this break
    wait_push(client, app)
    assert expo.sent == []

    # Later live transitions push as usual.
    pi.result(13400.0, at=7300)
    pi.result(13410.0, at=7390)
    wait_push(client, app)
    assert [m["data"]["type"] for m in expo.sent] == ["break"]


def test_live_fault_ending_a_line_only_drain_is_pushed(app: FastAPI, client: TestClient, db: Session) -> None:
    """The drain summary covers only replayed dimensions; a live fault in another one still pushes."""
    clock, expo, city_a, _ = _setup(app, client, db)
    seed_user(db, "a1@x.org", city_a, push_token="tok-a1")
    pi = Pi(client, clock, KEY_A)
    pi.heartbeat(0)
    set_ref(app, city_a)
    pi.result(REF, at=10)
    wait_push(client, app)
    expo.sent.clear()

    pi.result(13400.0, at=7200, queued_s=6000)  # replayed line edge: baseline {line}
    pi.fault(at=7201)  # live: drain over, ONLINE -> FAULT
    wait_push(client, app)
    assert [(m["body"], m["data"]["type"]) for m in expo.sent] == [("תקלת ציוד", "fault")]


def test_live_recovery_ending_a_device_only_drain_is_pushed(app: FastAPI, client: TestClient, db: Session) -> None:
    """Replay touched only the device; the live BREAK -> OK is not in the summary, so it pushes."""
    clock, expo, city_a, _ = _setup(app, client, db)
    seed_user(db, "a1@x.org", city_a, push_token="tok-a1")
    pi = Pi(client, clock, KEY_A)
    pi.heartbeat(0)
    set_ref(app, city_a)
    pi.result(13400.0, at=10)
    pi.result(13410.0, at=100)  # live BREAK
    wait_push(client, app)
    expo.sent.clear()

    pi.fault(at=7200, queued_s=6000)  # replayed ONLINE -> FAULT: baseline {device}
    pi.result(REF, at=7201)  # live: drain over, FAULT -> ONLINE and BREAK -> OK
    wait_push(client, app)
    assert [(m["body"], m["data"]["type"]) for m in expo.sent] == [("העירוב תקין", "recovered")]


# --- Expo send retries -----------------------------------------------------------------


def test_send_retries_5xx_then_delivers_once(app: FastAPI, client: TestClient, db: Session) -> None:
    clock, expo, city_a, _ = _setup(app, client, db)
    seed_user(db, "a1@x.org", city_a, push_token="tok-a1")
    expo.send_failures[:] = [503, 503]

    Pi(client, clock, KEY_A).heartbeat(0)  # ONLINE push
    wait_push(client, app)

    assert expo.send_attempts == 3
    assert [m["to"] for m in expo.sent] == ["tok-a1"]
    assert len(expo.sleeps) == 2
    assert 1.0 <= expo.sleeps[0] < 2.0 and 5.0 <= expo.sleeps[1] < 6.0
    assert expo.receipt_requests == [["ticket-tok-a1"]]


def test_send_does_not_retry_4xx(app: FastAPI, client: TestClient, db: Session) -> None:
    clock, expo, city_a, _ = _setup(app, client, db)
    seed_user(db, "a1@x.org", city_a, push_token="tok-a1")
    expo.send_failures[:] = [400]

    Pi(client, clock, KEY_A).heartbeat(0)
    wait_push(client, app)

    assert expo.send_attempts == 1
    assert expo.sent == [] and expo.sleeps == []


def test_send_gives_up_after_three_timeouts(
    app: FastAPI, client: TestClient, db: Session, caplog: pytest.LogCaptureFixture
) -> None:
    clock, expo, city_a, _ = _setup(app, client, db)
    seed_user(db, "a1@x.org", city_a, push_token="tok-a1")
    expo.send_failures[:] = [httpx.ReadTimeout("timed out") for _ in range(5)]

    with caplog.at_level(logging.WARNING, logger="app.push"):
        Pi(client, clock, KEY_A).heartbeat(0)
        wait_push(client, app)

    assert expo.send_attempts == 3
    assert expo.sent == [] and len(expo.sleeps) == 2
    errors = [r for r in caplog.records if r.name == "app.push" and r.levelno == logging.ERROR]
    assert len(errors) == 1 and "after 3 attempt(s)" in errors[0].getMessage()


def test_device_not_registered_receipt_deletes_token(app: FastAPI, client: TestClient, db: Session) -> None:
    clock, expo, city_a, _ = _setup(app, client, db)
    seed_user(db, "a1@x.org", city_a, push_token="tok-good")
    seed_user(db, "a2@x.org", city_a, push_token="tok-gone")
    seed_user(db, "a3@x.org", city_a, push_token="tok-gone-now")
    expo.receipts["ticket-tok-gone"] = {"status": "error", "details": {"error": "DeviceNotRegistered"}}
    expo.tickets["tok-gone-now"] = {"status": "error", "details": {"error": "DeviceNotRegistered"}}

    Pi(client, clock, KEY_A).heartbeat(0)  # ONLINE push
    wait_push(client, app)

    assert sorted(m["to"] for m in expo.sent) == ["tok-gone", "tok-gone-now", "tok-good"]
    assert expo.receipt_requests and sorted(expo.receipt_requests[0]) == ["ticket-tok-gone", "ticket-tok-good"]
    db.expire_all()
    assert list(db.scalars(select(PushToken.token))) == ["tok-good"]


# --- push token registration ----------------------------------------------------------


def test_push_token_register_moves_token_and_delete(app: FastAPI, client: TestClient, db: Session) -> None:
    city = seed_city(db, "Be'er Sheva")
    u1 = seed_user(db, "a1@x.org", city)
    u2 = seed_user(db, "a2@x.org", city)

    r = client.post("/api/push-tokens", json={"token": "ExponentPushToken[abc]", "platform": "ios"}, headers=auth(app, u1))
    assert r.status_code == 204, r.text
    # The same phone logs in as another user: the token moves.
    r = client.post("/api/push-tokens", json={"token": "ExponentPushToken[abc]", "platform": "ios"}, headers=auth(app, u2))
    assert r.status_code == 204
    db.expire_all()
    rows = list(db.scalars(select(PushToken)))
    assert [(t.user_id, t.token, t.platform) for t in rows] == [(u2.id, "ExponentPushToken[abc]", "ios")]

    # u1 cannot delete u2's token; u2 can.
    assert client.request("DELETE", "/api/push-tokens", json={"token": "ExponentPushToken[abc]"}, headers=auth(app, u1)).status_code == 204
    db.expire_all()
    assert db.scalar(select(PushToken.token)) == "ExponentPushToken[abc]"
    assert client.request("DELETE", "/api/push-tokens", json={"token": "ExponentPushToken[abc]"}, headers=auth(app, u2)).status_code == 204
    db.expire_all()
    assert db.scalar(select(PushToken.token)) is None

    assert client.post("/api/push-tokens", json={"token": "t", "platform": "ios"}).status_code == 401


def test_disable_reject_and_city_change_delete_push_tokens(
    app: FastAPI, client: TestClient, db: Session, admin_headers: dict[str, str]
) -> None:
    city_a = seed_city(db, "Be'er Sheva")
    city_b = seed_city(db, "Ashdod")
    u1 = seed_user(db, "a1@x.org", city_a, push_token="tok-1")
    u2 = seed_user(db, "a2@x.org", city_a, push_token="tok-2")
    u3 = seed_user(db, "a3@x.org", city_a, push_token="tok-3")
    seed_user(db, "a4@x.org", city_a, push_token="tok-4")

    assert client.post(f"/api/admin/users/{u1.id}/disable", headers=admin_headers).status_code == 200
    assert client.post(f"/api/admin/users/{u2.id}/reject", headers=admin_headers).status_code == 200
    assert client.post("/api/auth/city-change", json={"city_id": city_b}, headers=auth(app, u3)).status_code == 200
    db.expire_all()
    assert list(db.scalars(select(PushToken.token))) == ["tok-4"]

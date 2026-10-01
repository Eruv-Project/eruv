"""Logs API (R23): transitions and result summaries, newest first, filtered, paginated."""

from __future__ import annotations

from datetime import timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Result, ResultKind, StatusDimension, StatusEvent
from support import T0, auth, seed_city, seed_user


def _event(db: Session, city_id: int, minutes: int, to_state: str = "OK", replayed: bool = False) -> None:
    db.add(
        StatusEvent(
            city_id=city_id,
            dimension=StatusDimension.LINE,
            from_state="SUSPECT_BREAK",
            to_state=to_state,
            occurred_at=T0 + timedelta(minutes=minutes),
            replayed=replayed,
            detail=f"m{minutes}",
        )
    )


def _result(db: Session, city_id: int, device_id: int, minutes: int, kind: ResultKind, backlog: bool = False) -> None:
    db.add(
        Result(
            device_id=device_id,
            city_id=city_id,
            kind=kind,
            seq=minutes,
            payload_sha256="0" * 64,
            received_at=T0 + timedelta(minutes=minutes),
            measured_at=T0 + timedelta(minutes=minutes),
            backlog=backlog,
            agent_version="1.0.0",
            end_event_distance_m=47210.0 if kind == ResultKind.RESULT else None,
            fiber_length_m=47210.0 if kind == ResultKind.RESULT else None,
            link_loss_db=10.2 if kind == ResultKind.RESULT else None,
            fault_kind="otdr_timeout" if kind == ResultKind.FAULT else None,
            fault_detail="no answer" if kind == ResultKind.FAULT else None,
        )
    )


def test_date_filter_newest_first_with_cursor(app: FastAPI, client: TestClient, db: Session) -> None:
    city = seed_city(db, "Be'er Sheva")
    other = seed_city(db, "Ashdod")
    user = seed_user(db, "a@x.org", city)
    for m in (0, 10, 20, 30, 40, 50):
        _event(db, city, m, replayed=(m == 30))
    _event(db, other, 25)
    db.commit()

    params = {
        "type": "transitions",
        "from": (T0 + timedelta(minutes=10)).isoformat(),
        "to": (T0 + timedelta(minutes=40)).isoformat(),
        "limit": 2,
    }
    url = f"/api/cities/{city}/logs"
    page1 = client.get(url, params=params, headers=auth(app, user))
    assert page1.status_code == 200, page1.text
    body1 = page1.json()
    assert [i["detail"] for i in body1["items"]] == ["m40", "m30"]
    assert body1["items"][1]["replayed"] is True
    assert body1["items"][0]["kind"] == "transition"
    assert body1["next_cursor"]

    body2 = client.get(url, params=params | {"cursor": body1["next_cursor"]}, headers=auth(app, user)).json()
    assert [i["detail"] for i in body2["items"]] == ["m20", "m10"]
    assert body2["next_cursor"] is None  # nothing older inside the range

    assert client.get(f"/api/cities/{other}/logs", headers=auth(app, user)).status_code == 403
    assert client.get(url, params={"cursor": "not-a-cursor"}, headers=auth(app, user)).status_code == 422


def test_results_and_faults_filters(app: FastAPI, client: TestClient, db: Session) -> None:
    from app.models import Device

    city = seed_city(db, "Be'er Sheva")
    device = Device(city_id=city, api_key_hash="f" * 64)
    db.add(device)
    db.flush()
    user = seed_user(db, "a@x.org", city)
    _result(db, city, device.id, 1, ResultKind.RESULT)
    _result(db, city, device.id, 2, ResultKind.FAULT)
    _result(db, city, device.id, 3, ResultKind.RESULT, backlog=True)
    _event(db, city, 4)
    db.commit()
    url = f"/api/cities/{city}/logs"

    results = client.get(url, params={"type": "results"}, headers=auth(app, user)).json()
    assert [(i["kind"], i["replayed"]) for i in results["items"]] == [("result", True), ("result", False)]
    assert results["items"][0]["end_event_distance_m"] == 47210.0
    assert results["next_cursor"] is None

    faults = client.get(url, params={"type": "faults"}, headers=auth(app, user)).json()
    [fault] = faults["items"]
    assert (fault["kind"], fault["fault_kind"], fault["fault_detail"]) == ("fault", "otdr_timeout", "no answer")

    default = client.get(url, headers=auth(app, user)).json()
    assert [i["kind"] for i in default["items"]] == ["transition"]
    assert client.get(url, params={"type": "bogus"}, headers=auth(app, user)).status_code == 422

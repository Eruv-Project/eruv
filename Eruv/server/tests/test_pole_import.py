"""Pole import: CSV / KML parsing, R26 validation, preview and atomic replace (U9)."""

from __future__ import annotations

import math
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Pole
from app.services.pole_import import MAX_MISSING_LISTED, MAX_POLE_NUMBER, PoleImportError, parse_poles
from conftest import create_city


def _csv(numbers, header: bool = True) -> bytes:
    lines = ["pole_number,lat,lon"] if header else []
    for n in numbers:
        lines.append(f"{n},{31.25 + n * 0.0001:.6f},34.790000")
    return ("\n".join(lines) + "\n").encode()


def _kml(n: int) -> bytes:
    marks = "".join(
        f"<Placemark><name>{i}</name><Point><coordinates>34.79,{31.25 + i * 0.0001:.6f},0</coordinates></Point></Placemark>"
        for i in range(n, 0, -1)  # out of order on purpose
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<kml xmlns="http://www.opengis.net/kml/2.2"><Document>{marks}</Document></kml>'
    ).encode()


def _preview(client: TestClient, headers, city_id: int, name: str, content: bytes):
    return client.post(
        f"/api/admin/cities/{city_id}/poles/preview", files={"file": (name, content)}, headers=headers
    )


# --- service ------------------------------------------------------------------------


def test_csv_without_header_parses() -> None:
    poles = parse_poles(_csv([1, 2, 3], header=False), "poles.csv")
    assert [p.number for p in poles] == [1, 2, 3]


def test_csv_row_error_names_the_line() -> None:
    with pytest.raises(PoleImportError) as exc:
        parse_poles(b"pole_number,lat,lon\n1,31.2,34.7\n2,abc,34.7\n3,95,34.7\n", "p.csv")
    rows = {e["row"] for e in exc.value.errors if e["row"] is not None}
    assert rows == {3, 4}


def test_duplicate_numbers_are_rejected() -> None:
    with pytest.raises(PoleImportError) as exc:
        parse_poles(_csv([1, 2, 2, 3]), "p.csv")
    assert any("duplicate" in e["message"] for e in exc.value.errors)


def test_single_pole_is_rejected() -> None:
    with pytest.raises(PoleImportError):
        parse_poles(_csv([1]), "p.csv")


def test_kml_detected_by_content() -> None:
    assert len(parse_poles(_kml(3), "upload.bin")) == 3


# --- endpoints ----------------------------------------------------------------------


def test_csv_with_300_poles_previews_in_order_without_saving(
    client: TestClient, admin_headers, db: Session
) -> None:
    city = create_city(client, admin_headers, "Be'er Sheva")
    numbers = list(range(1, 301))
    content = _csv(reversed(numbers))
    r = _preview(client, admin_headers, city, "poles.csv", content)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 300
    assert [p["number"] for p in body["poles"]] == numbers
    assert body["perimeter_m"] > 0
    assert db.scalars(select(Pole).where(Pole.city_id == city)).all() == []


def test_csv_with_gap_is_rejected_naming_missing_number(client: TestClient, admin_headers) -> None:
    city = create_city(client, admin_headers, "Be'er Sheva")
    r = _preview(client, admin_headers, city, "poles.csv", _csv([1, 2, 4]))
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "invalid_poles"
    assert [e["missing_number"] for e in detail["errors"] if e["missing_number"] is not None] == [3]


def test_kml_placemark_names_become_pole_numbers(client: TestClient, admin_headers) -> None:
    city = create_city(client, admin_headers, "Be'er Sheva")
    r = _preview(client, admin_headers, city, "poles.kml", _kml(5))
    assert r.status_code == 200, r.text
    poles = r.json()["poles"]
    assert [p["number"] for p in poles] == [1, 2, 3, 4, 5]
    assert poles[0]["lon"] == 34.79
    assert math.isclose(poles[0]["lat"], 31.2501)


def test_put_poles_replaces_atomically(client: TestClient, admin_headers, db: Session) -> None:
    city = create_city(client, admin_headers, "Be'er Sheva")
    first = [{"number": n, "lat": 31.25 + n * 0.001, "lon": 34.79} for n in range(1, 6)]
    r = client.put(f"/api/admin/cities/{city}/poles", json={"poles": first}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 5

    second = [{"number": n, "lat": 31.3 + n * 0.001, "lon": 34.8} for n in range(1, 4)]
    r = client.put(f"/api/admin/cities/{city}/poles", json={"poles": second}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 3
    rows = db.scalars(select(Pole).where(Pole.city_id == city).order_by(Pole.number)).all()
    assert [(p.number, p.lat) for p in rows] == [(p["number"], p["lat"]) for p in second]

    bad = [{"number": 1, "lat": 31.0, "lon": 34.0}, {"number": 3, "lat": 31.0, "lon": 34.0}]
    r = client.put(f"/api/admin/cities/{city}/poles", json={"poles": bad}, headers=admin_headers)
    assert r.status_code == 422
    assert r.json()["detail"]["errors"][0]["missing_number"] == 2
    db.expire_all()
    assert len(db.scalars(select(Pole).where(Pole.city_id == city)).all()) == 3


@pytest.mark.parametrize("number", ["1e12", "20000"])
def test_huge_pole_number_is_a_row_error_and_fast(client: TestClient, admin_headers, number: str) -> None:
    city = create_city(client, admin_headers, "Be'er Sheva")
    content = f"pole_number,lat,lon\n1,31.25,34.79\n2,31.26,34.79\n{number},31.27,34.79\n".encode()
    started = time.monotonic()
    r = _preview(client, admin_headers, city, "poles.csv", content)
    assert time.monotonic() - started < 2.0
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "invalid_poles"
    assert any(e["row"] == 4 and "maximum" in e["message"] for e in detail["errors"])


def test_large_gap_is_counted_without_listing_every_number() -> None:
    with pytest.raises(PoleImportError) as exc:
        parse_poles(_csv([1, 2, MAX_POLE_NUMBER]), "p.csv")
    listed = [e["missing_number"] for e in exc.value.errors if e["missing_number"] is not None]
    assert listed == list(range(3, 3 + MAX_MISSING_LISTED))
    missing_total = MAX_POLE_NUMBER - 3  # every number in 3..MAX_POLE_NUMBER-1
    unlisted = missing_total - MAX_MISSING_LISTED
    assert any(e["message"] == f"{unlisted} more pole numbers are missing" for e in exc.value.errors)


def test_put_pole_number_above_maximum_is_422(client: TestClient, admin_headers, db: Session) -> None:
    city = create_city(client, admin_headers, "Be'er Sheva")
    poles = [{"number": 1, "lat": 31.0, "lon": 34.0}, {"number": 20000, "lat": 31.1, "lon": 34.0}]
    r = client.put(f"/api/admin/cities/{city}/poles", json={"poles": poles}, headers=admin_headers)
    assert r.status_code == 422
    assert db.scalars(select(Pole).where(Pole.city_id == city)).all() == []

"""Break mapping onto the closed pole ring (KTD7, R12, AE3-AE5).

Poles are laid out along one meridian, where great-circle distance is exactly
R * delta_latitude. Expected positions are therefore computed here from plain
arithmetic on the chosen distances, independently of the haversine code.
"""

from __future__ import annotations

import math

import pytest

from app.mapping import EARTH_RADIUS_M, PolePoint, map_break

BASE_LAT = 31.25
LON = 34.79


def lat_at(distance_m: float) -> float:
    """Latitude of a point `distance_m` north of BASE_LAT on the meridian."""
    return BASE_LAT + math.degrees(distance_m / EARTH_RADIUS_M)


def meridian_ring(cumulative_m: list[float]) -> list[PolePoint]:
    return [PolePoint(number=i + 1, lat=lat_at(d), lon=LON) for i, d in enumerate(cumulative_m)]


# Four poles at 0, 3000, 8000, 12000 m; the closing segment 4 -> 1 is 12000 m back.
# Segment lengths: 3000, 5000, 4000, 12000; perimeter 24000.
FOUR = [0.0, 3000.0, 8000.0, 12000.0]


def test_four_pole_ring_maps_into_the_right_segment_and_fraction() -> None:
    poles = meridian_ring(FOUR)
    m = map_break(otdr_break_m=6000.0, launch_offset_m=1000.0, poles=poles)  # geo 5000
    assert m["kind"] == "between"
    assert (m["pole_a"], m["pole_b"]) == (2, 3)
    assert m["geo_distance_m"] == pytest.approx(5000.0)
    assert m["offset_from_a_m"] == pytest.approx(2000.0, abs=0.01)
    assert m["lat"] == pytest.approx(lat_at(5000.0), abs=1e-7)
    assert m["lon"] == pytest.approx(LON)


def test_four_pole_ring_13400_lands_on_closing_segment() -> None:
    poles = meridian_ring(FOUR)
    m = map_break(otdr_break_m=13400.0, launch_offset_m=1000.0, poles=poles)  # geo 12400
    assert m["kind"] == "between"
    assert (m["pole_a"], m["pole_b"]) == (4, 1)
    assert m["offset_from_a_m"] == pytest.approx(400.0, abs=0.01)
    # 400 m back from pole 4 towards pole 1 along the meridian.
    assert m["lat"] == pytest.approx(lat_at(12000.0 - 400.0), abs=1e-7)


def test_ae3_between_pole_57_and_58_twenty_metres_past_57() -> None:
    # Poles 1..57 evenly spaced up to 12,380 m; pole 58 at 12,455 m.
    cumulative = [k * 12380.0 / 56 for k in range(57)] + [12455.0]
    poles = meridian_ring(cumulative)
    m = map_break(otdr_break_m=13400.0, launch_offset_m=1000.0, poles=poles)
    assert m["kind"] == "between"
    assert (m["pole_a"], m["pole_b"]) == (57, 58)
    assert m["offset_from_a_m"] == pytest.approx(20.0, abs=0.01)
    lat57, lat58 = lat_at(12380.0), lat_at(12455.0)
    assert m["lat"] == pytest.approx(lat57 + (20.0 / 75.0) * (lat58 - lat57), abs=1e-8)


def test_ae4_distance_below_launch_offset_is_at_the_cabinet() -> None:
    poles = meridian_ring(FOUR)
    m = map_break(otdr_break_m=640.0, launch_offset_m=1000.0, poles=poles)
    assert m["kind"] == "at_cabinet"
    assert m["pole_a"] == 1
    assert (m["lat"], m["lon"]) == (poles[0].lat, poles[0].lon)


def test_ae5_beyond_perimeter_sits_on_last_segment_at_pole_1() -> None:
    poles = meridian_ring(FOUR)
    m = map_break(otdr_break_m=1000.0 + 24000.0 + 350.0, launch_offset_m=1000.0, poles=poles)
    assert m["kind"] == "beyond_ring"
    assert (m["pole_a"], m["pole_b"]) == (4, 1)
    assert (m["lat"], m["lon"]) == pytest.approx((poles[0].lat, poles[0].lon))
    assert m["geo_distance_m"] == pytest.approx(24350.0)


def test_poles_are_ordered_by_number_not_input_order() -> None:
    poles = list(reversed(meridian_ring(FOUR)))
    m = map_break(otdr_break_m=6000.0, launch_offset_m=1000.0, poles=poles)
    assert (m["pole_a"], m["pole_b"]) == (2, 3)


def test_fewer_than_two_poles_is_unknown() -> None:
    m = map_break(otdr_break_m=6000.0, launch_offset_m=1000.0, poles=meridian_ring([0.0]))
    assert m["kind"] == "unknown"
    assert m["geo_distance_m"] == pytest.approx(5000.0)
    assert map_break(otdr_break_m=6000.0, launch_offset_m=1000.0, poles=[])["kind"] == "unknown"

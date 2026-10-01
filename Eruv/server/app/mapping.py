"""Break mapping onto the closed pole ring (KTD7, R12). Pure functions.

Pure geographic model (session-settled): the OTDR distance minus the launch-box
offset is walked along great-circle segments pole 1 -> 2 -> ... -> N -> 1, with no
fiber-slack correction. Inside the bounding segment the coordinate is a linear
interpolation of latitude and longitude (segments are tens of metres long).

Result kinds (JSON-able dict, stored on the BREAK status event):
- ``between``: on segment pole_a -> pole_b, ``offset_from_a_m`` past pole_a.
- ``at_cabinet``: distance shorter than the launch box (AE4); pole 1, pole_b None.
- ``beyond_ring``: longer than the ring perimeter (AE5); placed at the end of the
  last segment (pole N -> pole 1, t = 1).
- ``unknown``: the city has fewer than two poles, so there is no ring to walk
  (a single pole still reports ``at_cabinet`` for distances inside the launch box).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

# IUGG mean Earth radius.
EARTH_RADIUS_M = 6371008.8


@dataclass(frozen=True)
class PolePoint:
    number: int
    lat: float
    lon: float


def haversine_m(a: PolePoint, b: PolePoint) -> float:
    phi1, phi2 = math.radians(a.lat), math.radians(b.lat)
    dphi = phi2 - phi1
    dlmb = math.radians(b.lon - a.lon)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def _mapping(
    kind: str,
    geo: float,
    a: PolePoint | None = None,
    b: PolePoint | None = None,
    lat: float | None = None,
    lon: float | None = None,
    offset: float | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "pole_a": a.number if a else None,
        "pole_b": b.number if b else None,
        "lat": lat,
        "lon": lon,
        "geo_distance_m": geo,
        "offset_from_a_m": offset,
    }


def map_break(otdr_break_m: float, launch_offset_m: float, poles: Sequence[PolePoint]) -> dict[str, Any]:
    geo = otdr_break_m - launch_offset_m
    ring = sorted(poles, key=lambda p: p.number)
    if geo < 0 and ring:
        first = ring[0]
        return _mapping("at_cabinet", geo, first, None, first.lat, first.lon, 0.0)
    if len(ring) < 2:
        return _mapping("unknown", geo)

    cum = 0.0
    segments = list(zip(ring, ring[1:] + ring[:1]))
    for a, b in segments:
        seg = haversine_m(a, b)
        if cum + seg >= geo:
            t = (geo - cum) / seg if seg > 0 else 0.0
            lat = a.lat + t * (b.lat - a.lat)
            lon = a.lon + t * (b.lon - a.lon)
            return _mapping("between", geo, a, b, lat, lon, geo - cum)
        cum += seg
    a, b = segments[-1]
    return _mapping("beyond_ring", geo, a, b, b.lat, b.lon, haversine_m(a, b))


def ring_perimeter_m(poles: Sequence[PolePoint]) -> float | None:
    """Great-circle length of the closed ring 1 -> 2 -> ... -> N -> 1; None below two poles."""
    ring = sorted(poles, key=lambda p: p.number)
    if len(ring) < 2:
        return None
    return sum(haversine_m(a, b) for a, b in zip(ring, ring[1:] + ring[:1]))

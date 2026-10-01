"""Parse and validate a city's pole file (R26). Pure functions, no database.

CSV: ``pole_number,lat,lon`` rows, optional header row. KML: ``Placemark`` elements
whose ``name`` is the pole number and whose ``Point/coordinates`` is ``lon,lat[,alt]``.

Errors are collected, not raised one at a time, so the admin sees every problem in
one preview. Each error is ``{"row", "message", "missing_number"}``: ``row`` is the
1-based CSV line (None for KML and whole-file problems), ``missing_number`` names a
gap in the numbering.
"""

from __future__ import annotations

import csv
import io
import math
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from itertools import islice
from typing import Any

from app.mapping import PolePoint

# A typo such as pole 3000 in a 300-pole file would otherwise list ~2700 gaps.
MAX_MISSING_LISTED = 20
# Far above any real eruv ring; bounds the gap scan and the memory a bad file can cost.
MAX_POLE_NUMBER = 10000


class PoleImportError(Exception):
    def __init__(self, errors: list[dict[str, Any]]) -> None:
        super().__init__(f"{len(errors)} pole file error(s)")
        self.errors = errors


def _error(message: str, row: int | None = None, missing_number: int | None = None) -> dict[str, Any]:
    return {"row": row, "message": message, "missing_number": missing_number}


def _parse_int(text: str) -> int | None:
    text = text.strip()
    try:
        return int(text)
    except ValueError:
        try:
            value = float(text)
        except ValueError:
            return None
        return int(value) if value.is_integer() else None


def _parse_float(text: str) -> float | None:
    try:
        value = float(text.strip())
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _check_point(number: int, lat: float, lon: float, row: int | None, label: str) -> list[dict[str, Any]]:
    errors = []
    if number < 1:
        errors.append(_error(f"{label}: pole number {number} must be 1 or greater", row))
    elif number > MAX_POLE_NUMBER:
        errors.append(_error(f"{label}: pole number {number} is above the maximum {MAX_POLE_NUMBER}", row))
    if not -90.0 <= lat <= 90.0:
        errors.append(_error(f"{label}: latitude {lat} is outside -90..90", row))
    if not -180.0 <= lon <= 180.0:
        errors.append(_error(f"{label}: longitude {lon} is outside -180..180", row))
    return errors


def _parse_csv(text: str) -> tuple[list[tuple[PolePoint, int | None]], list[dict[str, Any]]]:
    points: list[tuple[PolePoint, int | None]] = []
    errors: list[dict[str, Any]] = []
    for line_no, fields in enumerate(csv.reader(io.StringIO(text)), start=1):
        if not fields or all(not f.strip() for f in fields):
            continue
        label = f"row {line_no}"
        if line_no == 1 and _parse_int(fields[0]) is None:
            continue  # header row
        if len(fields) < 3:
            errors.append(_error(f"{label}: expected pole_number,lat,lon", line_no))
            continue
        number, lat, lon = _parse_int(fields[0]), _parse_float(fields[1]), _parse_float(fields[2])
        if number is None:
            errors.append(_error(f"{label}: pole number {fields[0].strip()!r} is not a whole number", line_no))
        if lat is None:
            errors.append(_error(f"{label}: latitude {fields[1].strip()!r} is not a number", line_no))
        if lon is None:
            errors.append(_error(f"{label}: longitude {fields[2].strip()!r} is not a number", line_no))
        if number is None or lat is None or lon is None:
            continue
        point_errors = _check_point(number, lat, lon, line_no, label)
        errors.extend(point_errors)
        if not point_errors:
            points.append((PolePoint(number, lat, lon), line_no))
    return points, errors


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(elem: ET.Element, name: str) -> ET.Element | None:
    for sub in elem.iter():
        if sub is not elem and _local(sub.tag) == name:
            return sub
    return None


def _parse_kml(text: str) -> tuple[list[tuple[PolePoint, int | None]], list[dict[str, Any]]]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return [], [_error(f"KML is not valid XML: {exc}")]
    points: list[tuple[PolePoint, int | None]] = []
    errors: list[dict[str, Any]] = []
    placemarks = [e for e in root.iter() if _local(e.tag) == "Placemark"]
    for index, mark in enumerate(placemarks, start=1):
        name_el = _child(mark, "name")
        name = (name_el.text or "").strip() if name_el is not None else ""
        label = f"placemark {index} ({name!r})" if name else f"placemark {index}"
        number = _parse_int(name) if name else None
        if number is None:
            errors.append(_error(f"{label}: name must be the pole number"))
            continue
        point = _child(mark, "Point")
        coords_el = _child(point, "coordinates") if point is not None else None
        parts = (coords_el.text or "").strip().split(",") if coords_el is not None else []
        lon = _parse_float(parts[0]) if len(parts) >= 2 else None
        lat = _parse_float(parts[1]) if len(parts) >= 2 else None
        if lat is None or lon is None:
            errors.append(_error(f"{label}: needs a Point with coordinates lon,lat"))
            continue
        point_errors = _check_point(number, lat, lon, None, label)
        errors.extend(point_errors)
        if not point_errors:
            points.append((PolePoint(number, lat, lon), None))
    return points, errors


def _check_ring(points: list[tuple[PolePoint, int | None]]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    seen: dict[int, int | None] = {}
    for p, row in points:
        if p.number in seen:
            where = f"row {row}" if row is not None else f"pole {p.number}"
            errors.append(_error(f"{where}: duplicate pole number {p.number}", row))
        else:
            seen[p.number] = row
    if seen:
        # numbers are 1..MAX_POLE_NUMBER here (invalid points never reach the ring
        # check), so the count needs no list of gaps
        highest = max(seen)
        missing_total = highest - len(seen)
        gaps = (n for n in range(1, highest + 1) if n not in seen)
        listed = 0
        for n in islice(gaps, MAX_MISSING_LISTED):
            errors.append(_error(f"pole number {n} is missing; numbers must run 1..N without gaps", None, n))
            listed += 1
        if missing_total > listed:
            errors.append(_error(f"{missing_total - listed} more pole numbers are missing"))
    if len(seen) < 2:
        errors.append(_error("the ring needs at least 2 poles"))
    return errors


def validate_poles(entries: Iterable[tuple[PolePoint, int | None]], errors: list[dict[str, Any]] | None = None) -> list[PolePoint]:
    """The poles ordered by number, or PoleImportError with every problem found."""
    points = list(entries)
    all_errors = list(errors or []) + _check_ring(points)
    if all_errors:
        raise PoleImportError(all_errors)
    return sorted((p for p, _ in points), key=lambda p: p.number)


def check_points(poles: Iterable[PolePoint]) -> list[PolePoint]:
    """Validate already-structured poles (the save request); rows are list positions."""
    entries: list[tuple[PolePoint, int | None]] = []
    errors: list[dict[str, Any]] = []
    for index, p in enumerate(poles, start=1):
        point_errors = _check_point(p.number, p.lat, p.lon, index, f"item {index}")
        errors.extend(point_errors)
        if not point_errors:
            entries.append((p, index))
    return validate_poles(entries, errors)


def _looks_like_kml(filename: str | None, text: str) -> bool:
    name = (filename or "").lower()
    if name.endswith(".kml"):
        return True
    if name.endswith(".csv"):
        return False
    return text.lstrip().startswith("<")


def parse_poles(content: bytes, filename: str | None = None) -> list[PolePoint]:
    """Parse a CSV or KML pole file into poles ordered by number (R26)."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise PoleImportError([_error("file is not UTF-8 text")]) from None
    points, errors = _parse_kml(text) if _looks_like_kml(filename, text) else _parse_csv(text)
    return validate_poles(points, errors)

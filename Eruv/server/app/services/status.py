"""Apply the pure status engine to the database and publish transitions.

Every transition writes a ``status_events`` row and, after the commit, publishes a
``StatusChanged`` on the event bus. All state changes run under ``STATE_LOCK``:
the server is one process (KTD11), and the lock keeps ingest requests, the
watchdog thread and admin actions from interleaving read-modify-write cycles on
the same city (which could otherwise log a stale DISCONNECTED next to a fresh
heartbeat, or confirm one break twice).
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.events import EventBus, ResultReceived, StatusChanged
from app.mapping import PolePoint, map_break
from app.models import City, Device, DeviceHealth, LineState, Pole, Result, StatusDimension, StatusEvent
from app.status_engine import (
    health_on_fault,
    health_on_heartbeat,
    health_on_valid_result,
    line_on_reconnect,
    line_on_reference_set,
    line_on_result,
)

log = logging.getLogger(__name__)

STATE_LOCK = threading.RLock()


class Pending:
    """Status events written in this unit of work, published after commit."""

    def __init__(self) -> None:
        self.rows: list[StatusEvent] = []
        self.results: list[Result] = []

    def record(
        self,
        db: Session,
        city: City,
        dimension: StatusDimension,
        from_state: str,
        to_state: str,
        now: datetime,
        *,
        replayed: bool = False,
        detail: str | None = None,
        mapping: dict | None = None,
        result_id: int | None = None,
    ) -> None:
        row = StatusEvent(
            city_id=city.id,
            dimension=dimension,
            from_state=str(from_state),
            to_state=str(to_state),
            occurred_at=now,
            replayed=replayed,
            detail=detail,
            mapping=mapping,
            result_id=result_id,
        )
        db.add(row)
        self.rows.append(row)

    def commit_and_publish(self, db: Session, bus: EventBus) -> None:
        db.commit()
        for r in self.results:
            bus.publish(
                ResultReceived(
                    city_id=r.city_id,
                    result_id=r.id,
                    kind=r.kind.value,
                    received_at=r.received_at,
                    backlog=r.backlog,
                    end_event_distance_m=r.end_event_distance_m,
                )
            )
        for row in self.rows:
            bus.publish(
                StatusChanged(
                    event_id=row.id,
                    city_id=row.city_id,
                    dimension=row.dimension.value,
                    from_state=row.from_state,
                    to_state=row.to_state,
                    occurred_at=row.occurred_at,
                    replayed=row.replayed,
                    mapping=row.mapping,
                    detail=row.detail,
                    result_id=row.result_id,
                )
            )


def set_health(
    db: Session, pending: Pending, city: City, new: DeviceHealth, now: datetime, **kw
) -> bool:
    if new == city.device_health:
        return False
    pending.record(db, city, StatusDimension.DEVICE, city.device_health, new, now, **kw)
    city.device_health = new
    return True


def latest_event(
    db: Session, city_id: int, dimension: StatusDimension, to_state: str | None = None
) -> StatusEvent | None:
    query = select(StatusEvent).where(StatusEvent.city_id == city_id, StatusEvent.dimension == dimension)
    if to_state is not None:
        query = query.where(StatusEvent.to_state == to_state)
    return db.scalar(query.order_by(StatusEvent.occurred_at.desc(), StatusEvent.id.desc()).limit(1))


def pole_points(db: Session, city_id: int) -> list[PolePoint]:
    rows = db.scalars(select(Pole).where(Pole.city_id == city_id)).all()
    return [PolePoint(p.number, p.lat, p.lon) for p in rows]


def _reconnect(db: Session, pending: Pending, device: Device, city: City, now: datetime) -> None:
    """Any accepted device message proves the uplink is back (KTD6).

    DISCONNECTED -> ONLINE and drop the pre-outage break candidate, so every path
    into BREAK after a reconnect still needs two consecutive break results, even
    when a spooled result or fault arrives before the first heartbeat. The
    message also counts as a sign of life for the heartbeat timer, so the
    watchdog does not flip the device straight back to DISCONNECTED.
    """
    device.last_heartbeat_at = now
    if set_health(db, pending, city, health_on_heartbeat(city.device_health), now):
        city.suspect_distance_m = line_on_reconnect()


def apply_heartbeat(db: Session, bus: EventBus, device: Device, now: datetime) -> None:
    pending = Pending()
    city = db.get(City, device.city_id)
    _reconnect(db, pending, device, city, now)
    pending.commit_and_publish(db, bus)


def apply_result(db: Session, bus: EventBus, device: Device, result: Result, now: datetime) -> None:
    """`result` is a new, not yet flushed ``Result`` row of kind result."""
    pending = Pending()
    city = db.get(City, device.city_id)
    db.add(result)
    db.flush()
    pending.results.append(result)
    if city.device_health == DeviceHealth.DISCONNECTED:
        _reconnect(db, pending, device, city, now)

    step = line_on_result(
        city.line_state,
        city.suspect_distance_m,
        result.end_event_distance_m,
        city.reference_fiber_length_m,
        city.break_tolerance_m,
    )
    if not step.usable:
        log.warning("city %s: result seq %s has no end event; line state unchanged", city.id, result.seq)
        pending.commit_and_publish(db, bus)
        return

    city.last_result_at = now
    set_health(
        db, pending, city, health_on_valid_result(city.device_health), now,
        replayed=result.backlog, detail="valid test result received", result_id=result.id,
    )
    if step.rebaseline_warning:
        log.warning("city %s: %s", city.id, step.detail)
    if step.transition:
        mapping = None
        if step.state == LineState.BREAK:
            mapping = map_break(result.end_event_distance_m, city.launch_offset_m, pole_points(db, city.id))
        pending.record(
            db, city, StatusDimension.LINE, city.line_state, step.state, now,
            replayed=result.backlog, detail=step.detail, mapping=mapping, result_id=result.id,
        )
    city.line_state = step.state
    city.suspect_distance_m = step.suspect_distance_m
    pending.commit_and_publish(db, bus)


def apply_fault(db: Session, bus: EventBus, device: Device, fault: Result, now: datetime) -> None:
    """`fault` is a new, not yet flushed ``Result`` row of kind fault."""
    pending = Pending()
    city = db.get(City, device.city_id)
    db.add(fault)
    db.flush()
    pending.results.append(fault)
    if city.device_health == DeviceHealth.DISCONNECTED:
        _reconnect(db, pending, device, city, now)
    device.last_fault_at = now
    set_health(
        db, pending, city, health_on_fault(city.device_health), now,
        replayed=fault.backlog, detail=f"{fault.fault_kind}: {fault.fault_detail}", result_id=fault.id,
    )
    pending.commit_and_publish(db, bus)


def set_reference(db: Session, bus: EventBus, city_id: int, length_m: float, now: datetime) -> None:
    """Store a city's reference fiber length; AWAITING_REFERENCE -> OK (KTD6).

    The admin endpoint and its refusals (AE10) are U9; this only applies the edge.
    """
    with STATE_LOCK:
        pending = Pending()
        city = db.get(City, city_id)
        city.reference_fiber_length_m = length_m
        city.reference_set_at = now
        new = line_on_reference_set(city.line_state)
        if new != city.line_state:
            pending.record(
                db, city, StatusDimension.LINE, city.line_state, new, now,
                detail=f"reference set: {length_m:.1f} m",
            )
            city.line_state = new
        pending.commit_and_publish(db, bus)

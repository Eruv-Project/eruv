"""City reads: the public name list for registration, and scoped status and pole reads."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_city_access
from app.db import get_db
from app.models import City, DeviceHealth, LineState, Pole, StatusDimension
from app.services.status import latest_event
from app.status_engine import visible_line_state

router = APIRouter(prefix="/api/cities", tags=["cities"])


class CityName(BaseModel):
    id: int
    name: str


class ActiveBreakOut(BaseModel):
    """The transition into the current BREAK and its mapping (app.mapping keys)."""

    event_id: int
    occurred_at: datetime
    replayed: bool
    mapping: dict[str, Any] | None


class CityStatusOut(BaseModel):
    id: int
    name: str
    # Raw engine state, including the hidden SUSPECT_BREAK.
    line_state: LineState
    # What the banner shows: SUSPECT_BREAK is reported as OK (R10, R16).
    display_line_state: LineState
    device_health: DeviceHealth
    # When device_health last changed ("Monitoring disconnected since HH:MM", AE7).
    device_health_since: datetime | None
    # Server receive time of the last valid test result (the "last check", R16).
    last_result_at: datetime | None
    # Set only while line_state is BREAK (R17).
    active_break: ActiveBreakOut | None


class PoleOut(BaseModel):
    number: int
    lat: float
    lon: float


def city_status(db: Session, city: City) -> CityStatusOut:
    """The status snapshot shared by the REST endpoint and the WebSocket hello."""
    active_break = None
    if city.line_state == LineState.BREAK:
        event = latest_event(db, city.id, StatusDimension.LINE, LineState.BREAK.value)
        if event is not None:
            active_break = ActiveBreakOut(
                event_id=event.id, occurred_at=event.occurred_at, replayed=event.replayed, mapping=event.mapping
            )
    device_event = latest_event(db, city.id, StatusDimension.DEVICE)
    return CityStatusOut(
        id=city.id,
        name=city.name,
        line_state=city.line_state,
        display_line_state=visible_line_state(city.line_state),
        device_health=city.device_health,
        device_health_since=device_event.occurred_at if device_event else None,
        last_result_at=city.last_result_at,
        active_break=active_break,
    )


@router.get("", response_model=list[CityName])
def list_city_names(db: Session = Depends(get_db)) -> list[CityName]:
    """Unauthenticated: the registration form needs the city list (R19). Names only."""
    rows = db.execute(select(City.id, City.name).order_by(City.name)).all()
    return [CityName(id=row.id, name=row.name) for row in rows]


@router.get("/{city_id}/status", response_model=CityStatusOut)
def get_city_status(city: City = Depends(require_city_access), db: Session = Depends(get_db)) -> CityStatusOut:
    return city_status(db, city)


@router.get("/{city_id}/poles", response_model=list[PoleOut])
def list_poles(city: City = Depends(require_city_access), db: Session = Depends(get_db)) -> list[PoleOut]:
    """The ring in number order (R15); the map draws it as a closed polygon."""
    poles = db.scalars(select(Pole).where(Pole.city_id == city.id).order_by(Pole.number))
    return [PoleOut(number=p.number, lat=p.lat, lon=p.lon) for p in poles]

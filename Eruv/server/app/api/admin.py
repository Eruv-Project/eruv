"""Admin API (R24–R27): users, cities, device keys, pole import, reference setting.

Every route requires the admin role on the server; the app hides the admin tab too.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import UserOut
from app.api.deps import require_admin
from app.db import get_db, utcnow
from app.mapping import PolePoint, ring_perimeter_m
from app.models import (
    ApprovalState,
    City,
    Device,
    DeviceHealth,
    LineState,
    Pole,
    Result,
    ResultKind,
    Role,
    User,
)
from app.security import new_secret_token, sha256_hex
from app.services.pole_import import MAX_POLE_NUMBER, PoleImportError, check_points, parse_poles
from app.services.status import STATE_LOCK, pole_points, set_reference
from app.ws import revoke_live_access

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

# Fiber shorter than the ring by more than this needs explicit confirmation (R27).
SHORT_FIBER_CONFIRM_PCT = 5.0


# --- users -------------------------------------------------------------------


class AdminUserOut(UserOut):
    created_at: datetime


@router.get("/users", response_model=list[AdminUserOut])
def list_users(approval_state: ApprovalState | None = None, db: Session = Depends(get_db)) -> list[User]:
    query = select(User).order_by(User.created_at, User.id)
    if approval_state is not None:
        query = query.where(User.approval_state == approval_state)
    return list(db.scalars(query))


def _target_user(user_id: int, admin: User, db: Session) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="user not found")
    if user.id == admin.id:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="admins cannot change their own account")
    return user


@router.post("/users/{user_id}/approve", response_model=AdminUserOut)
def approve_user(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> User:
    """Approve the user; a requested city becomes the approved city (R22)."""
    user = _target_user(user_id, admin, db)
    if user.requested_city_id is not None:
        user.approved_city_id = user.requested_city_id
        user.requested_city_id = None
    if user.role == Role.MAINTAINER and user.approved_city_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="maintainer has no city to approve")
    user.approval_state = ApprovalState.APPROVED
    user.approved_at = utcnow()
    db.commit()
    return user


@router.post("/users/{user_id}/reject", response_model=AdminUserOut)
def reject_user(
    user_id: int, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> User:
    user = _target_user(user_id, admin, db)
    user.approval_state = ApprovalState.REJECTED
    db.commit()
    revoke_live_access(request.app, db, user.id)
    return user


@router.post("/users/{user_id}/disable", response_model=AdminUserOut)
def disable_user(
    user_id: int, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> User:
    user = _target_user(user_id, admin, db)
    user.approval_state = ApprovalState.DISABLED
    db.commit()
    revoke_live_access(request.app, db, user.id)
    return user


@router.post("/users/{user_id}/promote", response_model=AdminUserOut)
def promote_user(
    user_id: int, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> User:
    """Make the user an admin (R24). The role change closes their sockets and push tokens (R20)."""
    user = _target_user(user_id, admin, db)
    user.role = Role.ADMIN
    db.commit()
    revoke_live_access(request.app, db, user.id)
    return user


# --- cities and device keys ------------------------------------------------------


class CityCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    launch_offset_m: float = Field(default=1000.0, ge=0, allow_inf_nan=False)
    break_tolerance_m: float = Field(default=50.0, gt=0, allow_inf_nan=False)


class CityPatchIn(BaseModel):
    # Omitted fields stay unchanged; an explicit null is rejected (422).
    launch_offset_m: float = Field(default=None, ge=0, allow_inf_nan=False)
    break_tolerance_m: float = Field(default=None, gt=0, allow_inf_nan=False)


class AdminCityOut(BaseModel):
    id: int
    name: str
    launch_offset_m: float
    break_tolerance_m: float
    reference_fiber_length_m: float | None
    reference_set_at: datetime | None
    line_state: LineState
    device_health: DeviceHealth
    has_device: bool
    device_key_rotated_at: datetime | None
    pole_count: int
    perimeter_m: float | None


class DeviceKeyOut(BaseModel):
    device_id: int
    city_id: int
    # Plaintext key, returned only in this response (R25).
    api_key: str


def _city_or_404(db: Session, city_id: int) -> City:
    city = db.get(City, city_id)
    if city is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="city not found")
    return city


def _city_out(db: Session, city: City) -> AdminCityOut:
    device = db.scalar(select(Device).where(Device.city_id == city.id))
    poles = pole_points(db, city.id)
    return AdminCityOut(
        id=city.id,
        name=city.name,
        launch_offset_m=city.launch_offset_m,
        break_tolerance_m=city.break_tolerance_m,
        reference_fiber_length_m=city.reference_fiber_length_m,
        reference_set_at=city.reference_set_at,
        line_state=city.line_state,
        device_health=city.device_health,
        has_device=device is not None,
        device_key_rotated_at=device.key_rotated_at if device else None,
        pole_count=len(poles),
        perimeter_m=ring_perimeter_m(poles),
    )


@router.get("/cities", response_model=list[AdminCityOut])
def list_cities(db: Session = Depends(get_db)) -> list[AdminCityOut]:
    return [_city_out(db, c) for c in db.scalars(select(City).order_by(City.name, City.id))]


@router.post("/cities", status_code=status.HTTP_201_CREATED, response_model=AdminCityOut)
def create_city(body: CityCreateIn, db: Session = Depends(get_db)) -> AdminCityOut:
    city = City(
        name=body.name.strip(),
        launch_offset_m=body.launch_offset_m,
        break_tolerance_m=body.break_tolerance_m,
    )
    db.add(city)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="city name already exists") from None
    return _city_out(db, city)


@router.patch("/cities/{city_id}", response_model=AdminCityOut)
def update_city(city_id: int, body: CityPatchIn, db: Session = Depends(get_db)) -> AdminCityOut:
    """Edit the launch-box offset and break tolerance (R27)."""
    with STATE_LOCK:  # the status engine reads both values while applying a result
        city = _city_or_404(db, city_id)
        for field in body.model_fields_set:
            setattr(city, field, getattr(body, field))
        db.commit()
    return _city_out(db, city)


@router.post("/cities/{city_id}/device-key", status_code=status.HTTP_201_CREATED, response_model=DeviceKeyOut)
def issue_device_key(city_id: int, db: Session = Depends(get_db)) -> DeviceKeyOut:
    """Create the city's device, or rotate its key. The old key stops working at once."""
    _city_or_404(db, city_id)
    api_key = new_secret_token()
    device = db.scalar(select(Device).where(Device.city_id == city_id))
    if device is None:
        device = Device(city_id=city_id, api_key_hash=sha256_hex(api_key))
        db.add(device)
    else:
        device.api_key_hash = sha256_hex(api_key)
        device.key_rotated_at = utcnow()
    db.commit()
    return DeviceKeyOut(device_id=device.id, city_id=city_id, api_key=api_key)


# --- poles (R26) ---------------------------------------------------------------------


class PoleIO(BaseModel):
    number: int = Field(ge=1, le=MAX_POLE_NUMBER)
    lat: float = Field(allow_inf_nan=False)
    lon: float = Field(allow_inf_nan=False)


class PolesPreviewOut(BaseModel):
    poles: list[PoleIO]
    count: int
    perimeter_m: float | None


class PolesIn(BaseModel):
    poles: list[PoleIO]


class PolesSavedOut(BaseModel):
    count: int
    perimeter_m: float | None


def _invalid_poles(exc: PoleImportError) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"code": "invalid_poles", "errors": exc.errors}
    )


@router.post("/cities/{city_id}/poles/preview", response_model=PolesPreviewOut)
def preview_poles(city_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)) -> PolesPreviewOut:
    """Parse a CSV or KML pole file for the map preview. Nothing is saved."""
    _city_or_404(db, city_id)
    try:
        poles = parse_poles(file.file.read(), file.filename)
    except PoleImportError as exc:
        raise _invalid_poles(exc) from None
    return PolesPreviewOut(
        poles=[PoleIO(number=p.number, lat=p.lat, lon=p.lon) for p in poles],
        count=len(poles),
        perimeter_m=ring_perimeter_m(poles),
    )


@router.put("/cities/{city_id}/poles", response_model=PolesSavedOut)
def replace_poles(city_id: int, body: PolesIn, db: Session = Depends(get_db)) -> PolesSavedOut:
    """Replace the city's ring in one transaction; invalid input leaves the old ring."""
    _city_or_404(db, city_id)
    try:
        poles = check_points(PolePoint(p.number, p.lat, p.lon) for p in body.poles)
    except PoleImportError as exc:
        raise _invalid_poles(exc) from None
    with STATE_LOCK:  # break mapping reads the ring while applying a result
        db.execute(delete(Pole).where(Pole.city_id == city_id))
        db.add_all(Pole(city_id=city_id, number=p.number, lat=p.lat, lon=p.lon) for p in poles)
        db.commit()
    return PolesSavedOut(count=len(poles), perimeter_m=ring_perimeter_m(poles))


# --- reference (R27, AE10) --------------------------------------------------------------


class ReferenceIn(BaseModel):
    confirm_short: bool = False


class ReferenceOut(BaseModel):
    reference_fiber_length_m: float
    reference_set_at: datetime
    line_state: LineState


def _refuse(code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail={"code": code, "message": message, **extra})


@router.post("/cities/{city_id}/reference", response_model=ReferenceOut)
def set_city_reference(
    city_id: int, body: ReferenceIn, request: Request, db: Session = Depends(get_db)
) -> ReferenceOut:
    """Set the reference from the latest intact result (R27).

    Moves AWAITING_REFERENCE -> OK, or re-baselines an OK city. Refused during a
    suspected or confirmed break (AE10), when the latest message is not a result
    with an end event, and — unless confirmed — when the fiber is more than 5%
    shorter than the pole ring.
    """
    app = request.app
    with STATE_LOCK:  # no result may change line_state between the checks and the write
        city = _city_or_404(db, city_id)
        if city.line_state in (LineState.SUSPECT_BREAK, LineState.BREAK):
            raise _refuse("break_active", "the line is in a suspected or confirmed break; resolve it first")

        latest = db.scalar(
            select(Result)
            .where(Result.city_id == city_id)
            .order_by(Result.received_at.desc(), Result.seq.desc(), Result.id.desc())
            .limit(1)
        )
        if latest is None:
            raise _refuse("no_valid_result", "no test result has been received for this city yet")
        if latest.kind == ResultKind.FAULT:
            raise _refuse(
                "no_valid_result",
                f"the latest device message is an equipment fault ({latest.fault_kind}); wait for a valid result",
            )
        if latest.end_event_distance_m is None:
            raise _refuse("no_valid_result", "the latest test result has no end event")

        end_m = latest.end_event_distance_m
        fiber_m = end_m - city.launch_offset_m
        perimeter = ring_perimeter_m(pole_points(db, city_id))
        if perimeter:
            shortfall_pct = (perimeter - fiber_m) / perimeter * 100.0
            if shortfall_pct > SHORT_FIBER_CONFIRM_PCT and not body.confirm_short:
                raise _refuse(
                    "confirm_required",
                    f"the fiber is {shortfall_pct:.1f}% shorter than the pole ring; confirm to set it anyway",
                    fiber_length_m=fiber_m,
                    perimeter_m=perimeter,
                    shortfall_pct=shortfall_pct,
                )

        previous = city.reference_fiber_length_m
        set_reference(db, app.state.event_bus, city_id, end_m, app.state.clock())
        if previous is not None:
            log.info("city %s: reference re-baselined from %.1f m to %.1f m", city_id, previous, end_m)
        db.refresh(city)
        return ReferenceOut(
            reference_fiber_length_m=city.reference_fiber_length_m,
            reference_set_at=city.reference_set_at,
            line_state=city.line_state,
        )

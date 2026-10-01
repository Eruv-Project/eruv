"""City: one eruv line with its two persisted state machines (KTD6)."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime, utcnow
from app.models._types import str_enum


class LineState(enum.StrEnum):
    AWAITING_REFERENCE = "AWAITING_REFERENCE"
    OK = "OK"
    SUSPECT_BREAK = "SUSPECT_BREAK"
    BREAK = "BREAK"


class DeviceHealth(enum.StrEnum):
    ONLINE = "ONLINE"
    DISCONNECTED = "DISCONNECTED"
    FAULT = "FAULT"


class City(Base):
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    # Launch box length subtracted from OTDR distances before mapping (R12).
    launch_offset_m: Mapped[float] = mapped_column(default=1000.0)
    break_tolerance_m: Mapped[float] = mapped_column(default=50.0)
    # Set from the latest intact result by an admin (R27); null => AWAITING_REFERENCE.
    reference_fiber_length_m: Mapped[float | None]
    reference_set_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    line_state: Mapped[LineState] = mapped_column(
        str_enum(LineState, "line_state"), default=LineState.AWAITING_REFERENCE
    )
    # A city with no heartbeat yet has no working monitor.
    device_health: Mapped[DeviceHealth] = mapped_column(
        str_enum(DeviceHealth, "device_health"), default=DeviceHealth.DISCONNECTED
    )
    # End-event distance of the first short result while in SUSPECT_BREAK (R10).
    suspect_distance_m: Mapped[float | None]
    # Server receive time of the most recent result (the "last completed check").
    last_result_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

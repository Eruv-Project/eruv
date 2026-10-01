"""StatusEvent: one transition of a city's line state or device health (R22, R23)."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime, utcnow
from app.models._types import str_enum


class StatusDimension(enum.StrEnum):
    LINE = "line"
    DEVICE = "device"


class StatusEvent(Base):
    __tablename__ = "status_events"
    __table_args__ = (Index("ix_status_events_city_id_occurred_at", "city_id", "occurred_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="CASCADE"))
    dimension: Mapped[StatusDimension] = mapped_column(str_enum(StatusDimension, "status_dimension"))
    # LineState or DeviceHealth values, per dimension.
    from_state: Mapped[str] = mapped_column(String(32))
    to_state: Mapped[str] = mapped_column(String(32))
    # Server time.
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    # Caused by a backlog message: logged, not pushed individually.
    replayed: Mapped[bool] = mapped_column(default=False)
    # Break mapping (bounding poles, coordinate) for transitions into BREAK.
    mapping: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    detail: Mapped[str | None] = mapped_column(Text)
    result_id: Mapped[int | None] = mapped_column(ForeignKey("results.id", ondelete="SET NULL"))

"""Device: the one Pi agent of a city, authenticated by a hashed API key."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime, utcnow


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="CASCADE"), unique=True)
    # sha256 hex of the API key; the plaintext is shown to the admin once (R25).
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    key_rotated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # Highest result/fault seq accepted from this device (shared counter, see contract).
    highest_seq: Mapped[int] = mapped_column(default=0)
    last_fault_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

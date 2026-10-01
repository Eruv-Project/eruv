"""Pole: one numbered point on a city's closed ring."""

from __future__ import annotations

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Pole(Base):
    __tablename__ = "poles"
    __table_args__ = (UniqueConstraint("city_id", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="CASCADE"), index=True)
    # 1..N, consecutive; ring order is by number (R26).
    number: Mapped[int]
    lat: Mapped[float]
    lon: Mapped[float]

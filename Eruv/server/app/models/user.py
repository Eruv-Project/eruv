"""App user: maintainer or admin, gated by admin approval (R19, R20, R24)."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime, utcnow
from app.models._types import str_enum


class Role(enum.StrEnum):
    MAINTAINER = "maintainer"
    ADMIN = "admin"


class ApprovalState(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DISABLED = "disabled"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(40))
    # Stored lower-cased.
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))  # argon2id
    role: Mapped[Role] = mapped_column(str_enum(Role, "role"), default=Role.MAINTAINER)
    approval_state: Mapped[ApprovalState] = mapped_column(
        str_enum(ApprovalState, "approval_state"), default=ApprovalState.PENDING, index=True
    )
    # The city this user may read. Scoping always uses this, never requested_city_id.
    approved_city_id: Mapped[int | None] = mapped_column(ForeignKey("cities.id", ondelete="SET NULL"))
    # City awaiting admin approval (registration or a city-change request, R22).
    requested_city_id: Mapped[int | None] = mapped_column(ForeignKey("cities.id", ondelete="SET NULL"))
    # sha256 hex of the token the pending screen polls with; replaced on each new pending period.
    registration_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

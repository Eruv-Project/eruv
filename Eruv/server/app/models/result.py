"""Result: one accepted device message, either an OTDR test result or an equipment fault.

Both kinds share the per-device `seq` counter (contracts/pi-server-api.md), so they
share one table. `(device_id, seq)` is indexed but deliberately not unique: after a
device reset a lower `seq` with a different payload is accepted and stored.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime, utcnow
from app.models._types import str_enum


class ResultKind(enum.StrEnum):
    RESULT = "result"
    FAULT = "fault"


class Result(Base):
    __tablename__ = "results"
    __table_args__ = (
        Index("ix_results_device_id_seq", "device_id", "seq"),
        Index("ix_results_city_id_received_at", "city_id", "received_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="CASCADE"))
    kind: Mapped[ResultKind] = mapped_column(str_enum(ResultKind, "result_kind"))
    seq: Mapped[int]
    # sha256 of the message for the (device, seq) duplicate check. The ingest code
    # defines which fields it covers (queued_s changes between delivery attempts).
    payload_sha256: Mapped[str] = mapped_column(String(64))

    # Server time; the only clock used for ordering (KTD8).
    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    # Pi wall clock: result.measured_at or fault.occurred_at. Display only.
    measured_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    queued_s: Mapped[float] = mapped_column(default=0.0)
    # Backlog (queued_s > 180 or drain burst): drives state, not pushed per transition.
    backlog: Mapped[bool] = mapped_column(default=False)
    agent_version: Mapped[str] = mapped_column(String(64))

    # kind == result (contracts/result.schema.json)
    end_event_distance_m: Mapped[float | None]
    fiber_length_m: Mapped[float | None]
    link_loss_db: Mapped[float | None]
    otdr_firmware: Mapped[str | None] = mapped_column(String(64))
    params: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    events: Mapped[list[Any] | None] = mapped_column(JSON)
    pi_health: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # kind == fault (contracts/fault.schema.json)
    fault_kind: Mapped[str | None] = mapped_column(String(32))
    fault_detail: Mapped[str | None] = mapped_column(Text)
    fault_status_code: Mapped[int | None]

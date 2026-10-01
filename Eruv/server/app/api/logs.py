"""City log (R23): status transitions, result summaries and faults, newest first.

``GET /api/cities/{city_id}/logs?type=transitions|results|faults&from=&to=&limit=&cursor=``
- ``type`` defaults to ``transitions``; ``results`` lists test results, ``faults``
  equipment fault messages.
- ``from`` / ``to`` are inclusive ISO-8601 bounds on the server time
  (``occurred_at`` of a transition, ``received_at`` of a result or fault). The
  app sends ``from`` = now - 7 days for its default view.
- ``next_cursor`` is opaque; pass it back as ``cursor`` with the same filters.
  It is null when there are no older items in the range.
"""

from __future__ import annotations

import base64
import binascii
import enum
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.api.deps import require_city_access
from app.db import get_db
from app.models import City, Result, ResultKind, StatusEvent

router = APIRouter(prefix="/api/cities", tags=["logs"])


class LogType(enum.StrEnum):
    TRANSITIONS = "transitions"
    RESULTS = "results"
    FAULTS = "faults"


class LogItem(BaseModel):
    kind: Literal["transition", "result", "fault"]
    id: int
    # Server time: when the transition happened / the message was received.
    occurred_at: datetime
    # Backlog: the event came from a drained spool (R9) and was not pushed.
    replayed: bool
    # transition
    dimension: str | None = None
    from_state: str | None = None
    to_state: str | None = None
    mapping: dict[str, Any] | None = None
    detail: str | None = None
    result_id: int | None = None
    # result / fault
    seq: int | None = None
    measured_at: datetime | None = None  # the Pi's clock; display only
    end_event_distance_m: float | None = None
    fiber_length_m: float | None = None
    link_loss_db: float | None = None
    fault_kind: str | None = None
    fault_detail: str | None = None
    fault_status_code: int | None = None


class LogPage(BaseModel):
    items: list[LogItem]
    next_cursor: str | None


def _encode_cursor(at: datetime, row_id: int) -> str:
    return base64.urlsafe_b64encode(f"{at.isoformat()}|{row_id}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        at, row_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        value = datetime.fromisoformat(at)
        if value.tzinfo is None:
            raise ValueError("naive")
        return value, int(row_id)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid cursor") from None


def _aware(value: datetime | None, name: str) -> datetime | None:
    if value is not None and value.tzinfo is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"'{name}' needs a UTC offset")
    return value


def _transition(row: StatusEvent) -> LogItem:
    return LogItem(
        kind="transition",
        id=row.id,
        occurred_at=row.occurred_at,
        replayed=row.replayed,
        dimension=row.dimension.value,
        from_state=row.from_state,
        to_state=row.to_state,
        mapping=row.mapping,
        detail=row.detail,
        result_id=row.result_id,
    )


def _result(row: Result) -> LogItem:
    return LogItem(
        kind=row.kind.value,
        id=row.id,
        occurred_at=row.received_at,
        replayed=row.backlog,
        seq=row.seq,
        measured_at=row.measured_at,
        end_event_distance_m=row.end_event_distance_m,
        fiber_length_m=row.fiber_length_m,
        link_loss_db=row.link_loss_db,
        fault_kind=row.fault_kind,
        fault_detail=row.fault_detail,
        fault_status_code=row.fault_status_code,
    )


@router.get("/{city_id}/logs", response_model=LogPage)
def city_logs(
    city: City = Depends(require_city_access),
    db: Session = Depends(get_db),
    log_type: LogType = Query(LogType.TRANSITIONS, alias="type"),
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
) -> LogPage:
    from_ = _aware(from_, "from")
    to = _aware(to, "to")
    if log_type == LogType.TRANSITIONS:
        model, at_col, convert = StatusEvent, StatusEvent.occurred_at, _transition
        query = select(StatusEvent).where(StatusEvent.city_id == city.id)
    else:
        kind = ResultKind.RESULT if log_type == LogType.RESULTS else ResultKind.FAULT
        model, at_col, convert = Result, Result.received_at, _result
        query = select(Result).where(Result.city_id == city.id, Result.kind == kind)

    if from_ is not None:
        query = query.where(at_col >= from_)
    if to is not None:
        query = query.where(at_col <= to)
    if cursor is not None:
        at, row_id = _decode_cursor(cursor)
        query = query.where(or_(at_col < at, and_(at_col == at, model.id < row_id)))
    rows = list(db.scalars(query.order_by(at_col.desc(), model.id.desc()).limit(limit + 1)))

    items = [convert(row) for row in rows[:limit]]
    next_cursor = _encode_cursor(items[-1].occurred_at, items[-1].id) if len(rows) > limit else None
    return LogPage(items=items, next_cursor=next_cursor)

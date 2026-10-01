"""Device API: heartbeat, results, faults (contracts/pi-server-api.md).

Bodies are validated against the shared JSON Schemas in the repo's `contracts/`
folder (never copied). Results and faults are deduplicated on `(device, seq)`
with a payload hash that excludes `queued_s`, which changes between delivery
attempts. Ordering uses the server's receive time, never the Pi's clock (KTD8).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_device
from app.db import get_db
from app.models import Device, Result, ResultKind
from app.security import sha256_hex
from app.services.status import STATE_LOCK, apply_fault, apply_heartbeat, apply_result

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/device/v1", tags=["device"])

REPO_CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"
SCHEMAS = {"heartbeat": "heartbeat.schema.json", "result": "result.schema.json", "fault": "fault.schema.json"}


def load_validators(contracts_dir: Path | None) -> dict[str, Draft202012Validator]:
    folder = contracts_dir or REPO_CONTRACTS_DIR
    validators = {}
    for name, filename in SCHEMAS.items():
        schema = json.loads((folder / filename).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validators[name] = Draft202012Validator(schema, format_checker=FormatChecker())
    return validators


def _validate(request: Request, name: str, payload: Any) -> None:
    validator: Draft202012Validator = request.app.state.contract_validators[name]
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    if errors:
        detail = [{"loc": list(e.absolute_path), "msg": e.message} for e in errors[:10]]
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def _parse_time(payload: dict[str, Any], field: str) -> datetime:
    """RFC 3339 date-time; checked here too because jsonschema's format check is optional."""
    try:
        value = datetime.fromisoformat(payload[field])
    except ValueError:
        value = None
    if value is None or value.tzinfo is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=[{"loc": [field], "msg": "not an ISO-8601 date-time with offset"}],
        )
    return value


def payload_hash(kind: ResultKind, payload: dict[str, Any]) -> str:
    stable = {k: v for k, v in payload.items() if k != "queued_s"}
    canonical = json.dumps({"kind": kind.value, "body": stable}, sort_keys=True, separators=(",", ":"))
    return sha256_hex(canonical)


def _accept_seq(db: Session, device: Device, kind: ResultKind, payload: dict[str, Any]) -> str:
    """Return the payload hash, or raise 409 for an identical repeat. Updates highest_seq."""
    seq = payload["seq"]
    digest = payload_hash(kind, payload)
    duplicate = db.scalar(
        select(Result.id).where(Result.device_id == device.id, Result.seq == seq, Result.payload_sha256 == digest)
    )
    if duplicate is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="duplicate seq")
    if seq <= device.highest_seq:
        log.warning(
            "device %s reset: seq %s after highest %s with a different payload; continuing from the new sequence",
            device.id, seq, device.highest_seq,
        )
    device.highest_seq = seq
    return digest


def _new_row(request: Request, device: Device, kind: ResultKind, payload: dict[str, Any], digest: str,
             measured_at: datetime, now: datetime) -> Result:
    return Result(
        device_id=device.id,
        city_id=device.city_id,
        kind=kind,
        seq=payload["seq"],
        payload_sha256=digest,
        received_at=now,
        measured_at=measured_at,
        queued_s=payload["queued_s"],
        backlog=payload["queued_s"] > request.app.state.settings.backlog_threshold_s,
        agent_version=payload["agent_version"],
    )


@router.post("/heartbeat")
def heartbeat(
    request: Request,
    payload: Any = Body(...),
    device: Device = Depends(current_device),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    _validate(request, "heartbeat", payload)
    _parse_time(payload, "sent_at")
    now = request.app.state.clock()
    with STATE_LOCK:
        apply_heartbeat(db, request.app.state.event_bus, device, now)
    return {"server_time": now.isoformat()}


@router.post("/results", status_code=status.HTTP_201_CREATED)
def post_result(
    request: Request,
    payload: Any = Body(...),
    device: Device = Depends(current_device),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    _validate(request, "result", payload)
    measured_at = _parse_time(payload, "measured_at")
    with STATE_LOCK:
        now = request.app.state.clock()
        digest = _accept_seq(db, device, ResultKind.RESULT, payload)
        row = _new_row(request, device, ResultKind.RESULT, payload, digest, measured_at, now)
        row.end_event_distance_m = payload["end_event_distance_m"]
        row.fiber_length_m = payload["fiber_length_m"]
        row.link_loss_db = payload.get("link_loss_db")
        row.otdr_firmware = (payload.get("otdr") or {}).get("firmware")
        row.params = payload["params"]
        row.events = payload["events"]
        row.pi_health = payload["pi_health"]
        apply_result(db, request.app.state.event_bus, device, row, now)
    return {"id": row.id}


@router.post("/faults", status_code=status.HTTP_201_CREATED)
def post_fault(
    request: Request,
    payload: Any = Body(...),
    device: Device = Depends(current_device),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    _validate(request, "fault", payload)
    occurred_at = _parse_time(payload, "occurred_at")
    with STATE_LOCK:
        now = request.app.state.clock()
        digest = _accept_seq(db, device, ResultKind.FAULT, payload)
        row = _new_row(request, device, ResultKind.FAULT, payload, digest, occurred_at, now)
        row.fault_kind = payload["kind"]
        row.fault_detail = payload["detail"]
        row.fault_status_code = payload.get("status_code")
        apply_fault(db, request.app.state.event_bus, device, row, now)
    return {"id": row.id}

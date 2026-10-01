"""Watchdog: applies R13's timeouts every few seconds and records its own liveness.

`watchdog_tick` is one evaluation at an injected time; `run_watchdog` is the
lifespan loop. The loop stores its last successful run on
``app.state.watchdog_last_run`` for ``/health`` (KTD12).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.events import EventBus
from app.models import City, Device, DeviceHealth, StatusDimension, StatusEvent
from app.services.status import STATE_LOCK, Pending, set_health
from app.status_engine import health_on_watchdog

log = logging.getLogger(__name__)


def _online_since(db: Session, city_id: int) -> datetime | None:
    return db.scalar(
        select(func.max(StatusEvent.occurred_at)).where(
            StatusEvent.city_id == city_id,
            StatusEvent.dimension == StatusDimension.DEVICE,
            StatusEvent.to_state == DeviceHealth.ONLINE.value,
        )
    )


def watchdog_tick(
    session_factory: sessionmaker[Session],
    bus: EventBus,
    settings: Settings,
    now: datetime,
    server_started_at: datetime,
) -> None:
    with STATE_LOCK, session_factory() as db:
        pending = Pending()
        for device, city in db.execute(select(Device, City).join(City, Device.city_id == City.id)).all():
            if city.device_health == DeviceHealth.DISCONNECTED:
                continue
            new, detail = health_on_watchdog(
                city.device_health,
                now=now,
                last_heartbeat_at=device.last_heartbeat_at,
                last_result_at=city.last_result_at,
                last_fault_at=device.last_fault_at,
                server_started_at=server_started_at,
                online_since=_online_since(db, city.id),
                heartbeat_timeout_s=settings.missed_heartbeats * settings.heartbeat_interval_s,
                result_timeout_s=settings.missed_cadences * settings.test_cadence_s,
            )
            set_health(db, pending, city, new, now, detail=detail)
        pending.commit_and_publish(db, bus)


async def run_watchdog(app: FastAPI) -> None:
    state = app.state
    while True:
        now = state.clock()
        try:
            await asyncio.to_thread(
                watchdog_tick, state.session_factory, state.event_bus, state.settings, now, state.started_at
            )
            state.watchdog_last_run = now
        except Exception:
            log.exception("watchdog tick failed")
        await asyncio.sleep(state.settings.watchdog_interval_s)

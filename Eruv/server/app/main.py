"""FastAPI application factory.

Run with: `uvicorn app.main:create_app --factory` (one worker, KTD11).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app import ws
from app.api import admin, auth, cities, ingest, logs, push_tokens
from app.config import Settings, get_settings
from app.db import make_engine, make_session_factory, utcnow
from app.events import EventBus
from app.logging_setup import install_token_redaction
from app.push import PushService
from app.security import RateLimiter
from app.services.watchdog import run_watchdog


# /health fails when the watchdog loop has not run for this long (KTD12).
HEALTH_MAX_WATCHDOG_AGE_S = 30.0


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    state = app.state
    state.live_hub.start()
    state.push.start()
    unsubscribe = [state.event_bus.subscribe(state.live_hub.on_event), state.event_bus.subscribe(state.push.on_event)]
    task = asyncio.create_task(run_watchdog(app)) if state.settings.watchdog_enabled else None
    try:
        yield
    finally:
        for stop in unsubscribe:
            stop()
        state.live_hub.stop()
        await state.push.stop()
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    # uvicorn logs WebSocket paths with the ?token= access token; redact it.
    install_token_redaction()
    app = FastAPI(title="Eruv monitoring server", lifespan=lifespan)

    engine = make_engine(settings.database_url)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.rate_limiter = RateLimiter()
    # Server time source for ingest and the watchdog; tests replace it.
    app.state.clock = utcnow
    # Missed heartbeats and results are counted from no earlier than this (KTD6).
    app.state.started_at = utcnow()
    app.state.event_bus = EventBus()
    # Last successful watchdog run; /health fails when it is stale (KTD12).
    app.state.watchdog_last_run = None
    # Live fan-out (WebSocket) and push, fed by the event bus while the app runs.
    app.state.live_hub = ws.LiveHub()
    app.state.push = PushService(app.state.session_factory)
    app.state.contract_validators = ingest.load_validators(settings.contracts_dir)

    app.include_router(auth.router)
    app.include_router(cities.router)
    app.include_router(admin.router)
    app.include_router(ingest.router)
    app.include_router(logs.router)
    app.include_router(push_tokens.router)
    app.include_router(ws.router)

    @app.get("/health")
    def health() -> JSONResponse:
        """200 only while the watchdog loop runs; the uptime monitor alerts otherwise (KTD12)."""
        last = app.state.watchdog_last_run
        fresh = last is not None and (app.state.clock() - last).total_seconds() <= HEALTH_MAX_WATCHDOG_AGE_S
        return JSONResponse(
            {"status": "ok" if fresh else "stale", "watchdog_last_run": last.isoformat() if last else None},
            status_code=200 if fresh else 503,
        )

    return app

"""The agent: one OTDR test every cadence period, results and faults spooled,
the uplink draining the spool, and a heartbeat every 10 s (R2, R3, R5, R7, R9)."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from eruv_agent import __version__
from eruv_agent import protocol as p
from eruv_agent.config import Config
from eruv_agent.otdr_client import OtdrClient, OtdrDisconnectedError, OtdrTimeoutError
from eruv_agent.spool import Spool, SystemClock
from eruv_agent.uplink import Uplink

log = logging.getLogger(__name__)


def utc_iso(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def pi_health(disk_path: str | Path, clock=None) -> dict:
    """Uptime, CPU temperature and free disk. Temperature and disk are None when unavailable."""
    clock = clock or SystemClock()
    try:
        cpu_temp_c = int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000.0
    except (OSError, ValueError):
        cpu_temp_c = None
    try:
        disk_free_mb = round(shutil.disk_usage(disk_path).free / 1_048_576, 1)
    except OSError:
        disk_free_mb = None
    return {"uptime_s": round(clock.uptime_s(), 1), "cpu_temp_c": cpu_temp_c, "disk_free_mb": disk_free_mb}


def build_result(
    full: p.FullResult,
    *,
    seq: int,
    measured_at: str,
    otdr_version: p.VersionInfo | None,
    health: dict,
) -> dict:
    """A result per contracts/result.schema.json, without queued_s (added at send time)
    and without the curve (v1 never sends curve_b64)."""
    c = full.conditions
    return {
        "seq": seq,
        "measured_at": measured_at,
        "agent_version": __version__,
        "otdr": {
            "firmware": otdr_version.firmware if otdr_version else None,
            "device": otdr_version.device if otdr_version else None,
        },
        "params": {
            "wavelength_nm": c.wavelength_nm,
            "range_m": c.range_m,
            "pulse_width_ns": c.pulse_width_ns,
            "measure_time_ms": c.measure_time_ms,
            "group_index": c.group_index,
            "sample_rate_hz": c.sample_rate_hz,
            "end_threshold_db": c.end_threshold_db,
            "non_reflect_threshold_db": c.non_reflect_threshold_db,
            "test_mode": c.test_mode,
            "test_method": c.test_method,
        },
        "fiber_length_m": c.fiber_length_m,
        "link_loss_db": c.link_loss_db,
        "link_attenuation_db_per_km": c.link_attenuation_db_per_km,
        "end_event_distance_m": full.end_event_distance_m,
        "events": [dataclasses.asdict(e) for e in full.events],
        "pi_health": health,
    }


def build_fault(*, seq: int, occurred_at: str, kind: str, detail: str, status_code: int | None = None) -> dict:
    return {
        "seq": seq,
        "occurred_at": occurred_at,
        "agent_version": __version__,
        "kind": kind,
        "detail": detail,
        "status_code": status_code,
    }


class Agent:
    def __init__(self, cfg: Config, *, transport=None, clock=None) -> None:
        self.cfg = cfg
        self.clock = clock or SystemClock()
        self.spool = Spool(cfg.spool.path, cfg.spool.capacity, clock=self.clock)
        self.otdr = OtdrClient(cfg.otdr)
        self.uplink = Uplink(
            cfg.server,
            self.spool,
            retry_s=cfg.schedule.uplink_retry_s,
            heartbeat_s=cfg.schedule.heartbeat_s,
            heartbeat_fn=self.heartbeat,
            transport=transport,
        )

    def health(self) -> dict:
        return pi_health(Path(self.cfg.spool.path).parent, self.clock)

    def heartbeat(self) -> dict:
        h = self.health()
        return {
            "sent_at": utc_iso(self.clock.wall()),
            "agent_version": __version__,
            "otdr_connected": self.otdr.connected,
            "test_running": self.otdr.test_running,
            "uptime_s": h["uptime_s"],
            "cpu_temp_c": h["cpu_temp_c"],
            "spool_depth": self.spool.depth(),
        }

    def _fault(self, kind: str, detail: str, status_code: int | None = None) -> None:
        occurred_at = utc_iso(self.clock.wall())
        seq = self.spool.enqueue(
            "fault",
            lambda s: build_fault(seq=s, occurred_at=occurred_at, kind=kind, detail=detail, status_code=status_code),
        )
        log.error("fault seq %d %s: %s", seq, kind, detail)

    async def run_cycle(self) -> None:
        """One test: start, await final data, spool a result or a fault."""
        measured_at = utc_iso(self.clock.wall())
        try:
            if not await self.otdr.wait_connected(self.cfg.otdr.connect_timeout_s):
                self._fault("otdr_unreachable", self.otdr.last_error or "OTDR not connected")
                return
            try:
                full = await self.otdr.run_test(self.cfg.test.start_params())
            except OtdrTimeoutError as exc:
                self._fault("otdr_timeout", str(exc))
            except p.OtdrStatusError as exc:
                self._fault("otdr_error_status", str(exc), exc.code)
            except OtdrDisconnectedError as exc:
                self._fault("otdr_socket", str(exc))
            except p.ProtocolError as exc:
                self._fault("otdr_protocol", str(exc))
            else:
                seq = self.spool.enqueue(
                    "result",
                    lambda s: build_result(
                        full, seq=s, measured_at=measured_at,
                        otdr_version=self.otdr.version, health=self.health(),
                    ),
                )
                log.info("result seq %d: end event %s m, %d events",
                         seq, full.end_event_distance_m, len(full.events))
                return
            await self.otdr.cancel()  # no-op when the socket is down; retry next cycle
        finally:
            self.uplink.notify()

    async def cycle_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            started = loop.time()
            await self.run_cycle()
            # R2: the next test starts one cadence after this one STARTED.
            await asyncio.sleep(max(0.0, started + self.cfg.schedule.cadence_s - loop.time()))

    async def run(self) -> None:
        log.info("eruv-agent %s: OTDR %s:%d, server %s, cadence %.0f s",
                 __version__, self.cfg.otdr.host, self.cfg.otdr.port,
                 self.cfg.server.base_url, self.cfg.schedule.cadence_s)
        tasks = [
            asyncio.create_task(self.otdr.run(), name="otdr"),
            asyncio.create_task(self.uplink.run(), name="uplink"),
            asyncio.create_task(self.uplink.heartbeat_loop(), name="heartbeat"),
            asyncio.create_task(self.cycle_loop(), name="cycle"),
        ]
        try:
            # Any task ending is a bug; raise so systemd restarts the service.
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                t.result()
            raise RuntimeError(f"task ended unexpectedly: {[t.get_name() for t in done]}")
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def aclose(self) -> None:
        await self.uplink.aclose()
        self.spool.close()

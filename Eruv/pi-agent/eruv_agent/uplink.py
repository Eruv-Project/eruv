"""HTTPS uplink to the server (KTD3): spool drain and heartbeat.

Delivery rules (contracts/pi-server-api.md):

- 2xx and 409 (already stored) -> delivered, removed from the spool;
- 422 (invalid body) -> logged and dropped, a retry cannot succeed;
- anything else (5xx, 401, network error) -> kept; draining stops so later
  messages never overtake it, and is retried after ``retry_s``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

import httpx

from eruv_agent.config import ServerConfig
from eruv_agent.spool import Spool, SpooledMessage

log = logging.getLogger(__name__)

API = "/api/device/v1"
PATHS = {"result": f"{API}/results", "fault": f"{API}/faults"}


class Uplink:
    def __init__(
        self,
        cfg: ServerConfig,
        spool: Spool,
        *,
        retry_s: float,
        heartbeat_s: float,
        heartbeat_fn: Callable[[], dict],
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.spool = spool
        self.retry_s = retry_s
        self.heartbeat_s = heartbeat_s
        self.heartbeat_fn = heartbeat_fn
        self._wake = asyncio.Event()
        self._client = httpx.AsyncClient(
            base_url=cfg.base_url,
            headers={"X-Device-Key": cfg.device_key},
            timeout=cfg.request_timeout_s,
            transport=transport,
        )

    def notify(self) -> None:
        """Wake the drain loop: a message was just spooled."""
        self._wake.set()

    def wire_payload(self, msg: SpooledMessage) -> dict:
        return {**msg.payload, "queued_s": round(msg.queued_s(self.spool.clock), 3)}

    async def drain_once(self) -> bool:
        """Send spooled messages oldest-first. True when the spool was emptied."""
        while (msg := self.spool.peek()) is not None:
            try:
                resp = await self._client.post(PATHS[msg.kind], json=self.wire_payload(msg))
            except httpx.HTTPError as exc:
                log.warning("uplink: %s seq %d not delivered: %s", msg.kind, msg.seq, exc)
                return False
            if resp.is_success or resp.status_code == 409:
                self.spool.remove(msg.seq)
                log.info("uplink: %s seq %d delivered (%d)", msg.kind, msg.seq, resp.status_code)
            elif resp.status_code == 422:
                self.spool.remove(msg.seq)
                log.error("uplink: %s seq %d rejected as invalid, dropped: %s",
                          msg.kind, msg.seq, resp.text[:500])
            else:
                log.warning("uplink: %s seq %d not delivered: HTTP %d",
                            msg.kind, msg.seq, resp.status_code)
                return False
        return True

    async def run(self) -> None:
        while True:
            self._wake.clear()
            emptied = await self.drain_once()
            if emptied:
                await self._wake.wait()
            else:
                await asyncio.sleep(self.retry_s)

    async def heartbeat_loop(self) -> None:
        loop = asyncio.get_running_loop()
        next_at = loop.time()
        while True:
            try:
                resp = await self._client.post(f"{API}/heartbeat", json=self.heartbeat_fn())
                if not resp.is_success:
                    log.warning("heartbeat: HTTP %d", resp.status_code)
            except httpx.HTTPError as exc:
                log.warning("heartbeat failed: %s", exc)
            next_at += self.heartbeat_s
            now = loop.time()
            if next_at < now:  # a slow request overran the period; do not burst
                next_at = now
            await asyncio.sleep(next_at - now)

    async def aclose(self) -> None:
        await self._client.aclose()

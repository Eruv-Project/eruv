"""Uplink: seq-ordered drain, 409 = delivered, 422 dropped, 5xx kept; heartbeats."""

from __future__ import annotations

import asyncio
import json

import httpx
import jsonschema

from conftest import load_schema
from eruv_agent.spool import Spool
from eruv_agent.uplink import Uplink


class StubServer:
    """Records every request; the status per request comes from ``status_for``."""

    def __init__(self, status_for=lambda path, body: 201) -> None:
        self.status_for = status_for
        self.requests: list[tuple[str, dict, dict]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append((request.url.path, body, dict(request.headers)))
        status = self.status_for(request.url.path, body)
        if request.url.path.endswith("/heartbeat") and status == 201:
            status = 200
        return httpx.Response(status, json={})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def seqs(self, suffix: str = "/results") -> list[int]:
        return [b["seq"] for p, b, _ in self.requests if p.endswith(suffix)]


def make_uplink(cfg, spool, server: StubServer, heartbeat_fn=None) -> Uplink:
    return Uplink(
        cfg.server,
        spool,
        retry_s=cfg.schedule.uplink_retry_s,
        heartbeat_s=cfg.schedule.heartbeat_s,
        heartbeat_fn=heartbeat_fn or (lambda: {}),
        transport=server.transport(),
    )


def result_payload(seq: int) -> dict:
    return {"seq": seq, "kind": "fake"}


async def test_409_counts_as_delivered_and_is_not_retried(cfg_factory):
    cfg = cfg_factory()
    spool = Spool(cfg.spool.path, capacity=10)
    spool.enqueue("result", result_payload)
    server = StubServer(lambda path, body: 409)
    uplink = make_uplink(cfg, spool, server)
    await uplink.drain_once()
    await uplink.drain_once()
    await uplink.aclose()
    assert spool.depth() == 0
    assert server.seqs() == [1]


async def test_422_is_dropped(cfg_factory):
    cfg = cfg_factory()
    spool = Spool(cfg.spool.path, capacity=10)
    spool.enqueue("fault", result_payload)
    server = StubServer(lambda path, body: 422)
    uplink = make_uplink(cfg, spool, server)
    await uplink.drain_once()
    await uplink.aclose()
    assert spool.depth() == 0
    assert server.seqs("/faults") == [1]


async def test_503_outage_accumulates_then_delivers_in_seq_order(cfg_factory):
    cfg = cfg_factory()
    spool = Spool(cfg.spool.path, capacity=100)
    state = {"down": True}
    server = StubServer(lambda path, body: 503 if state["down"] else 201)
    uplink = make_uplink(cfg, spool, server)
    runner = asyncio.create_task(uplink.run())
    try:
        # "5 minutes" of outage, scaled: results keep arriving while the server is down.
        for _ in range(5):
            spool.enqueue("result", result_payload)
            uplink.notify()
            await asyncio.sleep(0.06)
        assert spool.depth() == 5
        assert server.requests, "the uplink kept retrying during the outage"
        assert all(b["seq"] == 1 for _, b, _ in server.requests), "never skips ahead of seq 1"

        state["down"] = False
        for _ in range(100):
            if spool.depth() == 0:
                break
            await asyncio.sleep(0.02)
    finally:
        runner.cancel()
        await uplink.aclose()
    assert spool.depth() == 0
    delivered = [b["seq"] for _, b, _ in server.requests[-5:]]
    assert delivered == [1, 2, 3, 4, 5]
    first = server.requests[-5][1]
    assert first["queued_s"] > 0.2  # it waited out the outage in the spool


async def test_requests_carry_device_key_and_queued_s(cfg_factory):
    cfg = cfg_factory()
    spool = Spool(cfg.spool.path, capacity=10)
    spool.enqueue("result", result_payload)
    server = StubServer()
    uplink = make_uplink(cfg, spool, server)
    await uplink.drain_once()
    await uplink.aclose()
    path, body, headers = server.requests[0]
    assert path == "/api/device/v1/results"
    assert headers["x-device-key"] == "test-key"
    assert body["queued_s"] >= 0


async def test_heartbeat_loop_posts_every_interval(cfg_factory):
    cfg = cfg_factory()
    spool = Spool(cfg.spool.path, capacity=10)
    server = StubServer()
    uplink = make_uplink(cfg, spool, server, heartbeat_fn=lambda: {"n": 1})
    task = asyncio.create_task(uplink.heartbeat_loop())
    await asyncio.sleep(0.55)  # ~5.5 heartbeat periods of 0.1 s
    task.cancel()
    await uplink.aclose()
    beats = [r for r in server.requests if r[0] == "/api/device/v1/heartbeat"]
    assert 4 <= len(beats) <= 7
    assert spool.depth() == 0  # heartbeats are never spooled

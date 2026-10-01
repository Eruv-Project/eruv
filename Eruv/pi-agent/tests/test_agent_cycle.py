"""Agent test cycle against the fake OTDR. Timings are scaled 100x (see conftest)."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime

import jsonschema
import pytest

from conftest import load_schema
from eruv_agent import protocol as p
from eruv_agent.agent import Agent
from fake_otdr import FIXTURE_EVENTS, FakeOtdr
from test_uplink import StubServer

C = 299_792_458
FS = 50_000_000
N32 = 1.468500018119812  # 1.4685 as the OTDR's float32 carries it


def validate(schema_name: str, message: dict) -> None:
    schema = load_schema(schema_name)
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER
    ).validate(message)
    stamp = message.get("measured_at") or message.get("occurred_at") or message.get("sent_at")
    assert datetime.fromisoformat(stamp.replace("Z", "+00:00")).utcoffset().total_seconds() == 0


async def eventually(fn, timeout: float = 1.0):
    """Poll until ``fn()`` is truthy: the fake reads commands asynchronously."""
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not (value := fn()) and loop.time() < end:
        await asyncio.sleep(0.01)
    return value


@contextlib.asynccontextmanager
async def running(fake: FakeOtdr, cfg_factory, server: StubServer | None = None, **sections):
    port = await fake.start()
    cfg = cfg_factory(port, **sections)
    agent = Agent(cfg, transport=(server or StubServer()).transport())
    otdr_task = asyncio.create_task(agent.otdr.run())
    try:
        yield agent
    finally:
        otdr_task.cancel()
        with contextlib.suppress(BaseException):
            await otdr_task
        await agent.aclose()
        await fake.stop()


async def test_one_cycle_spools_exactly_one_result_with_events_in_metres(cfg_factory):
    fake = FakeOtdr(["ok"], refresh_frames=1)
    async with running(fake, cfg_factory) as agent:
        await agent.run_cycle()
        pending = agent.spool.pending()
        wire = agent.uplink.wire_payload(pending[0]) if pending else None
        # every curve upload (refresh and final) was acked
        await eventually(lambda: len(fake.cmds(p.Cmd.CURVE_ACK)) >= 2)
        acks = len(fake.cmds(p.Cmd.CURVE_ACK))

    assert len(pending) == 1
    msg = pending[0]
    assert msg.kind == "result"
    result = msg.payload
    assert result["seq"] == 1
    assert "curve_b64" not in result
    got = [(e["index"], e["type"], e["distance_m"]) for e in result["events"]]
    want = [(e.index, ["start", "reflective", "non_reflective", "end"][e.type_code], e.index * C / (2 * N32 * FS)) for e in FIXTURE_EVENTS]
    assert [(i, t) for i, t, _ in got] == [(i, t) for i, t, _ in want]
    for (_, _, d_got), (_, _, d_want) in zip(got, want):
        assert d_got == pytest.approx(d_want, abs=1e-6)
    assert result["end_event_distance_m"] == pytest.approx(1494 * C / (2 * N32 * FS), abs=1e-6)
    assert result["params"]["sample_rate_hz"] == FS
    assert result["params"]["test_method"] == 1
    assert result["otdr"]["device"] == "GL3800M"
    assert acks == 2
    validate("result.schema.json", wire)


async def test_keepalive_when_idle_and_none_during_a_test(cfg_factory):
    # 30 s test (0.3 scaled), 90 s cadence (0.9): ~60 s idle between tests.
    fake = FakeOtdr(["ok"], test_duration_s=0.3)
    async with running(fake, cfg_factory) as agent:
        loop_task = asyncio.create_task(agent.cycle_loop())
        await asyncio.sleep(1.1)
        loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop_task

    starts = fake.cmds(p.Cmd.START_MEASURE)
    acks = fake.cmds(p.Cmd.CURVE_ACK)
    beats = fake.cmds(p.Cmd.HEARTBEAT)
    assert len(starts) >= 2
    assert not [b for b in beats if starts[0] <= b <= acks[0]], "keepalive sent during a running test"
    assert [b for b in beats if acks[0] < b < starts[1]], "no keepalive while idle between tests"


async def test_idle_session_gets_keepalive_within_25s(cfg_factory):
    fake = FakeOtdr()
    async with running(fake, cfg_factory) as agent:
        assert await agent.otdr.wait_connected(1)
        await asyncio.sleep(0.25)  # idle 25 s, scaled
        beats = fake.cmds(p.Cmd.HEARTBEAT)
    assert len(beats) >= 1


async def test_socket_closed_mid_test_spools_fault_then_recovers(cfg_factory):
    fake = FakeOtdr(["close", "ok"])
    async with running(fake, cfg_factory) as agent:
        await agent.run_cycle()
        await agent.run_cycle()
        pending = agent.spool.pending()
        fault_wire = agent.uplink.wire_payload(pending[0])

    assert [(m.seq, m.kind) for m in pending] == [(1, "fault"), (2, "result")]
    assert pending[0].payload["kind"] == "otdr_socket"
    assert fake.connections == 2
    validate("fault.schema.json", fault_wire)


async def test_timeout_spools_fault_and_cancels(cfg_factory):
    fake = FakeOtdr(["silent"])
    async with running(fake, cfg_factory) as agent:
        await agent.run_cycle()
        pending = agent.spool.pending()
        stops = await eventually(lambda: fake.cmds(p.Cmd.STOP_MEASURE))
    assert [m.payload["kind"] for m in pending] == ["otdr_timeout"]
    assert len(stops) == 1


async def test_error_status_spools_fault_with_code_and_cancels(cfg_factory):
    fake = FakeOtdr([("status", 19)])
    async with running(fake, cfg_factory) as agent:
        await agent.run_cycle()
        pending = agent.spool.pending()
        wire = agent.uplink.wire_payload(pending[0])
        stops = await eventually(lambda: fake.cmds(p.Cmd.STOP_MEASURE))
    assert wire["kind"] == "otdr_error_status"
    assert wire["status_code"] == 19
    assert len(stops) == 1
    validate("fault.schema.json", wire)


async def test_unreachable_otdr_spools_fault(cfg_factory):
    fake = FakeOtdr()
    port = await fake.start()
    await fake.stop()  # nothing listens on this port any more
    agent = Agent(cfg_factory(port, otdr={"connect_timeout_s": 0.2}), transport=StubServer().transport())
    otdr_task = asyncio.create_task(agent.otdr.run())
    try:
        await agent.run_cycle()
        pending = agent.spool.pending()
    finally:
        otdr_task.cancel()
        await agent.aclose()
    assert [m.payload["kind"] for m in pending] == ["otdr_unreachable"]


async def test_next_test_starts_90s_after_previous_start_not_end(cfg_factory):
    fake = FakeOtdr(["ok"], test_duration_s=0.4)  # a 40 s test, scaled
    async with running(fake, cfg_factory) as agent:
        loop_task = asyncio.create_task(agent.cycle_loop())
        await asyncio.sleep(2.0)
        loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop_task
    starts = fake.cmds(p.Cmd.START_MEASURE)
    assert len(starts) >= 2
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    for gap in gaps:
        assert gap == pytest.approx(0.9, abs=0.12), gaps  # not 0.4 + 0.9 = 1.3


async def test_scaled_run_delivers_results_and_heartbeats_to_stub_server(cfg_factory):
    fake = FakeOtdr(["ok"], test_duration_s=0.3)
    server = StubServer()
    port = await fake.start()
    agent = Agent(cfg_factory(port), transport=server.transport())
    task = asyncio.create_task(agent.run())
    await asyncio.sleep(2.0)  # ~200 s of agent time
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    await agent.aclose()
    await fake.stop()

    results = [b for path, b, _ in server.requests if path.endswith("/results")]
    beats = [b for path, b, _ in server.requests if path.endswith("/heartbeat")]
    assert 2 <= len(results) <= 3
    assert [r["seq"] for r in results] == list(range(1, len(results) + 1))
    assert 15 <= len(beats) <= 22
    for r in results:
        validate("result.schema.json", r)
    for b in beats:
        validate("heartbeat.schema.json", b)
    assert any(b["otdr_connected"] for b in beats)

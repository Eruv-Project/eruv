"""An asyncio TCP server that plays the OTDR module, replaying the U2 fixtures.

Each START_MEASURE consumes the next entry of ``script`` (the last entry repeats):

- ``"ok"``        status 0, then the full-result fixture after ``test_duration_s``
- ``"close"``     status 0, then the socket is closed mid-test
- ``"silent"``    status 0, then nothing (the agent must time out)
- ``("status", code)``  a non-zero status instead of starting the test

Every host command is recorded with a monotonic timestamp in ``received``.
"""

from __future__ import annotations

import asyncio
import time

from eruv_agent import protocol as p
from fixtures import frames as fx

# Fs = 50 MHz, n = 1.4685: one sample is about 2.0415 m.
FIXTURE_EVENTS = [
    fx.Event(index=0, type_code=0, reflect_loss=-45.1),
    fx.Event(index=490, type_code=1, reflect_loss=-52.0, insert_loss=0.4, atten_coef=0.2, total_loss=0.6),
    fx.Event(index=1494, type_code=3, reflect_loss=-30.5, atten_coef=0.35, total_loss=1.25),
]


def fixture_result() -> fx.FullResult:
    return fx.FullResult(events=list(FIXTURE_EVENTS))


class FakeOtdr:
    def __init__(
        self,
        script: list | None = None,
        *,
        test_duration_s: float = 0.05,
        result: fx.FullResult | None = None,
        refresh_frames: int = 0,
    ) -> None:
        self.script = list(script or ["ok"])
        self.test_duration_s = test_duration_s
        self.result = result or fixture_result()
        self.refresh_frames = refresh_frames
        self.received: list[tuple[float, int]] = []
        self.connections = 0
        self.tests_started = 0
        self._server: asyncio.base_events.Server | None = None
        self._tasks: set[asyncio.Task] = set()
        self.port = 0

    async def start(self) -> int:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        if self._server is not None:
            self._server.close()
            try:
                await asyncio.wait_for(self._server.wait_closed(), 1)
            except (asyncio.TimeoutError, Exception):
                pass

    def cmds(self, cmd: int) -> list[float]:
        return [t for t, c in self.received if c == cmd]

    def _next_behaviour(self):
        idx = min(self.tests_started, len(self.script) - 1)
        self.tests_started += 1
        return self.script[idx]

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            while True:
                frame = await p.read_frame(reader)
                self.received.append((time.monotonic(), frame.cmd))
                if frame.cmd == p.Cmd.HEARTBEAT:
                    writer.write(fx.heartbeat_reply_frame())
                elif frame.cmd == p.Cmd.READ_VERSION:
                    writer.write(fx.version_frame(0x0400, 2024, 3, 11, (10 << 16) | (20 << 8) | 30, b"GL3800M"))
                elif frame.cmd == p.Cmd.STOP_MEASURE:
                    writer.write(fx.status_frame(0))
                elif frame.cmd == p.Cmd.START_MEASURE:
                    behaviour = self._next_behaviour()
                    if isinstance(behaviour, tuple) and behaviour[0] == "status":
                        writer.write(fx.status_frame(behaviour[1]))
                    else:
                        writer.write(fx.status_frame(0))
                        await writer.drain()
                        if behaviour == "close":
                            await asyncio.sleep(self.test_duration_s / 2)
                            writer.close()
                            return
                        if behaviour == "ok":
                            for _ in range(self.refresh_frames):
                                writer.write(fx.refresh_frame([25000, 20000, 1000]))
                            await asyncio.sleep(self.test_duration_s)
                            writer.write(self.result.frame())
                        # "silent": say nothing more
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, asyncio.CancelledError):
            pass
        finally:
            self._tasks.discard(task)
            writer.close()

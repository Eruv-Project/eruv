"""One persistent TCP session to the OTDR module (R1, R6, R7).

``run()`` keeps the session up: it connects, reconnects with exponential
backoff capped at ``reconnect_max_s``, reads every frame, acks every curve
upload (0x90000000 and 0x90000001) with 0x10000004, and sends the 0x10000003
keepalive whenever the link has been idle for ``keepalive_idle_s`` and no test
is running. The module resets a session after 60 s without host traffic; a
30 s test plus processing stays well under that, so no keepalive is sent while
a test runs.

``run_test()`` starts one test and returns the decoded final data.
"""

from __future__ import annotations

import asyncio
import logging

from eruv_agent import protocol as p
from eruv_agent.config import OtdrConfig

log = logging.getLogger(__name__)


class OtdrTimeoutError(p.ProtocolError):
    """No final data within the measurement time plus the margin."""


class OtdrDisconnectedError(ConnectionError):
    """The socket failed or closed."""


_CLOSED = object()  # queued by the reader when the connection ends


class OtdrClient:
    def __init__(self, cfg: OtdrConfig) -> None:
        self.cfg = cfg
        self.version: p.VersionInfo | None = None
        self.last_error: str | None = None
        self.test_running = False
        self._writer: asyncio.StreamWriter | None = None
        self._frames: asyncio.Queue = asyncio.Queue()
        self._connected = asyncio.Event()
        self._last_tx = 0.0
        self._packet_id = 0

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    async def wait_connected(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self._connected.wait(), timeout)
        except asyncio.TimeoutError:
            return False
        return True

    # ------------------------------------------------------------ session

    async def run(self) -> None:
        delay = self.cfg.reconnect_initial_s
        while True:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self.cfg.host, self.cfg.port),
                    self.cfg.connect_timeout_s,
                )
            except (OSError, asyncio.TimeoutError) as exc:
                self.last_error = f"connect to {self.cfg.host}:{self.cfg.port} failed: {exc!r}"
                log.warning("otdr: %s; retry in %.1f s", self.last_error, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.cfg.reconnect_max_s)
                continue

            delay = self.cfg.reconnect_initial_s
            log.info("otdr: connected to %s:%d", self.cfg.host, self.cfg.port)
            self._writer = writer
            self._frames = asyncio.Queue()
            self._connected.set()
            keepalive = asyncio.create_task(self._keepalive())
            try:
                await self._send(p.encode_version_query)
                await self._read_loop(reader)
            except (OSError, asyncio.IncompleteReadError, p.FramingError) as exc:
                self.last_error = f"socket: {exc!r}"
                log.warning("otdr: connection lost: %s", self.last_error)
            finally:
                keepalive.cancel()
                self._connected.clear()
                self._writer = None
                self._frames.put_nowait(_CLOSED)
                writer.close()
            await asyncio.sleep(delay)
            delay = min(delay * 2, self.cfg.reconnect_max_s)

    async def _read_loop(self, reader: asyncio.StreamReader) -> None:
        while True:
            frame = await p.read_frame(reader)
            try:
                msg = p.decode(frame)
            except p.DecodeError as exc:
                log.warning("otdr: undecodable frame 0x%08x: %s", frame.cmd, exc)
                self._frames.put_nowait(exc)
                continue
            if isinstance(msg, (p.FullResult, p.RefreshCurve)):
                await self._send(p.encode_curve_ack)
            if isinstance(msg, p.VersionInfo):
                self.version = msg
                log.info("otdr: firmware %s, device %s", msg.firmware, msg.device)
                continue
            if isinstance(msg, p.HeartbeatReply):
                continue
            self._frames.put_nowait(msg)

    async def _keepalive(self) -> None:
        loop = asyncio.get_running_loop()
        tick = min(1.0, self.cfg.keepalive_idle_s / 4)
        while True:
            await asyncio.sleep(tick)
            if not self.test_running and loop.time() - self._last_tx >= self.cfg.keepalive_idle_s:
                try:
                    await self._send(p.encode_heartbeat)
                except OSError:
                    return  # the read loop will notice and reconnect

    async def _send(self, encode) -> None:
        writer = self._writer
        if writer is None:
            raise OtdrDisconnectedError("not connected")
        self._packet_id = (self._packet_id + 1) & 0xFFFFFFFF
        writer.write(encode(packet_id=self._packet_id))
        await writer.drain()
        self._last_tx = asyncio.get_running_loop().time()

    # ------------------------------------------------------------ tests

    async def run_test(self, params: p.StartMeasureParams) -> p.FullResult:
        """Start one test and wait for 0x90000000.

        Raises OtdrTimeoutError, OtdrDisconnectedError, OtdrStatusError (incl.
        OtdrBusyError) or DecodeError.
        """
        if not self.connected:
            raise OtdrDisconnectedError(self.last_error or "not connected")
        queue = self._frames
        while not queue.empty():  # drop leftovers from an earlier test
            stale = queue.get_nowait()
            if stale is _CLOSED:
                raise OtdrDisconnectedError(self.last_error or "connection closed")

        loop = asyncio.get_running_loop()
        deadline = loop.time() + params.measure_time_ms / 1000 + self.cfg.result_timeout_margin_s
        self.test_running = True
        try:
            await self._send(lambda packet_id: p.encode_start_measure(params, packet_id))
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise OtdrTimeoutError(
                        f"no final data within {params.measure_time_ms} ms + "
                        f"{self.cfg.result_timeout_margin_s} s"
                    )
                try:
                    msg = await asyncio.wait_for(queue.get(), remaining)
                except asyncio.TimeoutError:
                    continue  # re-checks the deadline and raises
                if msg is _CLOSED:
                    raise OtdrDisconnectedError(self.last_error or "connection closed during test")
                if isinstance(msg, Exception):
                    raise msg
                if isinstance(msg, p.StatusResponse):
                    msg.raise_for_status()
                elif isinstance(msg, p.FullResult):
                    return msg
                # RefreshCurve (already acked), TestStatus: keep waiting
        except OSError as exc:
            raise OtdrDisconnectedError(repr(exc)) from exc
        finally:
            self.test_running = False

    async def cancel(self) -> None:
        """Send 0x10000001 (cancel) when the socket is still up."""
        if not self.connected:
            return
        try:
            await self._send(lambda packet_id: p.encode_stop_measure(p.StopMode.CANCEL, packet_id))
        except (OSError, OtdrDisconnectedError) as exc:
            log.warning("otdr: cancel not sent: %s", exc)

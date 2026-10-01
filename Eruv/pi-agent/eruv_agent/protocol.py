"""Codec for the OTDR module's Ethernet protocol (manual v4, Appendix 1, ch. 3).

Socket-free: it builds host command frames and decodes module frames. The
network loop feeds received bytes to ``FrameReader`` (or awaits ``read_frame``)
and passes each ``Frame`` to ``decode``.

Wire format, all little-endian (the manual forbids network byte order)::

    char     sync[16]      "GLinkOtdr-3800M\\0"
    uint32   TotalLength   16 + 10*4 + n
    uint32   Rev, FrameType, Src, Dst, PacketID, RSVD1
    uint32   cmd
    uint32   datalen       n
    uint8    data[n]
    uint32   RSVD2         0xffffeeee when unused
"""

from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass, field
from enum import IntEnum

SYNC = b"GLinkOtdr-3800M\x00"
HEADER_SIZE = 44  # sync + 7 x uint32
FRAME_OVERHEAD = HEADER_SIZE + 12  # + cmd, datalen, RSVD2 = 16 + 10*4
RSVD_VALUE = 0xFFFFEEEE
REV_ID = 0
FRAMETYPE_HOST2TARGET = 0

SPEED_OF_LIGHT_M_S = 299_792_458
NOT_COMPUTED = 8192.0  # reserved float: value not computed / not applicable

_HEADER = struct.Struct("<16s7I")
_U32 = struct.Struct("<I")
_CONDITIONS = struct.Struct("<5I6f2I")  # 52 bytes
_EVENT = struct.Struct("<IIffff")  # 24 bytes


class Cmd(IntEnum):
    # host -> module
    START_MEASURE = 0x10000000
    STOP_MEASURE = 0x10000001
    HEARTBEAT = 0x10000003
    CURVE_ACK = 0x10000004  # "curve reception response" / NetworkIdle
    QUERY_STATUS = 0x10000005
    READ_VERSION = 0x11000000
    # module -> host
    UPLOAD_ALL_DATA = 0x90000000
    UPLOAD_REFRESH_DATA = 0x90000001
    HEARTBEAT_REPLY = 0x90000002
    TEST_STATUS = 0x90000005
    VERSION = 0x91000000
    STATUS_CODE = 0xA0000000


class StatusCode(IntEnum):
    OK = 0
    FRAME_SYNC_ERROR = 1
    REV_ERROR = 2
    FRAME_TYPE_ERROR = 3
    CMD_ID_ERROR = 4
    PACKET_LENGTH_ERROR = 5
    RANGE_OR_PULSE_INVALID = 16
    GROUP_INDEX_INVALID = 17
    NON_REFLECT_THRESHOLD_INVALID = 18
    OTDR_BUSY = 19  # "invalid test request": a test is already running
    IP_ERROR = 20
    UPGRADE_FILE_ERROR = 100
    UPGRADE_STARTED = 101
    UPGRADE_FAILED = 102
    UPGRADE_DONE = 103


class StopMode(IntEnum):
    CANCEL = 1  # stop and discard data
    TERMINATE = 2  # stop and process data acquired so far


EVENT_TYPES = {0: "start", 1: "reflective", 2: "non_reflective", 3: "end"}
END_EVENT_CODE = 3


# ---------------------------------------------------------------- errors


class ProtocolError(Exception):
    """Base class for every codec error."""


class FramingError(ProtocolError):
    """The byte stream is not a valid frame (bad sync or inconsistent lengths)."""


class DecodeError(ProtocolError):
    """A well-framed payload does not match the layout for its command."""


class OtdrStatusError(ProtocolError):
    """The module answered with a non-zero status code."""

    def __init__(self, code: int) -> None:
        self.code = code
        try:
            name = StatusCode(code).name
        except ValueError:
            name = "UNKNOWN"
        super().__init__(f"OTDR status code {code} ({name})")


class OtdrBusyError(OtdrStatusError):
    """Status 19: the module rejected a test request because one is running."""


# ---------------------------------------------------------------- frames


@dataclass(frozen=True)
class Frame:
    cmd: int
    data: bytes
    packet_id: int
    total_length: int


def _parse_header(header: bytes) -> tuple[int, int]:
    """Validate a 44-byte header; return (TotalLength, PacketID)."""
    sync, total, _rev, _ftype, _src, _dst, packet_id, _rsvd = _HEADER.unpack(header)
    if sync != SYNC:
        raise FramingError(f"bad frame sync {sync!r}")
    if total < FRAME_OVERHEAD:
        raise FramingError(f"TotalLength {total} below minimum {FRAME_OVERHEAD}")
    return total, packet_id


def _parse_body(body: bytes, total: int, packet_id: int) -> Frame:
    """Split the bytes after the header: cmd, datalen, data, RSVD2."""
    cmd, datalen = struct.unpack_from("<II", body, 0)
    if datalen != total - FRAME_OVERHEAD:
        raise FramingError(
            f"datalen {datalen} disagrees with TotalLength {total} "
            f"(expected {total - FRAME_OVERHEAD})"
        )
    return Frame(cmd=cmd, data=bytes(body[8 : 8 + datalen]), packet_id=packet_id, total_length=total)


class FrameReader:
    """Incremental frame reassembly; feed it TCP chunks of any size."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[Frame]:
        self._buf += chunk
        frames: list[Frame] = []
        while len(self._buf) >= HEADER_SIZE:
            total, packet_id = _parse_header(bytes(self._buf[:HEADER_SIZE]))
            if len(self._buf) < total:
                break
            frames.append(_parse_body(bytes(self._buf[HEADER_SIZE:total]), total, packet_id))
            del self._buf[:total]
        return frames


async def read_frame(reader: asyncio.StreamReader) -> Frame:
    """Read exactly one frame from an asyncio stream.

    Raises ``asyncio.IncompleteReadError`` if the stream ends mid-frame.
    """
    header = await reader.readexactly(HEADER_SIZE)
    total, packet_id = _parse_header(header)
    body = await reader.readexactly(total - HEADER_SIZE)
    return _parse_body(body, total, packet_id)


# ---------------------------------------------------------------- encoding


def encode_frame(cmd: int, data: bytes = b"", packet_id: int = 0) -> bytes:
    """Build a host -> module frame. Unused reserved words are 0xffffeeee."""
    total = FRAME_OVERHEAD + len(data)
    header = _HEADER.pack(
        SYNC, total, REV_ID, FRAMETYPE_HOST2TARGET, 0, 0, packet_id, RSVD_VALUE
    )
    return header + struct.pack("<II", cmd, len(data)) + data + _U32.pack(RSVD_VALUE)


@dataclass
class StartMeasureParams:
    """Fields of the manual's ``start_measure_t`` (3.6.1)."""

    wavelength_nm: int
    range_m: int
    pulse_width_ns: int
    measure_time_ms: int
    group_index: float
    end_threshold_db: float
    non_reflect_threshold_db: float  # 0 = automatic
    otdr_mode: int = 1  # 1 averaging, 2 real-time
    enable_refresh: bool = False
    refresh_period_ms: int = 1000  # ignored in averaging mode with refresh off


def encode_start_measure(params: StartMeasureParams, packet_id: int = 0) -> bytes:
    data = struct.pack(
        "<5I4I3f",
        # Ctrl
        params.otdr_mode,
        0,  # OtdrOptMode (reserved)
        0,  # RSVD (the C reference client sets 0)
        1 if params.enable_refresh else 0,
        params.refresh_period_ms,
        # State
        params.wavelength_nm,
        params.range_m,
        params.pulse_width_ns,
        params.measure_time_ms,
        params.group_index,
        params.end_threshold_db,
        params.non_reflect_threshold_db,
    )
    return encode_frame(Cmd.START_MEASURE, data, packet_id)


def encode_stop_measure(mode: StopMode = StopMode.CANCEL, packet_id: int = 0) -> bytes:
    return encode_frame(Cmd.STOP_MEASURE, _U32.pack(mode), packet_id)


def encode_heartbeat(packet_id: int = 0) -> bytes:
    return encode_frame(Cmd.HEARTBEAT, b"", packet_id)


def encode_curve_ack(packet_id: int = 0) -> bytes:
    return encode_frame(Cmd.CURVE_ACK, b"", packet_id)


def encode_status_query(packet_id: int = 0) -> bytes:
    return encode_frame(Cmd.QUERY_STATUS, b"", packet_id)


def encode_version_query(packet_id: int = 0) -> bytes:
    return encode_frame(Cmd.READ_VERSION, b"", packet_id)


# ---------------------------------------------------------------- decoded messages


def event_distance_m(index: int, group_index: float, sample_rate_hz: int) -> float:
    """x = m * c / (2 * n * Fs)."""
    return index * SPEED_OF_LIGHT_M_S / (2.0 * group_index * sample_rate_hz)


def curve_db(raw: bytes) -> list[float]:
    """Convert packed uint16 curve points to dB: v / 1000 - 5."""
    count = len(raw) // 2
    return [v / 1000.0 - 5.0 for v in struct.unpack(f"<{count}H", raw)]


def _opt(value: float) -> float | None:
    return None if value == NOT_COMPUTED else value


@dataclass(frozen=True)
class TestConditions:
    __test__ = False  # not a pytest class

    sample_rate_hz: int
    range_m: int
    pulse_width_ns: int
    wavelength_nm: int
    measure_time_ms: int
    group_index: float
    fiber_length_m: float | None
    link_loss_db: float | None
    link_attenuation_db_per_km: float | None
    non_reflect_threshold_db: float | None
    end_threshold_db: float | None
    test_mode: int  # 1 averaging, 2 real-time
    test_method: int  # 0 automatic, 1 manual


@dataclass(frozen=True)
class OtdrEvent:
    """Field names match the ``events`` items of contracts/result.schema.json."""

    index: int
    distance_m: float
    type_code: int
    type: str
    reflect_loss_db: float | None
    insert_loss_db: float | None
    atten_coef_db_per_km: float | None
    total_loss_db: float | None


@dataclass(frozen=True)
class FullResult:
    """0x90000000: the final data of a test."""

    conditions: TestConditions
    data_num: int
    curve_raw: bytes = field(repr=False)
    events: list[OtdrEvent]

    @property
    def end_event_distance_m(self) -> float | None:
        ends = [e for e in self.events if e.type_code == END_EVENT_CODE]
        return ends[-1].distance_m if ends else None

    def curve_db(self) -> list[float]:
        return curve_db(self.curve_raw)


@dataclass(frozen=True)
class RefreshCurve:
    """0x90000001: an intermediate curve without conditions or events."""

    data_num: int
    curve_raw: bytes = field(repr=False)

    def curve_db(self) -> list[float]:
        return curve_db(self.curve_raw)


@dataclass(frozen=True)
class HeartbeatReply:
    value: int


@dataclass(frozen=True)
class TestStatus:
    __test__ = False  # not a pytest class

    mode: int  # 0 idle, 1 averaging, 2 real-time
    wavelength_nm: int
    range_m: int
    pulse_width_ns: int
    measure_time_ms: int
    elapsed_ms: int

    @property
    def busy(self) -> bool:
        return self.mode != 0


@dataclass(frozen=True)
class VersionInfo:
    major: int
    minor: int
    year: int
    month: int
    day: int
    hour: int
    minute: int
    second: int
    device: str

    @property
    def firmware(self) -> str:
        return (
            f"{self.major}.{self.minor} "
            f"({self.year:04d}-{self.month:02d}-{self.day:02d} "
            f"{self.hour:02d}:{self.minute:02d}:{self.second:02d})"
        )


@dataclass(frozen=True)
class StatusResponse:
    """0xA0000000: the module's status code for the last command."""

    code: int

    @property
    def ok(self) -> bool:
        return self.code == StatusCode.OK

    def raise_for_status(self) -> None:
        if self.code == StatusCode.OTDR_BUSY:
            raise OtdrBusyError(self.code)
        if self.code != StatusCode.OK:
            raise OtdrStatusError(self.code)


Message = FullResult | RefreshCurve | HeartbeatReply | TestStatus | VersionInfo | StatusResponse


# ---------------------------------------------------------------- decoding


def _expect_len(data: bytes, expected: int, what: str) -> None:
    if len(data) != expected:
        raise DecodeError(f"{what}: payload is {len(data)} bytes, expected {expected}")


def _read_curve(data: bytes, offset: int, what: str) -> tuple[int, bytes, int]:
    """Read uint32 DataNum + DataNum x uint16; return (count, raw, next offset)."""
    if len(data) < offset + 4:
        raise DecodeError(f"{what}: truncated before DataNum")
    (count,) = _U32.unpack_from(data, offset)
    start = offset + 4
    end = start + 2 * count
    if len(data) < end:
        raise DecodeError(f"{what}: DataNum {count} exceeds payload")
    return count, data[start:end], end


def _decode_full_result(data: bytes) -> FullResult:
    what = "full result"
    if len(data) < _CONDITIONS.size:
        raise DecodeError(f"{what}: truncated condition block")
    (
        fs,
        range_m,
        pulse_ns,
        lambda_nm,
        time_ms,
        n,
        fiber_len,
        fiber_loss,
        atten,
        nr_thr,
        end_thr,
        otdr_mode,
        measure_mode,
    ) = _CONDITIONS.unpack_from(data, 0)
    if fs == 0 or n <= 0:
        raise DecodeError(f"{what}: sample rate {fs} / group index {n} cannot place events")
    conditions = TestConditions(
        sample_rate_hz=fs,
        range_m=range_m,
        pulse_width_ns=pulse_ns,
        wavelength_nm=lambda_nm,
        measure_time_ms=time_ms,
        group_index=n,
        fiber_length_m=_opt(fiber_len),
        link_loss_db=_opt(fiber_loss),
        link_attenuation_db_per_km=_opt(atten),
        non_reflect_threshold_db=_opt(nr_thr),
        end_threshold_db=_opt(end_thr),
        test_mode=otdr_mode,
        test_method=measure_mode,
    )

    data_num, curve_raw, offset = _read_curve(data, _CONDITIONS.size, what)

    if len(data) < offset + 4:
        raise DecodeError(f"{what}: truncated before EventNum")
    (event_num,) = _U32.unpack_from(data, offset)
    offset += 4
    _expect_len(data, offset + _EVENT.size * event_num, what)

    events: list[OtdrEvent] = []
    for i in range(event_num):
        index, type_code, reflect, insert, coef, total = _EVENT.unpack_from(
            data, offset + i * _EVENT.size
        )
        events.append(
            OtdrEvent(
                index=index,
                distance_m=event_distance_m(index, n, fs),
                type_code=type_code,
                type=EVENT_TYPES.get(type_code, "unknown"),
                reflect_loss_db=_opt(reflect),
                insert_loss_db=_opt(insert),
                atten_coef_db_per_km=_opt(coef),
                total_loss_db=_opt(total),
            )
        )
    return FullResult(conditions=conditions, data_num=data_num, curve_raw=curve_raw, events=events)


def _decode_refresh(data: bytes) -> RefreshCurve:
    count, raw, end = _read_curve(data, 0, "refresh curve")
    _expect_len(data, end, "refresh curve")
    return RefreshCurve(data_num=count, curve_raw=raw)


def _decode_version(data: bytes) -> VersionInfo:
    _expect_len(data, 28, "version")
    version, year, month, day, packed_time, device = struct.unpack("<4HI16s", data)
    return VersionInfo(
        major=version >> 8,
        minor=version & 0xFF,
        year=year,
        month=month,
        day=day,
        hour=packed_time >> 16,
        minute=(packed_time >> 8) & 0xFF,
        second=packed_time & 0xFF,
        device=device.split(b"\x00", 1)[0].decode("ascii", errors="replace"),
    )


def decode(frame: Frame) -> Message:
    """Decode a module -> host frame into a typed message.

    Raises ``DecodeError`` for unknown commands or payloads that do not match
    the manual's layout. A status frame is returned, not raised; call
    ``StatusResponse.raise_for_status()`` to turn a non-zero code into an error.
    """
    data = frame.data
    if frame.cmd == Cmd.UPLOAD_ALL_DATA:
        return _decode_full_result(data)
    if frame.cmd == Cmd.UPLOAD_REFRESH_DATA:
        return _decode_refresh(data)
    if frame.cmd == Cmd.STATUS_CODE:
        _expect_len(data, 4, "status code")
        return StatusResponse(code=_U32.unpack(data)[0])
    if frame.cmd == Cmd.HEARTBEAT_REPLY:
        _expect_len(data, 4, "heartbeat reply")
        return HeartbeatReply(value=_U32.unpack(data)[0])
    if frame.cmd == Cmd.TEST_STATUS:
        _expect_len(data, 24, "test status")
        return TestStatus(*struct.unpack("<6I", data))
    if frame.cmd == Cmd.VERSION:
        return _decode_version(data)
    raise DecodeError(f"unknown command code 0x{frame.cmd:08x}")

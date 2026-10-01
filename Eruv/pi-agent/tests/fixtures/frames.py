"""Build OTDR wire frames by hand, straight from the manual's layouts.

This module deliberately does not import ``eruv_agent.protocol``: fixtures are
the independent reference the codec is tested against. Every layout below cites
the manual section (Appendix 1, chapter 3 and the chapter 5.3 C header).

Frame (3.5): 16-byte "GLinkOtdr-3800M\\0", then uint32 TotalLength, Rev,
FrameType, Src, Dst, PacketID, RSVD1 (44 bytes), then uint32 cmd, uint32
datalen, data (n bytes), uint32 RSVD2. TotalLength = 16 + 10*4 + n.
All little-endian.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

SYNC = b"GLinkOtdr-3800M\x00"
RSVD = 0xFFFFEEEE
NOT_COMPUTED = 8192.0


def frame(
    cmd: int,
    data: bytes = b"",
    *,
    sync: bytes = SYNC,
    frame_type: int = 1,
    packet_id: int = 0,
) -> bytes:
    """A module-to-host frame as the OTDR would send it."""
    total = 16 + 10 * 4 + len(data)
    header = sync + struct.pack(
        "<7I", total, 0, frame_type, 0, 0, packet_id, RSVD
    )
    return header + struct.pack("<II", cmd, len(data)) + data + struct.pack("<I", RSVD)


def status_frame(code: int) -> bytes:
    """0xA0000000: one uint32 status code (otdr_state_t)."""
    return frame(0xA0000000, struct.pack("<I", code))


@dataclass
class Event:
    """One 24-byte event point (3.6.10 part c)."""

    index: int
    type_code: int
    reflect_loss: float = NOT_COMPUTED
    insert_loss: float = NOT_COMPUTED
    atten_coef: float = NOT_COMPUTED
    total_loss: float = NOT_COMPUTED

    def pack(self) -> bytes:
        return struct.pack(
            "<IIffff",
            self.index,
            self.type_code,
            self.reflect_loss,
            self.insert_loss,
            self.atten_coef,
            self.total_loss,
        )


@dataclass
class FullResult:
    """0x90000000 payload (3.6.10): conditions, curve, events."""

    sample_rate_hz: int = 50_000_000
    range_m: int = 60_000
    pulse_width_ns: int = 640
    wavelength_nm: int = 1550
    measure_time_ms: int = 30_000
    n: float = 1.4685
    fiber_length: float = 3050.0
    fiber_loss: float = 1.25
    fiber_atten_coef: float = 0.35
    non_reflect_threshold: float = 0.0
    end_threshold: float = 5.0
    otdr_mode: int = 1
    measure_mode: int = 1
    curve: list[int] = field(default_factory=lambda: [25000, 24000, 5000, 0])
    events: list[Event] = field(default_factory=list)

    def data(self) -> bytes:
        conditions = struct.pack(
            "<5I6f2I",
            self.sample_rate_hz,
            self.range_m,
            self.pulse_width_ns,
            self.wavelength_nm,
            self.measure_time_ms,
            self.n,
            self.fiber_length,
            self.fiber_loss,
            self.fiber_atten_coef,
            self.non_reflect_threshold,
            self.end_threshold,
            self.otdr_mode,
            self.measure_mode,
        )
        assert len(conditions) == 52
        curve = struct.pack("<I", len(self.curve)) + struct.pack(
            f"<{len(self.curve)}H", *self.curve
        )
        events = struct.pack("<I", len(self.events)) + b"".join(
            e.pack() for e in self.events
        )
        return conditions + curve + events

    def frame(self) -> bytes:
        return frame(0x90000000, self.data())


def refresh_frame(curve: list[int]) -> bytes:
    """0x90000001: uint32 DataNum then DataNum x uint16 (3.6.11)."""
    return frame(
        0x90000001,
        struct.pack("<I", len(curve)) + struct.pack(f"<{len(curve)}H", *curve),
    )


def heartbeat_reply_frame(value: int = 0) -> bytes:
    """0x90000002: one reserved uint32 (3.6.12)."""
    return frame(0x90000002, struct.pack("<I", value))


def otdr_status_frame(
    mode: int, wavelength: int, range_m: int, pulse: int, duration: int, elapsed: int
) -> bytes:
    """0x90000005: six uint32 fields (3.6.13)."""
    return frame(
        0x90000005,
        struct.pack("<6I", mode, wavelength, range_m, pulse, duration, elapsed),
    )


def version_frame(
    version: int, year: int, month: int, day: int, time_packed: int, device: bytes
) -> bytes:
    """0x91000000: uint16 version/year/month/day, uint32 time, String[16] (3.6.14)."""
    return frame(
        0x91000000,
        struct.pack("<4HI", version, year, month, day, time_packed)
        + device.ljust(16, b"\x00"),
    )

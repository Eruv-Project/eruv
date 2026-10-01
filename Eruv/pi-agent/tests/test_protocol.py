"""OTDR codec tests. Expected values come from the manual's layouts (see
tests/fixtures/frames.py) or are written out byte by byte here, never from the
code under test. No network access is used."""

from __future__ import annotations

import asyncio
import struct

import pytest

from eruv_agent import protocol as p
from fixtures import frames as fx

SYNC = b"GLinkOtdr-3800M\x00"
RSVD = struct.pack("<I", 0xFFFFEEEE)


def u32(v: int) -> bytes:
    return struct.pack("<I", v)


def default_start_params() -> p.StartMeasureParams:
    return p.StartMeasureParams(
        wavelength_nm=1550,
        range_m=60000,
        pulse_width_ns=640,
        measure_time_ms=30000,
        group_index=1.4685,
        end_threshold_db=5.0,
        non_reflect_threshold_db=0.0,
    )


def decode_one(raw: bytes) -> object:
    reader = p.FrameReader()
    frames = reader.feed(raw)
    assert len(frames) == 1
    return p.decode(frames[0])


# ---------------------------------------------------------------- encoding


def test_start_command_default_config_matches_manual_layout() -> None:
    raw = p.encode_start_measure(default_start_params(), packet_id=7)

    # start_measure_t: Ctrl (5 x uint32) + State (4 x uint32, 3 x float32) = 48
    assert len(raw) == 16 + 10 * 4 + 48 == 104
    assert raw[0:16] == SYNC
    assert raw[16:20] == u32(104)  # TotalLength
    assert raw[20:24] == u32(0)  # Rev (REV_ID 0)
    assert raw[24:28] == u32(0)  # FrameType: host -> module
    assert raw[28:32] == u32(0)  # Src
    assert raw[32:36] == u32(0)  # Dst
    assert raw[36:40] == u32(7)  # PacketID
    assert raw[40:44] == RSVD  # RSVD1
    assert raw[44:48] == u32(0x10000000)  # cmd
    assert raw[48:52] == u32(48)  # datalen
    # Ctrl
    assert raw[52:56] == u32(1)  # OtdrMode: averaging
    assert raw[56:60] == u32(0)  # OtdrOptMode
    assert raw[60:64] == u32(0)  # RSVD inside Ctrl (C client sets 0)
    assert raw[64:68] == u32(0)  # EnableRefresh: disabled
    assert raw[68:72] == u32(1000)  # RefreshPeriod_ms (ignored when disabled)
    # State
    assert raw[72:76] == u32(1550)  # Lambda_nm
    assert raw[76:80] == u32(60000)  # MeasureLength_m
    assert raw[80:84] == u32(640)  # PulseWidth_ns
    assert raw[84:88] == u32(30000)  # MeasureTime_ms
    # The manual's own example: 1.4685 as float32 is sent as CF F7 BB 3F.
    assert raw[88:92] == bytes([0xCF, 0xF7, 0xBB, 0x3F])
    assert raw[92:96] == struct.pack("<f", 5.0)  # EndThreshold
    assert raw[96:100] == struct.pack("<f", 0.0)  # NonReflectThreshold
    assert raw[100:104] == RSVD  # RSVD2


def test_start_command_with_refresh_enabled_sets_flag_and_period() -> None:
    params = default_start_params()
    params.enable_refresh = True
    params.refresh_period_ms = 2000
    raw = p.encode_start_measure(params)
    assert raw[64:68] == u32(1)
    assert raw[68:72] == u32(2000)


@pytest.mark.parametrize(
    ("encode", "cmd"),
    [
        (p.encode_heartbeat, 0x10000003),
        (p.encode_curve_ack, 0x10000004),
        (p.encode_status_query, 0x10000005),
        (p.encode_version_query, 0x11000000),
    ],
)
def test_empty_commands_have_no_data(encode, cmd: int) -> None:
    # Matches the C client's NetworkIdle: TotalLength = header + 12, len = 0.
    expected = (
        SYNC
        + struct.pack("<7I", 56, 0, 0, 0, 0, 3, 0xFFFFEEEE)
        + u32(cmd)
        + u32(0)
        + RSVD
    )
    assert encode(packet_id=3) == expected


@pytest.mark.parametrize(("mode", "value"), [(p.StopMode.CANCEL, 1), (p.StopMode.TERMINATE, 2)])
def test_cancel_command_carries_control_mode(mode: p.StopMode, value: int) -> None:
    expected = (
        SYNC
        + struct.pack("<7I", 60, 0, 0, 0, 0, 0, 0xFFFFEEEE)
        + u32(0x10000001)
        + u32(4)
        + u32(value)
        + RSVD
    )
    assert p.encode_stop_measure(mode) == expected


# ---------------------------------------------------------------- full result


def three_event_result() -> fx.FullResult:
    return fx.FullResult(
        events=[
            fx.Event(index=0, type_code=0, reflect_loss=-45.5),
            fx.Event(
                index=1000,
                type_code=2,
                insert_loss=0.25,
                atten_coef=0.34,
                total_loss=0.6,
            ),
            fx.Event(
                index=1494,
                type_code=3,
                reflect_loss=-14.0,
                atten_coef=0.36,
                total_loss=1.25,
            ),
        ]
    )


def test_full_result_with_three_events_decodes_three_events() -> None:
    result = decode_one(three_event_result().frame())

    assert isinstance(result, p.FullResult)
    assert len(result.events) == 3
    assert [e.type for e in result.events] == ["start", "non_reflective", "end"]
    assert [e.type_code for e in result.events] == [0, 2, 3]
    assert [e.index for e in result.events] == [0, 1000, 1494]

    # x = m * c / (2 * n * Fs) with Fs = 50 MHz, n = 1.4685
    assert result.events[1].distance_m == pytest.approx(2041.49, abs=0.01)
    assert result.events[1].insert_loss_db == pytest.approx(0.25)
    assert result.events[1].atten_coef_db_per_km == pytest.approx(0.34)
    assert result.events[1].total_loss_db == pytest.approx(0.6)
    assert result.events[0].reflect_loss_db == pytest.approx(-45.5)
    assert result.end_event_distance_m == pytest.approx(
        1494 * 299792458 / (2 * 1.4685 * 50e6), abs=0.01
    )

    c = result.conditions
    assert c.sample_rate_hz == 50_000_000
    assert c.range_m == 60000
    assert c.pulse_width_ns == 640
    assert c.wavelength_nm == 1550
    assert c.measure_time_ms == 30000
    assert c.group_index == pytest.approx(1.4685)
    assert c.fiber_length_m == pytest.approx(3050.0)
    assert c.link_loss_db == pytest.approx(1.25)
    assert c.link_attenuation_db_per_km == pytest.approx(0.35)
    assert c.non_reflect_threshold_db == pytest.approx(0.0)
    assert c.end_threshold_db == pytest.approx(5.0)
    assert c.test_mode == 1
    assert c.test_method == 1


def test_full_result_with_manual_60km_datanum_finds_events_at_right_offset() -> None:
    data_num = 29392  # the manual's 60 km example
    events = [
        fx.Event(index=0, type_code=0),
        fx.Event(index=12345, type_code=1, reflect_loss=-40.0, insert_loss=0.5),
        fx.Event(index=29000, type_code=3),
    ]
    fixture = fx.FullResult(curve=[(i * 7) % 60000 for i in range(data_num)], events=events)
    raw = fixture.frame()
    assert len(raw) == 2 * data_num + 24 * len(events) + 116

    reader = p.FrameReader()
    [frame] = reader.feed(raw)
    assert frame.total_length == 2 * data_num + 24 * len(events) + 116
    result = p.decode(frame)

    assert result.data_num == data_num
    assert [(e.index, e.type) for e in result.events] == [
        (0, "start"),
        (12345, "reflective"),
        (29000, "end"),
    ]
    assert result.events[1].reflect_loss_db == pytest.approx(-40.0)
    assert result.events[1].insert_loss_db == pytest.approx(0.5)


def test_reserved_8192_decodes_to_none() -> None:
    fixture = fx.FullResult(
        fiber_loss=8192.0,
        events=[fx.Event(index=10, type_code=2, insert_loss=8192.0, total_loss=0.4)],
    )
    result = decode_one(fixture.frame())

    event = result.events[0]
    assert event.insert_loss_db is None
    assert event.reflect_loss_db is None  # fixture default is 8192.0 too
    assert event.atten_coef_db_per_km is None
    assert event.total_loss_db == pytest.approx(0.4)
    assert result.conditions.link_loss_db is None


def test_unknown_event_type_code_maps_to_unknown() -> None:
    fixture = fx.FullResult(events=[fx.Event(index=5, type_code=9)])
    result = decode_one(fixture.frame())
    assert result.events[0].type == "unknown"
    assert result.events[0].type_code == 9


def test_no_end_event_gives_null_end_distance() -> None:
    fixture = fx.FullResult(events=[fx.Event(index=0, type_code=0)])
    assert decode_one(fixture.frame()).end_event_distance_m is None


def test_curve_values_convert_to_db() -> None:
    # 25000 represents 20.000 dB (manual 3.6.10); 0 is the -5 dB floor.
    result = decode_one(fx.FullResult(curve=[25000, 5000, 0, 5500]).frame())
    assert result.data_num == 4
    assert result.curve_db() == pytest.approx([20.0, 0.0, -5.0, 0.5])


def test_event_count_beyond_data_raises_decode_error() -> None:
    data = three_event_result().data()
    # Claim 4 events but carry only 3: the declared datalen still matches the
    # bytes sent, so this is a payload error, not a framing error.
    events_at = 52 + 4 + 2 * 4
    bad = data[:events_at] + u32(4) + data[events_at + 4 :]
    with pytest.raises(p.DecodeError):
        decode_one(fx.frame(0x90000000, bad))


def test_trailing_bytes_in_full_result_raise_decode_error() -> None:
    data = three_event_result().data() + b"\x00\x00\x00\x00"
    with pytest.raises(p.DecodeError):
        decode_one(fx.frame(0x90000000, data))


# ---------------------------------------------------------------- other frames


def test_status_code_19_is_typed_busy_error() -> None:
    status = decode_one(fx.status_frame(19))
    assert isinstance(status, p.StatusResponse)
    assert status.code == p.StatusCode.OTDR_BUSY
    assert not status.ok
    with pytest.raises(p.OtdrBusyError) as info:
        status.raise_for_status()
    assert info.value.code == 19
    assert isinstance(info.value, p.OtdrStatusError)


def test_status_code_0_is_ok() -> None:
    status = decode_one(fx.status_frame(0))
    assert status.ok
    status.raise_for_status()  # does not raise


def test_status_code_16_is_status_error_but_not_busy() -> None:
    status = decode_one(fx.status_frame(16))
    with pytest.raises(p.OtdrStatusError) as info:
        status.raise_for_status()
    assert not isinstance(info.value, p.OtdrBusyError)
    assert info.value.code == p.StatusCode.RANGE_OR_PULSE_INVALID


def test_refresh_curve_decodes() -> None:
    result = decode_one(fx.refresh_frame([25000, 6000]))
    assert isinstance(result, p.RefreshCurve)
    assert result.data_num == 2
    assert result.curve_db() == pytest.approx([20.0, 1.0])


def test_heartbeat_reply_decodes() -> None:
    assert isinstance(decode_one(fx.heartbeat_reply_frame(42)), p.HeartbeatReply)


def test_test_status_decodes() -> None:
    status = decode_one(fx.otdr_status_frame(1, 1550, 60000, 640, 30000, 12000))
    assert status == p.TestStatus(
        mode=1,
        wavelength_nm=1550,
        range_m=60000,
        pulse_width_ns=640,
        measure_time_ms=30000,
        elapsed_ms=12000,
    )
    assert status.busy


def test_version_decodes() -> None:
    # version 0x0203 -> 2.3; 14:05:09 -> hour<<16 | minute<<8 | second
    raw = fx.version_frame(0x0203, 2024, 5, 17, (14 << 16) | (5 << 8) | 9, b"GL3800M")
    info = decode_one(raw)
    assert isinstance(info, p.VersionInfo)
    assert (info.major, info.minor) == (2, 3)
    assert (info.year, info.month, info.day) == (2024, 5, 17)
    assert (info.hour, info.minute, info.second) == (14, 5, 9)
    assert info.device == "GL3800M"
    assert info.firmware == "2.3 (2024-05-17 14:05:09)"


def test_unknown_command_raises_decode_error() -> None:
    with pytest.raises(p.DecodeError):
        decode_one(fx.frame(0x9ABCDEF0, u32(0)))


def test_wrong_payload_size_for_status_raises_decode_error() -> None:
    with pytest.raises(p.DecodeError):
        decode_one(fx.frame(0xA0000000, b""))


# ---------------------------------------------------------------- framing


def test_wrong_sync_string_raises_framing_error() -> None:
    raw = fx.status_frame(0)
    bad = b"GLinkOtdr-3800X\x00" + raw[16:]
    with pytest.raises(p.FramingError):
        p.FrameReader().feed(bad)


def test_datalen_disagreeing_with_total_length_raises_framing_error() -> None:
    raw = bytearray(fx.status_frame(0))
    raw[48:52] = u32(8)  # datalen says 8, TotalLength says 4
    with pytest.raises(p.FramingError):
        p.FrameReader().feed(bytes(raw))


def test_total_length_smaller_than_empty_frame_raises_framing_error() -> None:
    raw = bytearray(fx.status_frame(0))
    raw[16:20] = u32(40)
    with pytest.raises(p.FramingError):
        p.FrameReader().feed(bytes(raw))


def test_frame_in_three_partial_chunks_reassembles() -> None:
    raw = three_event_result().frame()
    whole = decode_one(raw)

    reader = p.FrameReader()
    # Split inside the sync string, inside the header/cmd, then the rest.
    assert reader.feed(raw[:10]) == []
    assert reader.feed(raw[10:50]) == []
    frames = reader.feed(raw[50:])
    assert len(frames) == 1
    assert p.decode(frames[0]) == whole


def test_two_frames_in_one_chunk_both_decode() -> None:
    raw = fx.status_frame(0) + fx.heartbeat_reply_frame()
    frames = p.FrameReader().feed(raw)
    assert [f.cmd for f in frames] == [0xA0000000, 0x90000002]


def test_async_read_frame_from_stream_reader() -> None:
    raw = three_event_result().frame()

    async def run() -> p.Frame:
        reader = asyncio.StreamReader()
        reader.feed_data(raw[:20])
        reader.feed_data(raw[20:300])
        reader.feed_data(raw[300:] + fx.status_frame(19))
        reader.feed_eof()
        first = await p.read_frame(reader)
        second = await p.read_frame(reader)
        assert p.decode(second).code == 19
        return first

    frame = asyncio.run(run())
    assert p.decode(frame) == decode_one(raw)


def test_async_read_frame_rejects_bad_sync() -> None:
    async def run() -> None:
        reader = asyncio.StreamReader()
        reader.feed_data(b"X" * 16 + fx.status_frame(0)[16:])
        reader.feed_eof()
        await p.read_frame(reader)

    with pytest.raises(p.FramingError):
        asyncio.run(run())

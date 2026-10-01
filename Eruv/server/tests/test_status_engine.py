"""The two KTD6 state machines as pure functions (R10, R11, R13, R14)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import DeviceHealth, LineState
from app.status_engine import (
    LineStep,
    health_on_fault,
    health_on_heartbeat,
    health_on_valid_result,
    health_on_watchdog,
    line_on_reconnect,
    line_on_reference_set,
    line_on_result,
)

REF = 47210.0
TOL = 50.0


def run(state: LineState, distances: list[float | None], reference: float | None = REF) -> list[LineStep]:
    steps: list[LineStep] = []
    suspect = None
    for d in distances:
        step = line_on_result(state, suspect, d, reference, TOL)
        steps.append(step)
        state, suspect = step.state, step.suspect_distance_m
    return steps


# --- line state -----------------------------------------------------------------


def test_ae1_two_break_results_20m_apart_confirm_break_once() -> None:
    steps = run(LineState.OK, [13400.0, 13420.0, 13410.0])
    assert [s.state for s in steps] == [LineState.SUSPECT_BREAK, LineState.BREAK, LineState.BREAK]
    into_break = [s for s in steps if s.transition and s.state == LineState.BREAK]
    assert len(into_break) == 1
    assert steps[2].transition is False


def test_ae2_break_then_intact_is_a_single_suspect_reading() -> None:
    steps = run(LineState.OK, [13400.0, 47205.0])
    assert [s.state for s in steps] == [LineState.SUSPECT_BREAK, LineState.OK]
    assert steps[0].transition and "suspect" in (steps[0].detail or "").lower()
    assert steps[1].transition
    assert all(s.state != LineState.BREAK for s in steps)


def test_two_break_results_400m_apart_stay_suspect_with_newer_candidate() -> None:
    steps = run(LineState.OK, [13400.0, 13800.0])
    assert steps[1].state == LineState.SUSPECT_BREAK
    assert steps[1].suspect_distance_m == 13800.0
    assert steps[1].transition  # the SUSPECT -> SUSPECT edge is logged
    # a third reading agreeing with the newer candidate confirms
    assert run(LineState.OK, [13400.0, 13800.0, 13830.0])[2].state == LineState.BREAK


def test_tolerance_boundaries() -> None:
    # exactly reference - tolerance is intact
    assert run(LineState.OK, [REF - TOL])[0].state == LineState.OK
    assert run(LineState.OK, [REF - TOL - 0.1])[0].state == LineState.SUSPECT_BREAK
    # agreement within tolerance is inclusive
    assert run(LineState.OK, [13400.0, 13450.0])[1].state == LineState.BREAK
    assert run(LineState.OK, [13400.0, 13450.1])[1].state == LineState.SUSPECT_BREAK


def test_ae8_no_reference_never_breaks() -> None:
    steps = run(LineState.AWAITING_REFERENCE, [13400.0, 13400.0, 13400.0], reference=None)
    assert all(s.state == LineState.AWAITING_REFERENCE and not s.transition for s in steps)


def test_break_then_result_120m_past_reference_is_ok_with_rebaseline_warning() -> None:
    step = line_on_result(LineState.BREAK, None, REF + 120.0, REF, TOL)
    assert step.state == LineState.OK and step.transition
    assert step.rebaseline_warning
    assert "longer than reference" in (step.detail or "")


def test_rebaseline_warning_only_beyond_tolerance() -> None:
    assert not line_on_result(LineState.BREAK, None, REF + TOL, REF, TOL).rebaseline_warning
    assert line_on_result(LineState.OK, None, REF + TOL + 0.1, REF, TOL).rebaseline_warning


def test_break_result_while_in_break_stays_break_silently() -> None:
    step = line_on_result(LineState.BREAK, None, 20000.0, REF, TOL)
    assert step.state == LineState.BREAK and not step.transition


def test_null_end_event_changes_nothing() -> None:
    step = line_on_result(LineState.SUSPECT_BREAK, 13400.0, None, REF, TOL)
    assert step.state == LineState.SUSPECT_BREAK
    assert step.suspect_distance_m == 13400.0
    assert not step.transition
    assert not step.usable


def test_reconnect_clears_candidate_so_one_break_result_cannot_confirm() -> None:
    # Suspect before the outage; after reconnect a matching break result must not jump to BREAK.
    suspect = line_on_reconnect()
    assert suspect is None
    step = line_on_result(LineState.SUSPECT_BREAK, suspect, 13400.0, REF, TOL)
    assert step.state == LineState.SUSPECT_BREAK and step.suspect_distance_m == 13400.0
    assert line_on_reconnect() is None


def test_reference_set_moves_awaiting_to_ok_only() -> None:
    assert line_on_reference_set(LineState.AWAITING_REFERENCE) == LineState.OK
    assert line_on_reference_set(LineState.OK) == LineState.OK
    assert line_on_reference_set(LineState.BREAK) == LineState.BREAK


# --- device health --------------------------------------------------------------

T0 = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
START = T0 - timedelta(hours=1)


def watchdog(health: DeviceHealth, at_s: float, **kw) -> DeviceHealth:
    args = dict(
        last_heartbeat_at=T0,
        last_result_at=T0,
        last_fault_at=None,
        server_started_at=START,
        online_since=None,
        heartbeat_timeout_s=30.0,
        result_timeout_s=270.0,
    )
    args.update(kw)
    new, _detail = health_on_watchdog(health, now=T0 + timedelta(seconds=at_s), **args)
    return new


def test_heartbeat_machine_edges() -> None:
    assert health_on_heartbeat(DeviceHealth.DISCONNECTED) == DeviceHealth.ONLINE
    assert health_on_heartbeat(DeviceHealth.ONLINE) == DeviceHealth.ONLINE
    assert health_on_heartbeat(DeviceHealth.FAULT) == DeviceHealth.FAULT
    assert health_on_fault(DeviceHealth.ONLINE) == DeviceHealth.FAULT
    assert health_on_fault(DeviceHealth.DISCONNECTED) == DeviceHealth.DISCONNECTED
    assert health_on_valid_result(DeviceHealth.FAULT) == DeviceHealth.ONLINE
    assert health_on_valid_result(DeviceHealth.DISCONNECTED) == DeviceHealth.DISCONNECTED


def test_ae6_disconnected_at_30s_not_29s() -> None:
    assert watchdog(DeviceHealth.ONLINE, 29.0) == DeviceHealth.ONLINE
    assert watchdog(DeviceHealth.ONLINE, 30.0) == DeviceHealth.DISCONNECTED
    assert watchdog(DeviceHealth.FAULT, 30.0) == DeviceHealth.DISCONNECTED


def test_missed_heartbeats_count_from_server_start_when_later() -> None:
    # Server started 5 minutes after the last stored heartbeat: 20 s after start is not an outage.
    start = T0 + timedelta(minutes=5)
    assert watchdog(DeviceHealth.ONLINE, 300 + 20, server_started_at=start) == DeviceHealth.ONLINE
    assert watchdog(DeviceHealth.ONLINE, 300 + 30, server_started_at=start) == DeviceHealth.DISCONNECTED


def test_fault_after_three_cadences_without_result() -> None:
    fresh_hb = dict(last_heartbeat_at=T0 + timedelta(seconds=265))
    assert watchdog(DeviceHealth.ONLINE, 269.0, **fresh_hb) == DeviceHealth.ONLINE
    fresh_hb = dict(last_heartbeat_at=T0 + timedelta(seconds=265))
    assert watchdog(DeviceHealth.ONLINE, 270.0, **fresh_hb) == DeviceHealth.FAULT


def test_result_silence_counts_from_latest_of_result_start_and_reconnect() -> None:
    hb = dict(last_heartbeat_at=T0 + timedelta(seconds=995))
    # last result long ago, but the device came back online at t=900: not yet FAULT at t=1000
    assert (
        watchdog(DeviceHealth.ONLINE, 1000.0, online_since=T0 + timedelta(seconds=900), **hb)
        == DeviceHealth.ONLINE
    )
    assert watchdog(DeviceHealth.ONLINE, 1000.0, **hb) == DeviceHealth.FAULT


def test_pending_fault_report_moves_online_to_fault() -> None:
    new = watchdog(DeviceHealth.ONLINE, 5.0, last_fault_at=T0 + timedelta(seconds=1))
    assert new == DeviceHealth.FAULT
    # a fault older than the last valid result is resolved
    assert watchdog(DeviceHealth.ONLINE, 5.0, last_fault_at=T0 - timedelta(seconds=1)) == DeviceHealth.ONLINE


def test_disconnected_never_goes_to_fault_by_watchdog() -> None:
    assert watchdog(DeviceHealth.DISCONNECTED, 1000.0, last_heartbeat_at=T0 + timedelta(seconds=990)) == (
        DeviceHealth.DISCONNECTED
    )

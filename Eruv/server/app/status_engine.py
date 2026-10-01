"""The two per-city state machines of KTD6, as pure functions.

``line_state`` is driven only by results (R10, R11, R14); ``device_health`` by
heartbeats, fault messages and the watchdog (R13). Nothing here touches the
database; ``app.services.status`` applies these steps and logs transitions.

Decisions recorded here:
- A result whose ``end_event_distance_m`` is null is an unusable reading. It
  cannot show the line intact, so it never moves ``line_state`` (and keeps any
  break candidate), and it does not count as a valid result for device health.
- Every path into BREAK goes through SUSPECT_BREAK. A second break reading at a
  different place (outside tolerance) stays SUSPECT_BREAK with the newer candidate.
- After a reconnect the break candidate is dropped, so one break result after an
  outage can never confirm a break on its own (KTD6, "including after a reconnect").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.models import DeviceHealth, LineState

REBASELINE_WARNING = "fiber longer than reference — re-baseline"


@dataclass(frozen=True)
class LineStep:
    state: LineState
    suspect_distance_m: float | None
    # True when this reading is an edge of the diagram (logged as a status event).
    transition: bool
    detail: str | None = None
    # End event more than the tolerance past the reference (R11).
    rebaseline_warning: bool = False
    # False for a reading with no end event (see module docstring).
    usable: bool = True


def line_on_result(
    state: LineState,
    suspect_distance_m: float | None,
    end_event_m: float | None,
    reference_m: float | None,
    tolerance_m: float,
) -> LineStep:
    if end_event_m is None:
        return LineStep(state, suspect_distance_m, False, usable=False)
    if state == LineState.AWAITING_REFERENCE or reference_m is None:
        return LineStep(state, suspect_distance_m, False)

    if end_event_m >= reference_m - tolerance_m:
        longer = end_event_m > reference_m + tolerance_m
        warning = (
            f"{REBASELINE_WARNING} (end event {end_event_m:.1f} m, reference {reference_m:.1f} m)" if longer else None
        )
        if state == LineState.OK:
            return LineStep(LineState.OK, None, False, warning, longer)
        base = (
            "suspect reading not confirmed" if state == LineState.SUSPECT_BREAK else "line intact"
        ) + f": end event {end_event_m:.1f} m"
        detail = f"{base}; {warning}" if warning else base
        return LineStep(LineState.OK, None, True, detail, longer)

    # break reading
    if state == LineState.OK:
        return LineStep(
            LineState.SUSPECT_BREAK,
            end_event_m,
            True,
            f"suspect reading: end event {end_event_m:.1f} m, reference {reference_m:.1f} m",
        )
    if state == LineState.SUSPECT_BREAK:
        if suspect_distance_m is not None and abs(end_event_m - suspect_distance_m) <= tolerance_m:
            return LineStep(
                LineState.BREAK,
                None,
                True,
                f"break confirmed at {end_event_m:.1f} m (previous reading {suspect_distance_m:.1f} m)",
            )
        previous = f"{suspect_distance_m:.1f} m" if suspect_distance_m is not None else "none"
        return LineStep(
            LineState.SUSPECT_BREAK,
            end_event_m,
            True,
            f"suspect reading: end event {end_event_m:.1f} m (previous candidate {previous}), not confirmed",
        )
    return LineStep(LineState.BREAK, None, False)


def visible_line_state(state: LineState | str) -> LineState:
    """The line state users see: the hidden SUSPECT_BREAK shows as OK (R10, KTD6).

    Every edge into SUSPECT_BREAK starts from OK or SUSPECT_BREAK, so OK is always
    the previous visible state.
    """
    state = LineState(state)
    return LineState.OK if state == LineState.SUSPECT_BREAK else state


def line_on_reference_set(state: LineState) -> LineState:
    return LineState.OK if state == LineState.AWAITING_REFERENCE else state


def line_on_reconnect() -> None:
    """The break candidate to keep when the device comes back from DISCONNECTED."""
    return None


def health_on_heartbeat(health: DeviceHealth) -> DeviceHealth:
    return DeviceHealth.ONLINE if health == DeviceHealth.DISCONNECTED else health


def health_on_fault(health: DeviceHealth) -> DeviceHealth:
    return DeviceHealth.FAULT if health == DeviceHealth.ONLINE else health


def health_on_valid_result(health: DeviceHealth) -> DeviceHealth:
    return DeviceHealth.ONLINE if health == DeviceHealth.FAULT else health


def _latest(*times: datetime | None) -> datetime:
    return max(t for t in times if t is not None)


def health_on_watchdog(
    health: DeviceHealth,
    *,
    now: datetime,
    last_heartbeat_at: datetime | None,
    last_result_at: datetime | None,
    last_fault_at: datetime | None,
    server_started_at: datetime,
    online_since: datetime | None,
    heartbeat_timeout_s: float,
    result_timeout_s: float,
) -> tuple[DeviceHealth, str | None]:
    """One watchdog evaluation (R13). Returns the new health and a log detail.

    Silence is counted from the latest of the last message and the server start,
    so a restart does not mark every device down. Result silence also counts from
    the device's last return to ONLINE, so a reconnect is not instantly a FAULT
    while the Pi's spool drains.
    """
    if health == DeviceHealth.DISCONNECTED:
        return health, None
    hb_quiet = (now - _latest(last_heartbeat_at, server_started_at)).total_seconds()
    if hb_quiet >= heartbeat_timeout_s:
        return DeviceHealth.DISCONNECTED, f"no heartbeat for {hb_quiet:.0f} s"
    if health == DeviceHealth.FAULT:
        return health, None
    if last_fault_at is not None and (last_result_at is None or last_fault_at > last_result_at):
        return DeviceHealth.FAULT, "equipment fault reported since the last valid result"
    result_quiet = (now - _latest(last_result_at, server_started_at, online_since)).total_seconds()
    if result_quiet >= result_timeout_s:
        return DeviceHealth.FAULT, f"no valid test result for {result_quiet:.0f} s"
    return health, None

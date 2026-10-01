"""Spool (KTD8): persistent seq, bounded capacity, seq-ordered delivery, queued_s."""

from __future__ import annotations

from eruv_agent.spool import Spool


class FakeClock:
    def __init__(self, mono: float = 1000.0, wall: float = 1_790_000_000.0, boot: str = "boot-a") -> None:
        self.mono = mono
        self.wall_s = wall
        self.boot = boot

    def monotonic(self) -> float:
        return self.mono

    def wall(self) -> float:
        return self.wall_s

    def boot_id(self) -> str:
        return self.boot

    def uptime_s(self) -> float:
        return self.mono

    def advance(self, s: float) -> None:
        self.mono += s
        self.wall_s += s


def payload(seq: int) -> dict:
    return {"seq": seq, "x": "y"}


def test_seq_starts_at_one_and_increases(tmp_path):
    spool = Spool(tmp_path / "s.db", capacity=10, clock=FakeClock())
    assert spool.enqueue("result", payload) == 1
    assert spool.enqueue("fault", payload) == 2
    assert [m.seq for m in spool.pending()] == [1, 2]
    assert spool.peek().payload == {"seq": 1, "x": "y"}
    assert spool.peek().kind == "result"


def test_at_capacity_drops_oldest_never_newest(tmp_path):
    spool = Spool(tmp_path / "s.db", capacity=3, clock=FakeClock())
    for _ in range(5):
        spool.enqueue("result", payload)
    assert [m.seq for m in spool.pending()] == [3, 4, 5]
    assert spool.depth() == 3


def test_seq_survives_restart_with_empty_spool(tmp_path):
    path = tmp_path / "s.db"
    spool = Spool(path, capacity=10, clock=FakeClock())
    spool.enqueue("result", payload)
    last = spool.enqueue("result", payload)
    for m in spool.pending():
        spool.remove(m.seq)
    assert spool.depth() == 0
    spool.close()

    reopened = Spool(path, capacity=10, clock=FakeClock())
    assert reopened.enqueue("result", payload) > last


def test_queued_s_same_boot_uses_monotonic(tmp_path):
    clock = FakeClock()
    spool = Spool(tmp_path / "s.db", capacity=10, clock=clock)
    spool.enqueue("result", payload)
    clock.mono += 30.0
    clock.wall_s -= 3600  # an NTP jump must not affect it
    assert spool.peek().queued_s(clock) == 30.0


def test_queued_s_after_reboot_is_at_least_uptime(tmp_path):
    path = tmp_path / "s.db"
    before = FakeClock(mono=5000.0, wall=1_790_000_000.0, boot="boot-a")
    Spool(path, capacity=10, clock=before).enqueue("result", payload)

    # Rebooted 40 s ago; the wall clock is still wrong (earlier than before).
    after = FakeClock(mono=40.0, wall=1_700_000_000.0, boot="boot-b")
    assert Spool(path, capacity=10, clock=after).peek().queued_s(after) == 40.0

    # Once NTP has synced, the wall-clock gap is used when it is larger.
    synced = FakeClock(mono=40.0, wall=1_790_000_600.0, boot="boot-b")
    assert Spool(path, capacity=10, clock=synced).peek().queued_s(synced) == 600.0

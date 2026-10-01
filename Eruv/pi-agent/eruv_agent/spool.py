"""Bounded, persistent outbox for results and faults (KTD8, R9).

- ``seq`` comes from a counter row in its own table, never from a rowid, so it
  keeps increasing across an empty spool, a crash and a power cut.
- At capacity the OLDEST undelivered message is dropped, never the newest.
- Messages are delivered in ``seq`` order.

``queued_s`` (seconds a message waited before a delivery attempt) must not
depend on the wall clock, which is wrong on a Pi 5 until NTP syncs. Each row
stores the monotonic time and the kernel boot id at enqueue:

- same boot: ``now_monotonic - enqueued_monotonic`` (exact);
- after a reboot the old monotonic value is meaningless, but the message is at
  least as old as the current boot, so ``queued_s = max(uptime, wall-clock gap)``.
  The wall-clock gap only counts once it is larger, i.e. after NTP has synced.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

_PROCESS_BOOT_ID = f"process-{uuid.uuid4()}"  # fallback when the kernel has no boot id


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def wall(self) -> float:
        return time.time()

    def boot_id(self) -> str:
        try:
            return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        except OSError:
            return _PROCESS_BOOT_ID

    def uptime_s(self) -> float:
        try:
            return float(Path("/proc/uptime").read_text().split()[0])
        except (OSError, ValueError, IndexError):
            return time.monotonic()


@dataclass(frozen=True)
class SpooledMessage:
    seq: int
    kind: str  # "result" or "fault"
    payload: dict
    enqueued_wall: float
    enqueued_mono: float
    boot_id: str

    def queued_s(self, clock) -> float:
        if clock.boot_id() == self.boot_id:
            return max(0.0, clock.monotonic() - self.enqueued_mono)
        return max(0.0, clock.uptime_s(), clock.wall() - self.enqueued_wall)


class Spool:
    def __init__(self, path: str | Path, capacity: int = 2000, clock=None) -> None:
        self.capacity = capacity
        self.clock = clock or SystemClock()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), isolation_level=None)
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS counter (
                name  TEXT PRIMARY KEY,
                value INTEGER NOT NULL
            );
            INSERT OR IGNORE INTO counter (name, value) VALUES ('seq', 0);
            CREATE TABLE IF NOT EXISTS outbox (
                seq           INTEGER PRIMARY KEY,
                kind          TEXT NOT NULL,
                payload       TEXT NOT NULL,
                enqueued_wall REAL NOT NULL,
                enqueued_mono REAL NOT NULL,
                boot_id       TEXT NOT NULL
            );
            """
        )

    def enqueue(self, kind: str, build: Callable[[int], dict]) -> int:
        """Assign the next seq, store ``build(seq)``, and trim to capacity. Returns seq."""
        db = self._db
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("UPDATE counter SET value = value + 1 WHERE name = 'seq'")
            (seq,) = db.execute("SELECT value FROM counter WHERE name = 'seq'").fetchone()
            payload = build(seq)
            db.execute(
                "INSERT INTO outbox (seq, kind, payload, enqueued_wall, enqueued_mono, boot_id)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (seq, kind, json.dumps(payload), self.clock.wall(), self.clock.monotonic(), self.clock.boot_id()),
            )
            dropped = db.execute(
                "DELETE FROM outbox WHERE seq IN ("
                " SELECT seq FROM outbox ORDER BY seq DESC LIMIT -1 OFFSET ?)"
                " RETURNING seq",
                (self.capacity,),
            ).fetchall()
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        if dropped:
            log.warning("spool full (%d): dropped oldest undelivered seq %s",
                        self.capacity, sorted(s for (s,) in dropped))
        return seq

    def pending(self, limit: int = -1) -> list[SpooledMessage]:
        rows = self._db.execute(
            "SELECT seq, kind, payload, enqueued_wall, enqueued_mono, boot_id"
            " FROM outbox ORDER BY seq LIMIT ?",
            (limit,),
        ).fetchall()
        return [SpooledMessage(s, k, json.loads(p), w, m, b) for s, k, p, w, m, b in rows]

    def peek(self) -> SpooledMessage | None:
        rows = self.pending(1)
        return rows[0] if rows else None

    def remove(self, seq: int) -> None:
        self._db.execute("DELETE FROM outbox WHERE seq = ?", (seq,))

    def depth(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]

    def last_seq(self) -> int:
        return self._db.execute("SELECT value FROM counter WHERE name = 'seq'").fetchone()[0]

    def close(self) -> None:
        self._db.close()

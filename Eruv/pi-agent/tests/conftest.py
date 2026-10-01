"""Shared helpers. Agent timings are scaled down by 100x (90 s cadence -> 0.9 s)
through config, so no test sleeps real minutes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eruv_agent.config import parse_config

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = REPO_ROOT / "contracts"
SCALE = 0.01


def load_schema(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def scaled_config(tmp_path: Path, otdr_port: int = 5000, **sections) -> object:
    raw = {
        "server": {
            "base_url": "https://stub.test",
            "device_key": "test-key",
            "request_timeout_s": 1,
        },
        "otdr": {
            "host": "127.0.0.1",
            "port": otdr_port,
            "keepalive_idle_s": 20 * SCALE,
            "result_timeout_margin_s": 60 * SCALE,
            "connect_timeout_s": 1,
            "reconnect_initial_s": 0.02,
            "reconnect_max_s": 60 * SCALE,
        },
        "test": {
            "wavelength_nm": 1550,
            "range_m": 60000,
            "pulse_width_ns": 640,
            "measure_time_ms": 300,  # 30 s scaled
            "group_index": 1.4685,
            "end_threshold_db": 5.0,
            "non_reflect_threshold_db": 0.0,
        },
        "schedule": {
            "cadence_s": 90 * SCALE,
            "heartbeat_s": 10 * SCALE,
            "uplink_retry_s": 0.05,
        },
        "spool": {"path": str(tmp_path / "spool.sqlite3"), "capacity": 2000},
    }
    for name, values in sections.items():
        raw[name].update(values)
    return parse_config(raw)


@pytest.fixture
def cfg_factory(tmp_path):
    def make(otdr_port: int = 5000, **sections):
        return scaled_config(tmp_path, otdr_port, **sections)

    return make

"""Config loading: https guard, example file values, clear exit on bad config."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from eruv_agent.config import ConfigError, load_config, parse_config

PI_AGENT = Path(__file__).resolve().parents[1]
EXAMPLE = PI_AGENT / "config" / "agent.example.yaml"


def minimal(base_url: str, **server) -> dict:
    return {"server": {"base_url": base_url, "device_key": "k", **server}}


def test_http_base_url_is_refused_without_flag():
    with pytest.raises(ConfigError, match="https"):
        parse_config(minimal("http://203.0.113.10"))


def test_http_allowed_with_insecure_dev_flag():
    cfg = parse_config(minimal("http://localhost:8000", allow_insecure_dev=True))
    assert cfg.server.base_url == "http://localhost:8000"


def test_missing_device_key_is_refused():
    with pytest.raises(ConfigError, match="device_key"):
        parse_config({"server": {"base_url": "https://x.test"}})


def test_example_config_carries_the_documented_defaults():
    cfg = load_config(EXAMPLE)
    assert cfg.server.base_url == "https://203.0.113.10"
    assert cfg.server.device_key == "CHANGE_ME"
    assert cfg.server.allow_insecure_dev is False
    assert (cfg.otdr.host, cfg.otdr.port) == ("192.168.1.249", 5000)
    t = cfg.test
    assert (t.wavelength_nm, t.range_m, t.pulse_width_ns, t.measure_time_ms) == (1550, 60000, 640, 30000)
    assert (t.group_index, t.end_threshold_db, t.non_reflect_threshold_db) == (1.4685, 5.0, 0.0)
    assert (cfg.schedule.cadence_s, cfg.schedule.heartbeat_s) == (60, 10)
    assert cfg.spool.path == "/var/lib/eruv-agent/spool.sqlite3"
    assert cfg.spool.capacity == 2000
    sp = t.start_params()
    assert (sp.otdr_mode, sp.enable_refresh) == (1, False)  # averaging, refresh off


def test_agent_exits_with_clear_error_on_http_url(tmp_path):
    bad = tmp_path / "agent.yaml"
    bad.write_text("server:\n  base_url: http://203.0.113.10\n  device_key: k\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "eruv_agent", "--config", str(bad)],
        cwd=PI_AGENT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode != 0
    assert "https" in proc.stderr
    assert "allow_insecure_dev" in proc.stderr

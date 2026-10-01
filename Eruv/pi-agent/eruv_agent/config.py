"""Agent configuration, read from a YAML file (on the Pi: /etc/eruv-agent/agent.yaml)."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from urllib.parse import urlparse

import yaml

from eruv_agent.protocol import StartMeasureParams


class ConfigError(Exception):
    """The config file is missing, unreadable or invalid. The agent must not start."""


@dataclass
class ServerConfig:
    base_url: str
    device_key: str
    allow_insecure_dev: bool = False
    request_timeout_s: float = 8.0


@dataclass
class OtdrConfig:
    host: str = "192.168.1.249"
    port: int = 5000
    keepalive_idle_s: float = 20.0  # send 0x10000003 after this long without traffic (R6)
    result_timeout_margin_s: float = 60.0  # final data due within measure time + this
    connect_timeout_s: float = 10.0
    reconnect_initial_s: float = 1.0
    reconnect_max_s: float = 60.0


@dataclass
class TestParams:
    """Test parameters sent in 0x10000000. Averaging mode, manual method, refresh off."""

    __test__ = False  # not a pytest class

    wavelength_nm: int = 1550
    range_m: int = 60000
    pulse_width_ns: int = 640
    measure_time_ms: int = 30000
    group_index: float = 1.4685
    end_threshold_db: float = 5.0
    non_reflect_threshold_db: float = 0.0  # 0 = automatic

    def start_params(self) -> StartMeasureParams:
        return StartMeasureParams(
            wavelength_nm=self.wavelength_nm,
            range_m=self.range_m,
            pulse_width_ns=self.pulse_width_ns,
            measure_time_ms=self.measure_time_ms,
            group_index=self.group_index,
            end_threshold_db=self.end_threshold_db,
            non_reflect_threshold_db=self.non_reflect_threshold_db,
            otdr_mode=1,
            enable_refresh=False,
        )


@dataclass
class ScheduleConfig:
    cadence_s: float = 60.0  # from test start to next test start (R2)
    heartbeat_s: float = 10.0  # R5
    uplink_retry_s: float = 5.0  # retry delay after a failed delivery


@dataclass
class SpoolConfig:
    path: str = "/var/lib/eruv-agent/spool.sqlite3"
    capacity: int = 2000


@dataclass
class Config:
    server: ServerConfig
    otdr: OtdrConfig = field(default_factory=OtdrConfig)
    test: TestParams = field(default_factory=TestParams)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    spool: SpoolConfig = field(default_factory=SpoolConfig)


def _section(cls, raw: object, name: str):
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError(f"'{name}' must be a mapping")
    known = {f.name: f for f in fields(cls)}
    unknown = set(raw) - set(known)
    if unknown:
        raise ConfigError(f"unknown key(s) in '{name}': {', '.join(sorted(unknown))}")
    values = {}
    for key, value in raw.items():
        default = getattr(cls, key, None)
        # Coerce numbers to the type of the default so YAML "90" and "90.0" both work.
        if isinstance(default, bool):
            if not isinstance(value, bool):
                raise ConfigError(f"'{name}.{key}' must be true or false")
        elif isinstance(default, (int, float)) and not isinstance(default, bool):
            try:
                value = type(default)(value)
            except (TypeError, ValueError):
                raise ConfigError(f"'{name}.{key}' must be a number") from None
        values[key] = value
    try:
        return cls(**values)
    except TypeError as exc:
        raise ConfigError(f"'{name}': {exc}") from None


def parse_config(raw: object) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError("config must be a YAML mapping")
    unknown = set(raw) - {"server", "otdr", "test", "schedule", "spool"}
    if unknown:
        raise ConfigError(f"unknown section(s): {', '.join(sorted(unknown))}")

    server_raw = raw.get("server") or {}
    for key in ("base_url", "device_key"):
        if not server_raw.get(key):
            raise ConfigError(f"'server.{key}' is required")
    server = _section(ServerConfig, server_raw, "server")

    scheme = urlparse(server.base_url).scheme
    if scheme != "https" and not (scheme == "http" and server.allow_insecure_dev):
        raise ConfigError(
            f"server.base_url must use https (got '{server.base_url}'). "
            "The device key would travel in clear text. "
            "For local development only, set 'server.allow_insecure_dev: true'."
        )
    server.base_url = server.base_url.rstrip("/")

    cfg = Config(
        server=server,
        otdr=_section(OtdrConfig, raw.get("otdr"), "otdr"),
        test=_section(TestParams, raw.get("test"), "test"),
        schedule=_section(ScheduleConfig, raw.get("schedule"), "schedule"),
        spool=_section(SpoolConfig, raw.get("spool"), "spool"),
    )
    if cfg.spool.capacity < 1:
        raise ConfigError("'spool.capacity' must be at least 1")
    return cfg


def load_config(path: str | Path) -> Config:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from None
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"config file {path} is not valid YAML: {exc}") from None
    return parse_config(raw)

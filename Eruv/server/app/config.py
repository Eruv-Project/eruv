"""Server settings, read from the environment or `server/.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The JWT_SECRET value shipped in `.env.example` (caught by the "replace-with" marker).
EXAMPLE_JWT_SECRET = "replace-with-a-long-random-secret-at-least-32-chars"
# Matched case-insensitively, with "_" read as "-" (so "change_me" is caught too).
PLACEHOLDER_MARKERS = ("replace-with", "change-me", "changeme")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # postgresql+psycopg://user:pass@host:5432/eruv in production.
    database_url: str
    # Signs app JWTs. Must be long and random; rotating it logs every user out.
    jwt_secret: str = Field(min_length=32)
    # Public HTTPS origin of this server (the AWS address; see README).
    public_base_url: str

    access_token_ttl_s: int = 15 * 60
    refresh_token_ttl_s: int = 30 * 24 * 3600

    # Rate limiting and lockout (in-process; the server runs one worker, KTD11).
    login_ip_limit: int = 20
    login_ip_window_s: int = 60
    login_max_failures: int = 5
    login_failure_window_s: int = 15 * 60
    login_lockout_s: int = 15 * 60
    register_ip_limit: int = 10
    register_ip_window_s: int = 3600
    register_account_limit: int = 5

    # Device status (R13, KTD8). The Pi heartbeats every 10 s and tests every 60 s.
    heartbeat_interval_s: float = 10.0
    missed_heartbeats: int = 3  # -> DISCONNECTED after 30 s
    test_cadence_s: float = 60.0
    missed_cadences: int = 3  # -> FAULT after 180 s without a valid result
    # A message whose queued_s exceeds this is backlog (2 cadence periods, contract).
    backlog_threshold_s: float = 120.0
    watchdog_interval_s: float = 5.0
    # Off only in tests, which drive the watchdog with an injected clock.
    watchdog_enabled: bool = True
    # Folder with the shared JSON Schemas; default is the repo's `contracts/`.
    contracts_dir: Path | None = None

    @field_validator("jwt_secret")
    @classmethod
    def _reject_placeholder_secret(cls, value: str) -> str:
        normalized = value.lower().replace("_", "-")
        if any(marker in normalized for marker in PLACEHOLDER_MARKERS):
            raise ValueError(
                "JWT_SECRET is a placeholder value; set it to a long random secret, e.g. "
                '`python -c "import secrets; print(secrets.token_urlsafe(48))"`'
            )
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment

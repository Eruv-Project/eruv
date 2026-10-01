"""Settings validation and log redaction hardening."""

from __future__ import annotations

import logging
import secrets

import pytest
from pydantic import ValidationError

from app.config import EXAMPLE_JWT_SECRET, Settings
from app.logging_setup import TokenRedactingFilter, install_token_redaction


def make_settings(jwt_secret: str) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        jwt_secret=jwt_secret,
        public_base_url="https://example.test",
    )


@pytest.mark.parametrize(
    "secret",
    [
        EXAMPLE_JWT_SECRET,
        "change-me-" + "x" * 32,
        "CHANGE_ME_" + "x" * 32,
        "x" * 20 + "changeme" + "x" * 20,
        "please-replace-with-something-random-0123",
    ],
)
def test_placeholder_jwt_secret_rejected(secret: str) -> None:
    with pytest.raises(ValidationError, match="placeholder"):
        make_settings(secret)


def test_random_jwt_secret_accepted() -> None:
    secret = secrets.token_hex(24)  # 48 chars
    assert len(secret) == 48
    assert make_settings(secret).jwt_secret == secret


def test_filter_redacts_websocket_accept_record() -> None:
    record = logging.LogRecord(
        "uvicorn.error", logging.INFO, __file__, 1, '"WebSocket %s" [accepted]',
        ("/ws?token=abc.def.ghi&city_id=1",), None,
    )
    assert TokenRedactingFilter().filter(record)
    message = record.getMessage()
    assert "abc.def.ghi" not in message
    assert message == '"WebSocket /ws?token=***&city_id=1" [accepted]'


def test_filter_keeps_access_record_args_shape() -> None:
    # uvicorn's AccessFormatter unpacks five positional args.
    args = ("127.0.0.1:5000", "GET", "/ws?city_id=1&token=abc.def.ghi", "1.1", 101)
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d', args, None,
    )
    TokenRedactingFilter().filter(record)
    assert isinstance(record.args, tuple) and len(record.args) == 5
    assert record.args[2] == "/ws?city_id=1&token=***"


def test_uvicorn_logger_emits_redacted(caplog: pytest.LogCaptureFixture) -> None:
    install_token_redaction()
    logger = logging.getLogger("uvicorn.error")
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        logger.info('"WebSocket %s" [accepted]', "/ws?token=abc.def.ghi&city_id=1")
    assert "abc.def.ghi" not in caplog.text
    assert "token=***" in caplog.text

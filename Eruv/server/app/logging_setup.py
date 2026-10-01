"""Keep access tokens out of server logs.

The live WebSocket takes the access token as a `?token=` query value, and
uvicorn logs request paths with their query strings ('"WebSocket %s" [accepted]'
on `uvicorn.error`, request lines on `uvicorn.access`). This filter redacts
`token=<value>` to `token=***` in those records.
"""

from __future__ import annotations

import logging
import re

_TOKEN_RE = re.compile(r"(?i)(\btoken=)[^&\s\"']+")
REDACTED = r"\1***"
REDACTED_LOGGERS = ("uvicorn.error", "uvicorn.access")


def redact(text: str) -> str:
    return _TOKEN_RE.sub(REDACTED, text)


class TokenRedactingFilter(logging.Filter):
    """Rewrites a record so its message carries no `token=` query value."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = redact(record.msg)
            # Redact string args in place, keeping the tuple shape: uvicorn's
            # AccessFormatter unpacks record.args positionally.
            if isinstance(record.args, tuple):
                record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
            message = record.getMessage()
            redacted = redact(message)
            if redacted != message:
                # A non-string arg still renders a token: freeze the redacted text.
                record.msg = redacted
                record.args = ()
        except Exception:  # never let redaction break logging
            pass
        return True


_FILTER = TokenRedactingFilter()


def install_token_redaction() -> None:
    """Attach the filter to uvicorn's loggers and their handlers (idempotent)."""
    for name in REDACTED_LOGGERS:
        logger = logging.getLogger(name)
        if _FILTER not in logger.filters:
            logger.addFilter(_FILTER)
        for handler in logger.handlers:
            if _FILTER not in handler.filters:
                handler.addFilter(_FILTER)

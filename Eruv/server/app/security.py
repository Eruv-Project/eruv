"""Password hashing, secret tokens, JWTs and the in-process rate limiter."""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections import deque
from datetime import timedelta
from typing import Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import Settings
from app.db import utcnow

_password_hasher = PasswordHasher()  # argon2id with library defaults
# Verified against when the email is unknown, so timing does not reveal accounts.
_DUMMY_HASH = _password_hasher.hash("dummy-password-for-timing")

TokenType = Literal["access", "refresh"]
JWT_ALGORITHM = "HS256"


# --- passwords -------------------------------------------------------------


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


# --- opaque secrets (device keys, registration tokens) ---------------------


def new_secret_token() -> str:
    """32 random bytes, url-safe base64 (43 chars)."""
    return secrets.token_urlsafe(32)


def sha256_hex(value: str) -> str:
    """Hash for high-entropy secrets; a slow KDF adds nothing for 256-bit random keys."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# --- JWT --------------------------------------------------------------------


class TokenError(Exception):
    pass


def create_token(settings: Settings, user_id: int, token_type: TokenType) -> str:
    ttl = settings.access_token_ttl_s if token_type == "access" else settings.refresh_token_ttl_s
    now = utcnow()
    claims = {
        "sub": str(user_id),
        "typ": token_type,
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_token(settings: Settings, token: str, expected_type: TokenType) -> int:
    """Return the user id in a valid, unexpired token of the expected type."""
    try:
        claims = jwt.decode(
            token, settings.jwt_secret, algorithms=[JWT_ALGORITHM], options={"require": ["exp", "sub", "typ"]}
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if claims.get("typ") != expected_type:
        raise TokenError("wrong token type")
    try:
        return int(claims["sub"])
    except (TypeError, ValueError) as exc:
        raise TokenError("bad subject") from exc


# --- rate limiting ------------------------------------------------------------


class RateLimiter:
    """Sliding-window counters and temporary lockouts, kept in memory.

    Valid because the server runs as a single process (KTD11).
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._locked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_s: float) -> bool:
        """Record one event for `key`; return False when the limit is exceeded."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - window_s:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True

    def count(self, key: str, window_s: float) -> int:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.get(key)
            if not hits:
                return 0
            while hits and hits[0] <= now - window_s:
                hits.popleft()
            return len(hits)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def lock(self, key: str, duration_s: float) -> None:
        with self._lock:
            self._locked_until[key] = time.monotonic() + duration_s

    def is_locked(self, key: str) -> bool:
        with self._lock:
            until = self._locked_until.get(key)
            if until is None:
                return False
            if until <= time.monotonic():
                del self._locked_until[key]
                return False
            return True

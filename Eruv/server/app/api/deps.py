"""Reusable FastAPI dependencies: settings, app-user auth, role/city scoping, device auth."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_db
from app.models import ApprovalState, City, Device, Role, User
from app.security import RateLimiter, TokenError, decode_token, sha256_hex

_bearer = HTTPBearer(auto_error=False)


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter


def _unauthorized(detail: str = "not authenticated") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> User:
    """The approved user behind a valid access token.

    The user row is reloaded on every request, so a disable, rejection or city
    change takes effect immediately even for unexpired tokens (KTD10, R20).
    """
    if credentials is None:
        raise _unauthorized()
    try:
        user_id = decode_token(settings, credentials.credentials, "access")
    except TokenError:
        raise _unauthorized("invalid token") from None
    user = db.get(User, user_id)
    if user is None or user.approval_state != ApprovalState.APPROVED:
        raise _unauthorized("access revoked")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="admin only")
    return user


def require_city_access(
    city_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> City:
    """The city named by the `city_id` path parameter, if this user may read it.

    Admins read every city; a maintainer only their approved city (403 otherwise).
    """
    if user.role != Role.ADMIN and user.approved_city_id != city_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="no access to this city")
    city = db.get(City, city_id)
    if city is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="city not found")
    return city


def current_device(
    x_device_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Device:
    """The device whose API key is in `X-Device-Key` (contracts/pi-server-api.md); 401 otherwise."""
    if not x_device_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="missing device key")
    device = db.scalar(select(Device).where(Device.api_key_hash == sha256_hex(x_device_key)))
    if device is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="unknown device key")
    return device

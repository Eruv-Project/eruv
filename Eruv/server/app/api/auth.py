"""App-user authentication: register, login, refresh, pending-status check, city change."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_app_settings, get_rate_limiter
from app.config import Settings
from app.db import get_db
from app.models import ApprovalState, City, Role, User
from app.security import (
    RateLimiter,
    TokenError,
    create_token,
    decode_token,
    hash_password,
    new_secret_token,
    sha256_hex,
    verify_password,
)
from app.ws import revoke_live_access

router = APIRouter(prefix="/api/auth", tags=["auth"])


# --- schemas -----------------------------------------------------------------


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=1, max_length=40)
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    city_id: int


class RegisterOut(BaseModel):
    user_id: int
    approval_state: ApprovalState
    # Bearer secret for POST /registration-status; shown once.
    registration_token: str


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=256)


class RefreshIn(BaseModel):
    refresh_token: str


class RegistrationStatusIn(BaseModel):
    registration_token: str


class RegistrationStatusOut(BaseModel):
    approval_state: ApprovalState


class CityChangeIn(BaseModel):
    city_id: int


class CityChangeOut(BaseModel):
    approval_state: ApprovalState
    requested_city_id: int
    registration_token: str


class UserOut(BaseModel):
    id: int
    name: str
    phone: str
    email: str
    role: Role
    approval_state: ApprovalState
    approved_city_id: int | None
    requested_city_id: int | None

    model_config = {"from_attributes": True}


class TokensOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


# --- helpers -----------------------------------------------------------------


def _client_ip(request: Request) -> str:
    # Behind Caddy, uvicorn must run with --proxy-headers so this is the real client.
    return request.client.host if request.client else "unknown"


def _too_many(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=detail)


def _not_approved(user: User) -> HTTPException:
    detail: dict[str, Any] = {"code": "not_approved", "approval_state": user.approval_state.value}
    return HTTPException(status.HTTP_403_FORBIDDEN, detail=detail)


def _issue_registration_token(user: User) -> str:
    token = new_secret_token()
    user.registration_token_hash = sha256_hex(token)
    return token


def _tokens_for(settings: Settings, user: User) -> TokensOut:
    return TokensOut(
        access_token=create_token(settings, user.id, "access"),
        refresh_token=create_token(settings, user.id, "refresh"),
        user=UserOut.model_validate(user),
    )


# --- endpoints ---------------------------------------------------------------


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=RegisterOut)
def register(
    body: RegisterIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> RegisterOut:
    email = body.email.lower()
    window = settings.register_ip_window_s
    if not limiter.hit(f"register-ip:{_client_ip(request)}", settings.register_ip_limit, window):
        raise _too_many("too many registrations from this address")
    if not limiter.hit(f"register-acct:{email}", settings.register_account_limit, window):
        raise _too_many("too many registration attempts for this email")

    if db.get(City, body.city_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="city not found")
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="email already registered")

    user = User(
        name=body.name.strip(),
        phone=body.phone.strip(),
        email=email,
        password_hash=hash_password(body.password),
        role=Role.MAINTAINER,
        approval_state=ApprovalState.PENDING,
        requested_city_id=body.city_id,
    )
    token = _issue_registration_token(user)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # concurrent registration with the same email
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="email already registered") from None
    return RegisterOut(user_id=user.id, approval_state=user.approval_state, registration_token=token)


@router.post("/login", response_model=TokensOut)
def login(
    body: LoginIn,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> TokensOut:
    """Tokens for approved users only. Non-approved users get 403 with their state (KTD10)."""
    email = body.email.lower()
    account_key = f"login-fail:{email}"
    if not limiter.hit(f"login-ip:{_client_ip(request)}", settings.login_ip_limit, settings.login_ip_window_s):
        raise _too_many("too many login attempts from this address")
    if limiter.is_locked(account_key):
        raise _too_many("account temporarily locked after repeated failed logins")

    user = db.scalar(select(User).where(User.email == email))
    if not verify_password(user.password_hash if user else None, body.password) or user is None:
        limiter.hit(account_key, settings.login_max_failures + 1, settings.login_failure_window_s)
        if limiter.count(account_key, settings.login_failure_window_s) >= settings.login_max_failures:
            limiter.lock(account_key, settings.login_lockout_s)
            limiter.reset(account_key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid email or password")
    limiter.reset(account_key)

    if user.approval_state != ApprovalState.APPROVED:
        # No token here: the pending screen polls with the registration token, and
        # rotating it on every login would break another device's polling.
        raise _not_approved(user)

    return _tokens_for(settings, user)


@router.post("/refresh", response_model=TokensOut)
def refresh(
    body: RefreshIn, db: Session = Depends(get_db), settings: Settings = Depends(get_app_settings)
) -> TokensOut:
    try:
        user_id = decode_token(settings, body.refresh_token, "refresh")
    except TokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid refresh token") from None
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="access revoked")
    if user.approval_state != ApprovalState.APPROVED:
        # Same shape as login, so the app routes to the pending / rejected / disabled screen (R20).
        raise _not_approved(user)
    return _tokens_for(settings, user)


@router.post("/registration-status", response_model=RegistrationStatusOut)
def registration_status(body: RegistrationStatusIn, db: Session = Depends(get_db)) -> RegistrationStatusOut:
    """Unauthenticated approval check for the pending screen (R20)."""
    user = db.scalar(select(User).where(User.registration_token_hash == sha256_hex(body.registration_token)))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="unknown registration")
    return RegistrationStatusOut(approval_state=user.approval_state)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> User:
    return user


@router.post("/city-change", response_model=CityChangeOut)
def city_change(
    body: CityChangeIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> CityChangeOut:
    """Request another city; the user returns to pending until an admin approves (R22)."""
    if user.role == Role.ADMIN:
        # Admins read every city; going pending could lock out the only admin.
        raise HTTPException(status.HTTP_409_CONFLICT, detail="admins already have access to every city")
    if db.get(City, body.city_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="city not found")
    if body.city_id == user.approved_city_id:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="already approved for this city")
    user.requested_city_id = body.city_id
    user.approval_state = ApprovalState.PENDING
    token = _issue_registration_token(user)
    db.commit()
    revoke_live_access(request.app, db, user.id)
    return CityChangeOut(approval_state=user.approval_state, requested_city_id=body.city_id, registration_token=token)

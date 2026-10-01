"""Expo push token registration (R22).

The app posts its token on every foreground, so POST is an upsert. A token is
unique: when another user logs in on the same phone it moves to that user.
DELETE (on logout) removes the token only if it belongs to the caller.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.db import get_db, utcnow
from app.models import PushToken, User

router = APIRouter(prefix="/api/push-tokens", tags=["push"])


class PushTokenIn(BaseModel):
    token: str = Field(min_length=1, max_length=255)
    platform: str | None = Field(default=None, max_length=16)


class PushTokenDeleteIn(BaseModel):
    token: str = Field(min_length=1, max_length=255)


def _upsert(db: Session, user: User, body: PushTokenIn) -> None:
    row = db.scalar(select(PushToken).where(PushToken.token == body.token))
    now = utcnow()
    if row is None:
        db.add(PushToken(user_id=user.id, token=body.token, platform=body.platform, created_at=now, last_seen_at=now))
    else:
        row.user_id = user.id
        row.platform = body.platform
        row.last_seen_at = now
    db.commit()


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
def register_push_token(
    body: PushTokenIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Response:
    _upsert(db, user, body)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_push_token(
    body: PushTokenDeleteIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Response:
    db.execute(delete(PushToken).where(PushToken.token == body.token, PushToken.user_id == user.id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

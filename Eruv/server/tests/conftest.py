"""Shared fixtures: a fresh SQLite database and app per test.

Production runs PostgreSQL; the models are kept portable so tests can use a
throwaway SQLite file (no Docker/PostgreSQL on the dev machine).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import Base
from app.main import create_app
from app.models import User
from app.models.user import ApprovalState, Role
from app.security import hash_password

ADMIN_EMAIL = "admin@example.org"
ADMIN_PASSWORD = "admin-password-123"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'test.db').as_posix()}",
        jwt_secret="test-secret-" + "x" * 40,
        public_base_url="https://testserver",
        # Tests drive the watchdog with an injected clock (tests/test_ingest.py).
        watchdog_enabled=False,
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    application = create_app(settings)
    Base.metadata.create_all(application.state.engine)
    return application


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db(app: FastAPI) -> Iterator[Session]:
    session: Session = app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def admin_headers(client: TestClient, db: Session) -> dict[str, str]:
    """Seed an approved admin directly in the database and log in over HTTP."""
    db.add(
        User(
            name="Admin",
            phone="050-0000000",
            email=ADMIN_EMAIL,
            password_hash=hash_password(ADMIN_PASSWORD),
            role=Role.ADMIN,
            approval_state=ApprovalState.APPROVED,
        )
    )
    db.commit()
    response = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert response.status_code == 200, response.text
    return bearer(response.json()["access_token"])


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_city(client: TestClient, admin_headers: dict[str, str], name: str) -> int:
    response = client.post("/api/admin/cities", json={"name": name}, headers=admin_headers)
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def register(
    client: TestClient, email: str, city_id: int, password: str = "correct-horse-battery"
) -> dict[str, Any]:
    response = client.post(
        "/api/auth/register",
        json={
            "name": "Maintainer",
            "phone": "050-1234567",
            "email": email,
            "password": password,
            "city_id": city_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()

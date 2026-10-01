"""`python -m app.cli create-admin` bootstraps the first admin (runbook step)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.cli import PASSWORD_ENV, main
from app.config import Settings

EMAIL = "First.Admin@Example.org"
PASSWORD = "bootstrap-password-1"


def _args(email: str = EMAIL) -> list[str]:
    return ["create-admin", "--email", email, "--name", "First Admin", "--phone", "050-1111111"]


def test_created_admin_can_log_in_and_use_admin_api(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(PASSWORD_ENV, PASSWORD)
    assert main(_args(), settings=settings) == 0

    login = client.post("/api/auth/login", json={"email": EMAIL.lower(), "password": PASSWORD})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    users = client.get("/api/admin/users", headers=headers)
    assert users.status_code == 200, users.text
    [admin] = users.json()
    assert admin["email"] == EMAIL.lower()
    assert admin["role"] == "admin"
    assert admin["approval_state"] == "approved"


def test_password_prompt_must_match(client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PASSWORD_ENV, raising=False)
    answers = iter([PASSWORD, "something-else"])
    assert main(_args(), settings=settings, prompt=lambda _: next(answers)) == 1

    answers = iter([PASSWORD, PASSWORD])
    assert main(_args(), settings=settings, prompt=lambda _: next(answers)) == 0
    login = client.post("/api/auth/login", json={"email": EMAIL.lower(), "password": PASSWORD})
    assert login.status_code == 200, login.text


def test_refuses_duplicate_email_and_short_password(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(PASSWORD_ENV, "short")
    assert main(_args(), settings=settings) == 1

    monkeypatch.setenv(PASSWORD_ENV, PASSWORD)
    assert main(_args(), settings=settings) == 0
    assert main(_args(EMAIL.upper()), settings=settings) == 1

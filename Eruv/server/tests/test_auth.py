"""U4 auth, scoping and data-model tests, exercised through the HTTP API."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from conftest import bearer, create_city, register
from app.api.deps import current_device
from app.models import Device, Pole

PASSWORD = "correct-horse-battery"


def login(client: TestClient, email: str, password: str = PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def approve(client: TestClient, admin_headers: dict[str, str], user_id: int) -> None:
    response = client.post(f"/api/admin/users/{user_id}/approve", headers=admin_headers)
    assert response.status_code == 200, response.text
    assert response.json()["approval_state"] == "approved"


def approved_maintainer(
    client: TestClient, admin_headers: dict[str, str], email: str, city_id: int
) -> dict:
    reg = register(client, email, city_id)
    approve(client, admin_headers, reg["user_id"])
    response = login(client, email)
    assert response.status_code == 200, response.text
    return response.json()


def test_public_city_list_for_registration(client: TestClient, admin_headers: dict[str, str]) -> None:
    city_id = create_city(client, admin_headers, "Beer Sheva")
    response = client.get("/api/cities")
    assert response.status_code == 200
    assert response.json() == [{"id": city_id, "name": "Beer Sheva"}]


def test_login_before_approval_is_pending_and_issues_no_token(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    city_id = create_city(client, admin_headers, "Beer Sheva")
    reg = register(client, "m@example.org", city_id)
    assert reg["approval_state"] == "pending"
    assert reg["registration_token"]

    response = login(client, "m@example.org")
    assert response.status_code == 403
    body = response.json()
    assert body["detail"]["approval_state"] == "pending"
    assert "access_token" not in response.text
    assert "refresh_token" not in response.text


def test_registration_status_check_reports_approval(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    city_id = create_city(client, admin_headers, "Beer Sheva")
    reg = register(client, "m@example.org", city_id)
    token = reg["registration_token"]

    status = client.post("/api/auth/registration-status", json={"registration_token": token})
    assert status.status_code == 200
    assert status.json()["approval_state"] == "pending"

    approve(client, admin_headers, reg["user_id"])
    status = client.post("/api/auth/registration-status", json={"registration_token": token})
    assert status.json()["approval_state"] == "approved"

    unknown = client.post("/api/auth/registration-status", json={"registration_token": "nope"})
    assert unknown.status_code == 404


def test_duplicate_email_registration_is_rejected(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    city_id = create_city(client, admin_headers, "Beer Sheva")
    register(client, "m@example.org", city_id)
    response = client.post(
        "/api/auth/register",
        json={
            "name": "Other",
            "phone": "050",
            "email": "M@Example.org",
            "password": PASSWORD,
            "city_id": city_id,
        },
    )
    assert response.status_code == 409


def test_wrong_password_is_401_and_repeated_failures_lock_the_account(
    client: TestClient, admin_headers: dict[str, str], settings
) -> None:
    city_id = create_city(client, admin_headers, "Beer Sheva")
    reg = register(client, "m@example.org", city_id)
    approve(client, admin_headers, reg["user_id"])

    response = login(client, "m@example.org", "wrong-password")
    assert response.status_code == 401
    assert "access_token" not in response.text

    for _ in range(settings.login_max_failures - 1):
        assert login(client, "m@example.org", "wrong-password").status_code == 401

    # Account is now locked: even the correct password is refused for a while.
    locked = login(client, "m@example.org")
    assert locked.status_code == 429
    assert "access_token" not in locked.text


def test_login_is_rate_limited_per_ip(client: TestClient, settings) -> None:
    for i in range(settings.login_ip_limit):
        assert login(client, f"nobody{i}@example.org").status_code == 401
    assert login(client, "another@example.org").status_code == 429


def test_register_is_rate_limited_per_ip(client: TestClient, admin_headers: dict[str, str], settings) -> None:
    city_id = create_city(client, admin_headers, "Beer Sheva")
    for i in range(settings.register_ip_limit):
        register(client, f"user{i}@example.org", city_id)
    response = client.post(
        "/api/auth/register",
        json={"name": "x", "phone": "1", "email": "last@example.org", "password": PASSWORD, "city_id": city_id},
    )
    assert response.status_code == 429


def test_approved_login_issues_tokens_and_disable_revokes_them(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    city_id = create_city(client, admin_headers, "Beer Sheva")
    reg = register(client, "m@example.org", city_id)
    approve(client, admin_headers, reg["user_id"])

    tokens = login(client, "m@example.org").json()
    assert tokens["access_token"] and tokens["refresh_token"]
    me = client.get("/api/auth/me", headers=bearer(tokens["access_token"]))
    assert me.status_code == 200
    assert me.json()["approved_city_id"] == city_id

    refreshed = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]

    response = client.post(f"/api/admin/users/{reg['user_id']}/disable", headers=admin_headers)
    assert response.status_code == 200

    # The access token is still unexpired, but the user is reloaded on every request.
    assert client.get("/api/auth/me", headers=bearer(tokens["access_token"])).status_code == 401
    assert client.get(f"/api/cities/{city_id}/status", headers=bearer(tokens["access_token"])).status_code == 401
    # Refresh reports the state (not a bare 401) so the app shows the "disabled" screen (R20).
    refused = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refused.status_code == 403
    assert refused.json()["detail"] == {"code": "not_approved", "approval_state": "disabled"}
    # Login now reports the disabled state and issues nothing.
    disabled = login(client, "m@example.org")
    assert disabled.status_code == 403
    assert disabled.json()["detail"]["approval_state"] == "disabled"


def test_rejected_user_gets_no_token(client: TestClient, admin_headers: dict[str, str]) -> None:
    city_id = create_city(client, admin_headers, "Beer Sheva")
    reg = register(client, "m@example.org", city_id)
    assert client.post(f"/api/admin/users/{reg['user_id']}/reject", headers=admin_headers).status_code == 200
    response = login(client, "m@example.org")
    assert response.status_code == 403
    assert response.json()["detail"]["approval_state"] == "rejected"


def test_refresh_for_rejected_user_reports_not_approved(client: TestClient, admin_headers: dict[str, str]) -> None:
    city_id = create_city(client, admin_headers, "Beer Sheva")
    reg = register(client, "m@example.org", city_id)
    approve(client, admin_headers, reg["user_id"])
    tokens = login(client, "m@example.org").json()
    assert client.post(f"/api/admin/users/{reg['user_id']}/reject", headers=admin_headers).status_code == 200
    refused = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refused.status_code == 403
    assert refused.json()["detail"] == {"code": "not_approved", "approval_state": "rejected"}
    # An invalid refresh token is still a plain 401.
    assert client.post("/api/auth/refresh", json={"refresh_token": "garbage"}).status_code == 401


def test_access_token_cannot_be_used_as_refresh_token(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    city_id = create_city(client, admin_headers, "Beer Sheva")
    tokens = approved_maintainer(client, admin_headers, "m@example.org", city_id)
    assert client.post("/api/auth/refresh", json={"refresh_token": tokens["access_token"]}).status_code == 401
    assert client.get("/api/auth/me", headers=bearer(tokens["refresh_token"])).status_code == 401


def test_city_change_returns_user_to_pending_until_admin_approves(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    city_a = create_city(client, admin_headers, "Beer Sheva")
    city_b = create_city(client, admin_headers, "Ashdod")
    tokens = approved_maintainer(client, admin_headers, "m@example.org", city_a)
    headers = bearer(tokens["access_token"])
    assert client.get(f"/api/cities/{city_a}/status", headers=headers).status_code == 200

    change = client.post("/api/auth/city-change", json={"city_id": city_b}, headers=headers)
    assert change.status_code == 200
    assert change.json()["approval_state"] == "pending"
    reg_token = change.json()["registration_token"]

    # Neither the old nor the new city is readable while pending.
    assert client.get(f"/api/cities/{city_a}/status", headers=headers).status_code == 401
    assert client.get(f"/api/cities/{city_b}/status", headers=headers).status_code == 401
    refused = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refused.status_code == 403
    assert refused.json()["detail"] == {"code": "not_approved", "approval_state": "pending"}
    assert login(client, "m@example.org").status_code == 403

    pending = client.get("/api/admin/users", params={"approval_state": "pending"}, headers=admin_headers)
    assert pending.status_code == 200
    [row] = pending.json()
    assert row["requested_city_id"] == city_b

    approve(client, admin_headers, row["id"])
    status = client.post("/api/auth/registration-status", json={"registration_token": reg_token})
    assert status.json()["approval_state"] == "approved"

    new_headers = bearer(login(client, "m@example.org").json()["access_token"])
    assert client.get(f"/api/cities/{city_b}/status", headers=new_headers).status_code == 200
    assert client.get(f"/api/cities/{city_a}/status", headers=new_headers).status_code == 403
    me = client.get("/api/auth/me", headers=new_headers).json()
    assert me["approved_city_id"] == city_b
    assert me["requested_city_id"] is None


def test_maintainer_of_city_a_gets_403_for_city_b(client: TestClient, admin_headers: dict[str, str]) -> None:
    city_a = create_city(client, admin_headers, "Beer Sheva")
    city_b = create_city(client, admin_headers, "Ashdod")
    tokens = approved_maintainer(client, admin_headers, "m@example.org", city_a)
    headers = bearer(tokens["access_token"])

    own = client.get(f"/api/cities/{city_a}/status", headers=headers)
    assert own.status_code == 200
    assert own.json()["line_state"] == "AWAITING_REFERENCE"
    assert own.json()["device_health"] == "DISCONNECTED"

    assert client.get(f"/api/cities/{city_b}/status", headers=headers).status_code == 403
    # Admins may read any city.
    assert client.get(f"/api/cities/{city_b}/status", headers=admin_headers).status_code == 200


def test_admin_endpoints_require_admin(client: TestClient, admin_headers: dict[str, str]) -> None:
    city_id = create_city(client, admin_headers, "Beer Sheva")
    tokens = approved_maintainer(client, admin_headers, "m@example.org", city_id)
    headers = bearer(tokens["access_token"])
    assert client.get("/api/admin/users", headers=headers).status_code == 403
    assert client.post("/api/admin/cities", json={"name": "X"}, headers=headers).status_code == 403
    assert client.get("/api/admin/users").status_code == 401


@pytest.fixture
def device_probe(app: FastAPI) -> None:
    """Mount a probe route that only resolves the device-auth dependency (ingest arrives in U5)."""

    @app.get("/api/device/v1/_probe")
    def probe(device: Device = Depends(current_device)) -> dict[str, int]:
        return {"device_id": device.id, "city_id": device.city_id}


def test_device_key_resolves_to_its_own_city_and_rotation_revokes_old_key(
    client: TestClient, admin_headers: dict[str, str], device_probe: None
) -> None:
    city_a = create_city(client, admin_headers, "Beer Sheva")
    city_b = create_city(client, admin_headers, "Ashdod")

    key_a = client.post(f"/api/admin/cities/{city_a}/device-key", headers=admin_headers)
    key_b = client.post(f"/api/admin/cities/{city_b}/device-key", headers=admin_headers)
    assert key_a.status_code == 201 and key_b.status_code == 201
    plain_a = key_a.json()["api_key"]

    assert client.get("/api/device/v1/_probe").status_code == 401
    assert client.get("/api/device/v1/_probe", headers={"X-Device-Key": "unknown"}).status_code == 401

    resolved = client.get("/api/device/v1/_probe", headers={"X-Device-Key": plain_a})
    assert resolved.status_code == 200
    assert resolved.json() == {"device_id": key_a.json()["device_id"], "city_id": city_a}
    resolved_b = client.get("/api/device/v1/_probe", headers={"X-Device-Key": key_b.json()["api_key"]})
    assert resolved_b.json()["city_id"] == city_b

    rotated = client.post(f"/api/admin/cities/{city_a}/device-key", headers=admin_headers)
    assert rotated.status_code == 201
    assert rotated.json()["device_id"] == key_a.json()["device_id"]
    assert client.get("/api/device/v1/_probe", headers={"X-Device-Key": plain_a}).status_code == 401
    assert (
        client.get("/api/device/v1/_probe", headers={"X-Device-Key": rotated.json()["api_key"]}).json()["city_id"]
        == city_a
    )


def test_device_key_plaintext_is_not_stored(
    client: TestClient, admin_headers: dict[str, str], db: Session
) -> None:
    city_id = create_city(client, admin_headers, "Beer Sheva")
    plain = client.post(f"/api/admin/cities/{city_id}/device-key", headers=admin_headers).json()["api_key"]
    device = db.query(Device).one()
    assert plain not in device.api_key_hash
    assert len(plain) >= 43  # 32 random bytes, url-safe base64


def test_duplicate_pole_number_within_a_city_is_rejected_by_the_database(
    client: TestClient, admin_headers: dict[str, str], db: Session
) -> None:
    city_a = create_city(client, admin_headers, "Beer Sheva")
    city_b = create_city(client, admin_headers, "Ashdod")
    db.add_all(
        [
            Pole(city_id=city_a, number=1, lat=31.25, lon=34.79),
            Pole(city_id=city_b, number=1, lat=31.80, lon=34.65),  # same number, other city: fine
        ]
    )
    db.commit()

    db.add(Pole(city_id=city_a, number=1, lat=31.26, lon=34.80))
    with pytest.raises(IntegrityError):
        db.commit()

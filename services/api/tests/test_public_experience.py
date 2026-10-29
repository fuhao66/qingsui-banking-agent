from decimal import Decimal

from fastapi.testclient import TestClient

from app.core.config import settings


def login(client: TestClient, name: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/experience",
        json={"invite_code": "TEST-INVITE", "display_name": name},
    )
    assert response.status_code == 200
    return response.json()


def bearer(session: dict[str, object]) -> dict[str, str]:
    return {"Authorization": f"Bearer {session['access_token']}"}


def test_public_mode_requires_invite_and_bearer_token(
    api_client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "public_demo_mode", True)
    monkeypatch.setattr(settings, "public_invite_code", "TEST-INVITE")

    unauthorized = api_client.get("/api/v1/accounts")
    assert unauthorized.status_code == 401
    assert unauthorized.json()["detail"]["code"] == "EXPERIENCE_TOKEN_REQUIRED"

    invalid = api_client.post(
        "/api/v1/auth/experience",
        json={"invite_code": "WRONG-CODE", "display_name": "访客"},
    )
    assert invalid.status_code == 403
    session = login(api_client, "王老师")
    profile = api_client.get("/api/v1/auth/me", headers=bearer(session))
    assert profile.status_code == 200
    assert profile.json()["display_name"] == "王老师"
    assert api_client.get("/api/v1/accounts", headers=bearer(session)).status_code == 200


def test_experience_users_have_isolated_banking_data(
    api_client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "public_demo_mode", True)
    monkeypatch.setattr(settings, "public_invite_code", "TEST-INVITE")
    first = login(api_client, "体验者甲")
    second = login(api_client, "体验者乙")
    first_headers, second_headers = bearer(first), bearer(second)

    run = api_client.post(
        "/api/v1/agent/runs",
        headers=first_headers,
        json={"message": "给妈妈转100元", "channel": "app"},
    ).json()
    completed = api_client.post(
        f"/api/v1/agent/runs/{run['id']}/resume",
        headers=first_headers,
        json={"confirmed": True},
    )
    assert completed.status_code == 200

    first_balance = Decimal(
        api_client.get("/api/v1/accounts", headers=first_headers).json()["items"][0]["balance"]
    )
    second_balance = Decimal(
        api_client.get("/api/v1/accounts", headers=second_headers).json()["items"][0]["balance"]
    )
    assert first_balance == Decimal("28540.52")
    assert second_balance == Decimal("28640.52")

    reset = api_client.post(
        "/api/v1/demo/reset",
        headers=first_headers,
        json={"confirmation": "RESET_DEMO_DATA"},
    )
    assert reset.status_code == 200
    assert reset.json()["user_id"] == first["user_id"]
    restored = api_client.get("/api/v1/accounts", headers=first_headers).json()
    assert restored["items"][0]["balance"] == "28640.52"
    assert api_client.get("/api/v1/agent/runs", headers=first_headers).json() == []


def test_admin_stats_and_logout_are_protected(api_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "public_demo_mode", True)
    monkeypatch.setattr(settings, "public_invite_code", "TEST-INVITE")
    monkeypatch.setattr(settings, "admin_api_token", "TEST-ADMIN")
    session = login(api_client, "评委")
    headers = bearer(session)
    api_client.get("/api/v1/accounts", headers=headers)

    assert api_client.get("/api/v1/admin/experience-stats").status_code == 403
    stats = api_client.get(
        "/api/v1/admin/experience-stats", headers={"X-Admin-Token": "TEST-ADMIN"}
    )
    assert stats.status_code == 200
    assert stats.json()["total_sessions"] == 1
    assert stats.json()["active_sessions"] == 1
    assert stats.json()["total_requests"] >= 1

    logged_out = api_client.post("/api/v1/auth/logout", headers=headers)
    assert logged_out.status_code == 200
    assert api_client.get("/api/v1/accounts", headers=headers).status_code == 401


def test_experience_rate_limit_is_enforced(api_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "public_demo_mode", True)
    monkeypatch.setattr(settings, "public_invite_code", "TEST-INVITE")
    monkeypatch.setattr(settings, "experience_requests_per_minute", 2)
    session = login(api_client, "限流测试")
    headers = bearer(session)

    assert api_client.get("/api/v1/accounts", headers=headers).status_code == 200
    assert api_client.get("/api/v1/accounts", headers=headers).status_code == 200
    limited = api_client.get("/api/v1/accounts", headers=headers)
    assert limited.status_code == 429
    assert limited.json()["detail"]["code"] == "EXPERIENCE_RATE_LIMITED"

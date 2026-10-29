from fastapi.testclient import TestClient

from app.core.config import settings
from app.domain.constants import DEMO_CHECKING_ACCOUNT_ID


def test_demo_reset_restores_seed_data_and_writes_fresh_audit(
    api_client: TestClient,
) -> None:
    run = api_client.post(
        "/api/v1/agent/runs",
        json={"message": "给妈妈转100元", "channel": "app"},
    ).json()
    completed = api_client.post(
        f"/api/v1/agent/runs/{run['id']}/resume",
        json={"confirmed": True},
    )
    assert completed.status_code == 200

    changed = api_client.get(f"/api/v1/accounts/{DEMO_CHECKING_ACCOUNT_ID}").json()
    assert changed["balance"] == "28540.52"

    occasion = api_client.post(
        "/api/v1/agent/runs",
        json={
            "message": "我爱人9月20日生日，预算1000元，提前2天准备鲜花",
            "channel": "app",
        },
    ).json()
    api_client.post(
        f"/api/v1/agent/runs/{occasion['id']}/resume", json={"confirmed": True}
    )
    assert api_client.get("/api/v1/scheduled-tasks").json()["total"] == 1

    response = api_client.post(
        "/api/v1/demo/reset",
        json={"confirmation": "RESET_DEMO_DATA"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "reset"
    restored = api_client.get(f"/api/v1/accounts/{DEMO_CHECKING_ACCOUNT_ID}").json()
    assert restored["balance"] == "28640.52"
    runs = api_client.get("/api/v1/agent/runs").json()
    assert runs == []
    assert api_client.get("/api/v1/scheduled-tasks").json()["total"] == 0
    audit = api_client.get("/api/v1/security/audit-events?limit=5").json()
    assert audit["chain_valid"] is True
    assert audit["items"][0]["action"] == "demo.data.reset"


def test_demo_reset_requires_confirmation_and_development_environment(
    api_client: TestClient, monkeypatch
) -> None:
    invalid = api_client.post(
        "/api/v1/demo/reset",
        json={"confirmation": "RESET"},
    )
    assert invalid.status_code == 422

    monkeypatch.setattr(settings, "app_env", "production")
    disabled = api_client.post(
        "/api/v1/demo/reset",
        json={"confirmation": "RESET_DEMO_DATA"},
    )
    assert disabled.status_code == 403
    assert disabled.json()["detail"]["code"] == "DEMO_RESET_DISABLED"

from fastapi.testclient import TestClient

from app.main import app


def test_live_health_check() -> None:
    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Banking Agent API",
        "version": "0.7.0",
    }


def test_system_status_exposes_roadmap() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    components = {item["name"]: item for item in response.json()["components"]}
    assert components["api"]["status"] == "available"
    assert components["agent_graph"]["status"] == "available"
    assert components["human_handoff"]["status"] == "available"

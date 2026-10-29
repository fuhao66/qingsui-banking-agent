from decimal import Decimal

from fastapi.testclient import TestClient

from app.domain.constants import DEMO_CHECKING_ACCOUNT_ID


def create_run(client: TestClient, message: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/agent/runs", json={"message": message, "channel": "app"}
    )
    assert response.status_code == 201
    return response.json()


def test_occasion_plan_creates_confirmed_reservation_and_task(
    api_client: TestClient,
) -> None:
    before = Decimal(
        api_client.get(f"/api/v1/accounts/{DEMO_CHECKING_ACCOUNT_ID}").json()["balance"]
    )
    run = create_run(
        api_client,
        "我爱人9月20日生日，预算1000元，提前2天准备鲜花和蛋糕",
    )

    assert run["intent"] == "occasion.plan"
    assert run["status"] == "waiting_confirmation"
    assert len(run["plan"]) == 6
    assert run["pending_action"]["type"] == "occasion_confirmation"
    assert run["pending_action"]["details"]["budget"] == "1000"
    assert len(run["pending_action"]["details"]["items"]) == 4
    assert Decimal(
        api_client.get(f"/api/v1/accounts/{DEMO_CHECKING_ACCOUNT_ID}").json()["balance"]
    ) == before

    confirmed = api_client.post(
        f"/api/v1/agent/runs/{run['id']}/resume", json={"confirmed": True}
    )
    assert confirmed.status_code == 200
    completed = confirmed.json()
    assert completed["status"] == "completed"
    assert Decimal(completed["result"]["reserved_amount"]) == Decimal("1000.00")

    task_list = api_client.get("/api/v1/scheduled-tasks").json()
    assert task_list["total"] == 1
    assert task_list["active_reserved_amount"] == "1000.00"
    assert task_list["items"][0]["status"] == "scheduled"
    assert Decimal(
        api_client.get(f"/api/v1/accounts/{DEMO_CHECKING_ACCOUNT_ID}").json()["balance"]
    ) == before


def test_task_state_machine_releases_budget_on_cancel(api_client: TestClient) -> None:
    run = create_run(api_client, "我爱人9月20日生日，预算1000元，提前2天准备鲜花")
    completed = api_client.post(
        f"/api/v1/agent/runs/{run['id']}/resume", json={"confirmed": True}
    ).json()
    task_id = completed["result"]["task_id"]

    paused = api_client.post(
        f"/api/v1/scheduled-tasks/{task_id}/actions",
        json={"action": "pause", "confirmed": True},
    )
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"

    resumed = api_client.post(
        f"/api/v1/scheduled-tasks/{task_id}/actions",
        json={"action": "resume", "confirmed": True},
    )
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "scheduled"

    cancelled = api_client.post(
        f"/api/v1/scheduled-tasks/{task_id}/actions",
        json={"action": "cancel", "confirmed": True},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert Decimal(cancelled.json()["reserved_amount"]) == Decimal(0)

    invalid = api_client.post(
        f"/api/v1/scheduled-tasks/{task_id}/actions",
        json={"action": "resume", "confirmed": True},
    )
    assert invalid.status_code == 409
    assert invalid.json()["detail"]["code"] == "INVALID_TASK_TRANSITION"

    audit = api_client.get("/api/v1/security/audit-events?limit=20").json()
    actions = {event["action"] for event in audit["items"]}
    assert {"scheduled_task.pause", "scheduled_task.resume", "scheduled_task.cancel"} <= actions
    assert audit["chain_valid"] is True


def test_occasion_plan_completes_missing_slots_and_rejects_overbooking(
    api_client: TestClient,
) -> None:
    incomplete = create_run(api_client, "帮我准备爱人的生日惊喜")
    assert incomplete["status"] == "waiting_clarification"
    assert set(incomplete["pending_action"]["fields"]) == {"event_date", "budget"}

    clarified = api_client.post(
        f"/api/v1/agent/runs/{incomplete['id']}/resume",
        json={"clarification_message": "9月20日，预算1000元，提前2天"},
    )
    assert clarified.status_code == 200
    assert clarified.json()["status"] == "waiting_confirmation"

    over_budget = create_run(
        api_client,
        "我爱人10月20日生日，预算10万元，提前2天准备鲜花和蛋糕",
    )
    assert over_budget["status"] == "failed"
    assert over_budget["error_code"] == "INSUFFICIENT_AVAILABLE_BUDGET"


def test_task_action_requires_explicit_confirmation(api_client: TestClient) -> None:
    run = create_run(api_client, "我爱人9月20日生日，预算1000元，提前2天准备鲜花")
    completed = api_client.post(
        f"/api/v1/agent/runs/{run['id']}/resume", json={"confirmed": True}
    ).json()
    task_id = completed["result"]["task_id"]

    response = api_client.post(
        f"/api/v1/scheduled-tasks/{task_id}/actions",
        json={"action": "pause", "confirmed": False},
    )
    assert response.status_code == 422

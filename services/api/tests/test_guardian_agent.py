from decimal import Decimal

from fastapi.testclient import TestClient

from app.domain.constants import DEMO_CHECKING_ACCOUNT_ID, DEMO_PRIMARY_PAYEE_ID


def balance(client: TestClient) -> Decimal:
    response = client.get(f"/api/v1/accounts/{DEMO_CHECKING_ACCOUNT_ID}")
    assert response.status_code == 200
    return Decimal(response.json()["balance"])


def test_guardian_blocks_scam_evidence_before_business_side_effects(
    api_client: TestClient,
) -> None:
    before = balance(api_client)
    response = api_client.post(
        "/api/v1/agent/evidence-runs",
        json={
            "message": "请判断这段聊天是否安全",
            "evidence_text": "公安说我涉案，让我立即转钱到安全账户，不要告诉家人，还要提供验证码。",
            "channel": "app",
        },
    )
    assert response.status_code == 201
    run = response.json()
    assert run["intent"] == "fraud.assess"
    assert run["status"] == "human_review"
    assert run["guardian"]["disposition"] == "block"
    assert run["guardian"]["scam_score"] >= 65
    assert [node["id"] for node in run["plan"]] == [
        "guardian_review", "fraud_policy_block", "human_handoff"
    ]
    assert run["guardian"]["receipt_hash"]
    assert balance(api_client) == before

    receipt = api_client.get(
        f"/api/v1/agent/runs/{run['id']}/decision-receipt"
    )
    assert receipt.status_code == 200
    assert receipt.json()["receipt"]["guardian"]["disposition"] == "block"


def test_guardian_reroutes_small_transfer_to_strong_auth(
    api_client: TestClient,
) -> None:
    before = balance(api_client)
    response = api_client.post(
        "/api/v1/agent/runs",
        json={"message": "客服让我马上给小王转300元", "channel": "app"},
    )
    assert response.status_code == 201
    run = response.json()
    assert run["intent"] == "transfer.create"
    assert run["guardian"]["disposition"] == "step_up"
    assert run["guardian"]["original_risk"] == "yellow"
    assert run["guardian"]["effective_risk"] == "red"
    if run["status"] == "waiting_clarification":
        resumed = api_client.post(
            f"/api/v1/agent/runs/{run['id']}/resume",
            json={"selected_payee_id": DEMO_PRIMARY_PAYEE_ID},
        )
        assert resumed.status_code == 200
        run = resumed.json()
    assert run["status"] == "waiting_auth"
    assert run["pending_action"]["type"] == "strong_authentication"
    assert balance(api_client) == before


def test_evidence_image_type_is_rejected_before_model_call(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/v1/agent/evidence-runs",
        json={
            "message": "帮我看看附件是否安全",
            "image_data_url": "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",
            "channel": "app",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "UNSUPPORTED_EVIDENCE_IMAGE"

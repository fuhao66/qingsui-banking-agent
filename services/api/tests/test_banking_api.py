from fastapi.testclient import TestClient

from app.domain.constants import DEMO_CHECKING_ACCOUNT_ID, DEMO_PRIMARY_PAYEE_ID


def test_profile_and_accounts(api_client: TestClient) -> None:
    profile = api_client.get("/api/v1/users/me")
    accounts = api_client.get("/api/v1/accounts")

    assert profile.status_code == 200
    assert profile.json()["display_name"] == "刘女士"
    assert accounts.status_code == 200
    assert accounts.json()["total"] == 2
    assert accounts.json()["total_balance"] == "80640.52"


def test_transactions_support_filtering_and_pagination(api_client: TestClient) -> None:
    response = api_client.get(
        "/api/v1/transactions",
        params={"category": "subscription", "limit": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 36
    assert len(payload["items"]) == 5
    assert all(item["category"] == "subscription" for item in payload["items"])


def test_bill_summary_is_calculated_from_ledger(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/bill-summary", params={"month": "2026-08"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["month"] == "2026-08"
    assert payload["transaction_count"] > 10
    assert payload["suspicious_count"] == 1
    assert payload["outflow_change_percent"] is not None
    assert payload["categories"][0]["category"] == "housing"


def test_payee_search_surfaces_ambiguity(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/payees/search", params={"q": "小王"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["requires_disambiguation"] is True
    assert {item["name"] for item in payload["items"]} == {"王小明", "王晓"}


def test_active_subscriptions_have_monthly_total(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/subscriptions")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 5
    assert payload["monthly_equivalent"] == "169.00"


def test_create_transfer_draft_never_executes_money_movement(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/v1/transfer-drafts",
        json={
            "source_account_id": DEMO_CHECKING_ACCOUNT_ID,
            "payee_id": DEMO_PRIMARY_PAYEE_ID,
            "amount": "300.00",
            "currency": "cny",
            "memo": " AA ",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "pending_policy"
    assert payload["amount"] == "300.00"
    assert payload["currency"] == "CNY"
    assert payload["memo"] == "AA"


def test_transfer_draft_rejects_insufficient_funds(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/v1/transfer-drafts",
        json={
            "source_account_id": DEMO_CHECKING_ACCOUNT_ID,
            "payee_id": DEMO_PRIMARY_PAYEE_ID,
            "amount": "999999.00",
            "currency": "CNY",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "INSUFFICIENT_FUNDS"

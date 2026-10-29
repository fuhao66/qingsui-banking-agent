from fastapi.testclient import TestClient


def create(client: TestClient, message: str) -> dict[str, object]:
    response = client.post("/api/v1/agent/runs", json={"message": message, "channel": "app"})
    assert response.status_code == 201, response.text
    return response.json()


def resume(client: TestClient, run: dict[str, object], payload: dict[str, object]) -> dict[str, object]:
    response = client.post(f"/api/v1/agent/runs/{run['id']}/resume", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_annual_report_and_life_event_detection(api_client: TestClient) -> None:
    annual = create(api_client, "生成2026年年度账单")
    assert annual["status"] == "completed"
    assert len(annual["result"]["months"]) == 12
    events = create(api_client, "看看近期重要日子")
    assert events["status"] == "completed"
    assert events["result"]["life_events"][0]["person"] == "爱人"


def test_aa_collection_and_subscription_reminder(api_client: TestClient) -> None:
    aa = create(api_client, "发起4人聚餐AA收款共400元")
    assert aa["status"] == "waiting_confirmation"
    aa = resume(api_client, aa, {"confirmed": True})
    assert aa["result"]["per_person"] == "100.00"
    reminder = create(api_client, "给星幕视频设置提前3天续费提醒")
    assert reminder["status"] == "waiting_confirmation"
    reminder = resume(api_client, reminder, {"confirmed": True})
    assert reminder["result"]["merchant"] == "星幕视频"


def test_scheduled_phone_transfer_and_card_controls(api_client: TestClient) -> None:
    transfer = create(api_client, "2026年12月20日9点定时给13800002381转500元")
    assert transfer["status"] == "waiting_auth"
    transfer = resume(api_client, transfer, {"auth_code": "246810"})
    assert transfer["result"]["status"] == "scheduled"
    limit = create(api_client, "把尾号6688银行卡单笔限额调整为2000元")
    assert limit["status"] == "waiting_auth"
    limit = resume(api_client, limit, {"auth_code": "246810"})
    assert limit["result"]["transaction_limit"] == "2000.00"
    restriction = create(api_client, "关闭尾号6688银行卡线上交易")
    restriction = resume(api_client, restriction, {"auth_code": "246810"})
    assert restriction["result"]["online_transactions_enabled"] is False


def test_investment_subscribe_holdings_and_redeem(api_client: TestClient) -> None:
    subscribe = create(api_client, "申购稳盈90天1000元理财")
    assert subscribe["status"] == "waiting_auth"
    subscribe = resume(api_client, subscribe, {"auth_code": "246810"})
    assert subscribe["result"]["status"] == "active"
    holdings = create(api_client, "查询我的理财持仓")
    assert holdings["status"] == "completed"
    assert len(holdings["result"]["holdings"]) == 1
    redeem = create(api_client, "赎回稳盈90天理财")
    assert redeem["status"] == "waiting_auth"
    redeem = resume(api_client, redeem, {"auth_code": "246810"})
    assert redeem["result"]["status"] == "redeemed"


def test_virtual_card_application(api_client: TestClient) -> None:
    run = create(api_client, "申请一张虚拟银行卡")
    assert run["status"] == "waiting_auth"
    completed = resume(api_client, run, {"auth_code": "246810"})
    assert completed["result"]["status"] == "approved"

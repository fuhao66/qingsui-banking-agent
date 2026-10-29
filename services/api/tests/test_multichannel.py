import base64
import hashlib
import json
import os
from urllib.parse import unquote, urlparse

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import channels as channel_service


def feishu_event(message_id: str, text: str) -> dict[str, object]:
    return {
        "schema": "2.0",
        "header": {
            "event_type": "im.message.receive_v1",
            "tenant_key": "test-tenant",
            "token": "TEST-FEISHU-TOKEN",
        },
        "event": {
            "sender": {"sender_id": {"open_id": "ou_test_user"}},
            "message": {
                "message_id": message_id,
                "chat_id": "oc_test_chat",
                "message_type": "text",
                "content": f'{{"text":"{text}"}}',
            },
        },
    }


def test_feishu_url_verification_and_token(api_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "feishu_verification_token", "TEST-FEISHU-TOKEN")
    monkeypatch.setattr(settings, "feishu_encrypt_key", "configured-but-handshake-is-unsigned")
    verified = api_client.post(
        "/api/v1/channels/feishu/events",
        json={"type": "url_verification", "token": "TEST-FEISHU-TOKEN", "challenge": "ok"},
    )
    assert verified.status_code == 200
    assert verified.json() == {"challenge": "ok"}
    denied = api_client.post(
        "/api/v1/channels/feishu/events",
        json={"type": "url_verification", "token": "wrong", "challenge": "no"},
    )
    assert denied.status_code == 401


def test_feishu_message_is_idempotent_and_write_action_moves_to_secure_web(
    api_client: TestClient, monkeypatch
) -> None:
    replies: list[tuple[str, str]] = []

    async def capture_reply(message_id: str, text: str) -> None:
        replies.append((message_id, text))

    monkeypatch.setattr(settings, "feishu_verification_token", "TEST-FEISHU-TOKEN")
    monkeypatch.setattr(settings, "public_web_base_url", "https://agent.example.test")
    monkeypatch.setattr(channel_service, "reply_feishu_message", capture_reply)
    payload = feishu_event("om_message_1", "给妈妈转100元")

    first = api_client.post("/api/v1/channels/feishu/events", json=payload)
    duplicate = api_client.post("/api/v1/channels/feishu/events", json=payload)
    assert first.status_code == duplicate.status_code == 200
    assert len(replies) == 1
    assert "安全页面确认" in replies[0][1]

    url = replies[0][1].splitlines()[-2]
    token = unquote(urlparse(url).path.removeprefix("/secure-action/"))
    pending = api_client.get(f"/api/v1/channels/secure/{token}")
    assert pending.status_code == 200
    assert pending.json()["channel"] == "im"
    assert pending.json()["status"] == "waiting_confirmation"

    completed = api_client.post(
        f"/api/v1/channels/secure/{token}/resume", json={"confirmed": True}
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"


def test_feishu_relationship_alias_is_normalized(
    api_client: TestClient, monkeypatch
) -> None:
    replies: list[str] = []

    async def capture_reply(_message_id: str, text: str) -> None:
        replies.append(text)

    monkeypatch.setattr(settings, "feishu_verification_token", "TEST-FEISHU-TOKEN")
    monkeypatch.setattr(channel_service, "reply_feishu_message", capture_reply)
    response = api_client.post(
        "/api/v1/channels/feishu/events",
        json=feishu_event("om_relationship_alias", "给我妈转100元"),
    )
    assert response.status_code == 200
    assert replies
    assert "没有找到收款人" not in replies[0]
    assert "安全页面确认" in replies[0]


def test_feishu_new_intent_replaces_stale_clarification(
    api_client: TestClient, monkeypatch
) -> None:
    replies: list[str] = []

    async def capture_reply(_message_id: str, text: str) -> None:
        replies.append(text)

    monkeypatch.setattr(settings, "feishu_verification_token", "TEST-FEISHU-TOKEN")
    monkeypatch.setattr(channel_service, "reply_feishu_message", capture_reply)

    missing_payee = api_client.post(
        "/api/v1/channels/feishu/events",
        json=feishu_event("om_stale_transfer", "给陌生人转300元"),
    )
    new_intent = api_client.post(
        "/api/v1/channels/feishu/events",
        json=feishu_event("om_new_subscription", "帮我取消订阅"),
    )

    assert missing_payee.status_code == new_intent.status_code == 200
    assert "没有找到收款人" in replies[0]
    assert "需要取消哪个平台或会员" in replies[1]
    assert "没有找到收款人" not in replies[1]


def test_feishu_signature_check(monkeypatch) -> None:
    monkeypatch.setattr(settings, "feishu_encrypt_key", "encrypt-key")
    body = b'{"schema":"2.0"}'
    signature = hashlib.sha256(b"1700000000nonceencrypt-key" + body).hexdigest()
    assert channel_service.verify_feishu_signature(body, "1700000000", "nonce", signature)
    assert not channel_service.verify_feishu_signature(body, "1700000000", "nonce", "bad")


def test_encrypted_feishu_callback_is_decrypted(api_client: TestClient, monkeypatch) -> None:
    encrypt_key = "test-encrypt-key"
    token = "TEST-FEISHU-TOKEN"
    monkeypatch.setattr(settings, "feishu_encrypt_key", encrypt_key)
    monkeypatch.setattr(settings, "feishu_verification_token", token)
    inner = json.dumps(
        {"type": "url_verification", "token": token, "challenge": "encrypted-ok"},
        separators=(",", ":"),
    ).encode()
    key = hashlib.sha256(encrypt_key.encode()).digest()
    padder = PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(inner) + padder.finalize()
    iv = os.urandom(16)
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    outer = json.dumps(
        {"encrypt": base64.b64encode(iv + encryptor.update(padded) + encryptor.finalize()).decode()},
        separators=(",", ":"),
    ).encode()
    response = api_client.post(
        "/api/v1/channels/feishu/events",
        content=outer,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json() == {"challenge": "encrypted-ok"}

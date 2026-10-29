import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import quote
from uuid import uuid4

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import runtime as agent_runtime
from app.agent.intents import DeterministicIntentAdapter
from app.core.config import settings
from app.db.models import AgentRun, AgentStep, ChannelIdentity, ChannelMessageReceipt
from app.domain.schemas import AgentResumeRequest
from app.services.audit import append_audit_event
from app.services.experience import clone_demo_sandbox

PENDING_STATUSES = {"waiting_clarification", "waiting_confirmation", "waiting_auth"}


def verify_feishu_signature(body: bytes, timestamp: str | None, nonce: str | None, signature: str | None) -> bool:
    """Validate the Lark/Feishu SHA-256 callback signature when an encrypt key is configured."""
    if not settings.feishu_encrypt_key:
        return True
    if not timestamp or not nonce or not signature:
        return False
    signed = timestamp.encode() + nonce.encode() + settings.feishu_encrypt_key.encode() + body
    expected = hashlib.sha256(signed).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_feishu_token(payload: dict[str, object]) -> bool:
    if not settings.feishu_verification_token:
        return settings.app_env == "development"
    token = str(payload.get("token") or (payload.get("header") or {}).get("token") or "")
    return hmac.compare_digest(token, settings.feishu_verification_token)


def decrypt_feishu_payload(payload: dict[str, object]) -> dict[str, object]:
    """Decrypt an encrypted Feishu callback body using the configured Encrypt Key."""
    encrypted = payload.get("encrypt")
    if not encrypted:
        return payload
    if not settings.feishu_encrypt_key:
        raise ValueError("encrypted callback received without FEISHU_ENCRYPT_KEY")
    key = hashlib.sha256(settings.feishu_encrypt_key.encode()).digest()
    ciphertext = base64.b64decode(str(encrypted), validate=True)
    if len(ciphertext) < 32 or len(ciphertext) % 16 != 0:
        raise ValueError("invalid encrypted callback length")
    iv, encrypted_body = ciphertext[:16], ciphertext[16:]
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(encrypted_body) + decryptor.finalize()
    unpadder = PKCS7(algorithms.AES.block_size).unpadder()
    plaintext = unpadder.update(padded) + unpadder.finalize()
    decoded = json.loads(plaintext)
    if not isinstance(decoded, dict):
        raise TypeError("decrypted callback must be a JSON object")
    return decoded


def sign_channel_link(run_id: str, user_id: str) -> str:
    expires = int((datetime.now(UTC) + timedelta(minutes=settings.channel_link_minutes)).timestamp())
    payload = f"{run_id}.{user_id}.{expires}"
    signature = hmac.new(
        settings.security_hmac_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return f"{payload}.{signature}"


def decode_channel_link(token: str) -> tuple[str, str]:
    try:
        run_id, user_id, expires_text, signature = token.split(".", 3)
        payload = f"{run_id}.{user_id}.{expires_text}"
        expected = hmac.new(
            settings.security_hmac_secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError("signature")
        if int(expires_text) < int(datetime.now(UTC).timestamp()):
            raise ValueError("expired")
        return run_id, user_id
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "CHANNEL_LINK_INVALID", "message": "安全操作链接无效或已过期。"},
        ) from exc


async def get_or_create_identity(
    session: AsyncSession,
    *,
    provider: str,
    tenant_key: str,
    external_user_id: str,
    display_name: str,
) -> ChannelIdentity:
    identity = await session.scalar(
        select(ChannelIdentity).where(
            ChannelIdentity.provider == provider,
            ChannelIdentity.tenant_key == tenant_key,
            ChannelIdentity.external_user_id == external_user_id,
        )
    )
    if identity is not None:
        return identity
    user = await clone_demo_sandbox(session, display_name[:80] or f"{provider}体验用户")
    identity = ChannelIdentity(
        id=str(uuid4()),
        provider=provider,
        tenant_key=tenant_key or "default",
        external_user_id=external_user_id,
        display_name=display_name[:80] or f"{provider}体验用户",
        user_id=user.id,
    )
    session.add(identity)
    await session.commit()
    return identity


async def claim_message(
    session: AsyncSession,
    *,
    provider: str,
    message_id: str,
    chat_id: str,
    identity_id: str,
) -> ChannelMessageReceipt | None:
    existing = await session.scalar(
        select(ChannelMessageReceipt).where(
            ChannelMessageReceipt.provider == provider,
            ChannelMessageReceipt.external_message_id == message_id,
        )
    )
    if existing is not None:
        return None
    receipt = ChannelMessageReceipt(
        id=str(uuid4()), provider=provider, external_message_id=message_id,
        external_chat_id=chat_id, identity_id=identity_id, status="received",
    )
    session.add(receipt)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return None
    return receipt


async def run_channel_message(
    session: AsyncSession, identity: ChannelIdentity, message: str
) -> AgentRun:
    active = await session.get(AgentRun, identity.active_run_id) if identity.active_run_id else None
    if active is not None and active.status == "waiting_clarification":
        normalized = message.strip().lower()
        if normalized in {"取消", "取消当前操作", "取消任务", "重新开始"}:
            await cancel_superseded_run(session, active, reason="USER_CANCELLED_IN_CHANNEL")
            identity.active_run_id = None
            await session.commit()
            return active

        standalone = await DeterministicIntentAdapter().classify(
            message, {}, identity.user_id
        )
        if standalone.intent not in {"unsupported", active.intent}:
            await cancel_superseded_run(session, active, reason="NEW_CHANNEL_INTENT")
            await session.commit()
            run = await agent_runtime.create_run(
                session, identity.user_id, message, "im", identity.conversation_id
            )
        else:
            run = await agent_runtime.resume_run(
                session,
                identity.user_id,
                active.id,
                AgentResumeRequest(clarification_message=message),
            )
    elif active is not None and active.status in {"waiting_confirmation", "waiting_auth"}:
        return active
    else:
        run = await agent_runtime.create_run(
            session, identity.user_id, message, "im", identity.conversation_id
        )
    identity.conversation_id = run.conversation_id
    identity.active_run_id = run.id if run.status in PENDING_STATUSES else None
    await session.commit()
    return run


async def cancel_superseded_run(
    session: AsyncSession, run: AgentRun, *, reason: str
) -> None:
    paused_steps = await session.scalars(
        select(AgentStep).where(AgentStep.run_id == run.id, AgentStep.status == "paused")
    )
    now = datetime.now(UTC)
    for step in paused_steps:
        step.status = "skipped"
        step.finished_at = now
    run.status = "cancelled"
    run.pending_action = None
    run.response_text = (
        "当前任务已取消。" if reason == "USER_CANCELLED_IN_CHANNEL" else "旧任务已由新的业务请求替代。"
    )
    run.version += 1
    await append_audit_event(
        session,
        user_id=run.user_id,
        action="agent.run.channel_replace",
        outcome="recorded",
        resource_type="agent_run",
        resource_id=run.id,
        reason_codes=[reason],
        details={"channel": run.channel},
    )


def channel_response_text(run: AgentRun) -> str:
    text = run.response_text or "请求已由银行智能体处理。"
    if run.status in {"waiting_confirmation", "waiting_auth"}:
        token = sign_channel_link(run.id, run.user_id)
        url = f"{settings.public_web_base_url.rstrip('/')}/secure-action/{quote(token, safe='')}"
        return f"{text}\n\n为保护账户安全，请在 {settings.channel_link_minutes} 分钟内打开安全页面确认：\n{url}\n请勿转发此链接。"
    return text


async def feishu_tenant_access_token() -> str:
    if not settings.feishu_app_id or not settings.feishu_app_secret:
        raise RuntimeError("Feishu app credentials are not configured")
    async with httpx.AsyncClient(timeout=8) as client:
        response = await client.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": settings.feishu_app_id, "app_secret": settings.feishu_app_secret},
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0 or not data.get("tenant_access_token"):
            raise RuntimeError(f"Feishu token request failed: {data.get('msg', 'unknown error')}")
        return str(data["tenant_access_token"])


async def reply_feishu_message(message_id: str, text: str) -> None:
    if not settings.feishu_delivery_enabled:
        return
    token = await feishu_tenant_access_token()
    async with httpx.AsyncClient(timeout=8) as client:
        response = await client.post(
            f"https://open.feishu.cn/open-apis/im/v1/messages/{quote(message_id, safe='')}/reply",
            headers={"Authorization": f"Bearer {token}"},
            json={"msg_type": "text", "content": json.dumps({"text": text}, ensure_ascii=False)},
        )
        response.raise_for_status()

import json
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import runtime as agent_runtime
from app.api.dependencies import get_db
from app.core.database import SessionFactory
from app.domain.schemas import AgentResumeRequest, AgentRunResponse
from app.services import channels as channel_service

router = APIRouter()
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]


async def process_feishu_message(event: dict[str, object]) -> None:
    message = event.get("message") or {}
    sender = event.get("sender") or {}
    sender_id = sender.get("sender_id") or {}
    message_id = str(message.get("message_id") or "")
    chat_id = str(message.get("chat_id") or "")
    external_user_id = str(sender_id.get("open_id") or sender_id.get("user_id") or "")
    if not message_id or not chat_id or not external_user_id or message.get("message_type") != "text":
        return
    try:
        content = json.loads(str(message.get("content") or "{}"))
        text = str(content.get("text") or "").strip()
    except json.JSONDecodeError:
        return
    if not text:
        return
    tenant_key = str(event.get("tenant_key") or "default")
    async with SessionFactory() as session:
        identity = await channel_service.get_or_create_identity(
            session,
            provider="feishu",
            tenant_key=tenant_key,
            external_user_id=external_user_id,
            display_name=f"飞书用户-{external_user_id[-6:]}",
        )
        receipt = await channel_service.claim_message(
            session, provider="feishu", message_id=message_id,
            chat_id=chat_id, identity_id=identity.id,
        )
        if receipt is None:
            return
        try:
            run = await channel_service.run_channel_message(session, identity, text)
            receipt.run_id = run.id
            receipt.status = "processed"
            await session.commit()
            await channel_service.reply_feishu_message(
                message_id, channel_service.channel_response_text(run)
            )
        except Exception:
            receipt.status = "failed"
            await session.commit()
            raise


@router.post("/channels/feishu/events", tags=["channels"])
async def feishu_events(
    request: Request,
    background_tasks: BackgroundTasks,
    x_lark_request_timestamp: Annotated[str | None, Header()] = None,
    x_lark_request_nonce: Annotated[str | None, Header()] = None,
    x_lark_signature: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    body = await request.body()
    if len(body) > 1_048_576:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="payload too large")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid json") from exc
    try:
        payload = channel_service.decrypt_feishu_payload(payload)
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid encrypted payload"
        ) from exc
    # Feishu's URL Verification handshake does not carry the normal event signature.
    # Validate its inner token and return the challenge before enforcing event headers.
    if payload.get("type") == "url_verification":
        if not channel_service.verify_feishu_token(payload):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
        return {"challenge": payload.get("challenge", "")}
    if not channel_service.verify_feishu_signature(
        body, x_lark_request_timestamp, x_lark_request_nonce, x_lark_signature
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid signature")
    if not channel_service.verify_feishu_token(payload):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
    header = payload.get("header") or {}
    if header.get("event_type") == "im.message.receive_v1":
        event = dict(payload.get("event") or {})
        event["tenant_key"] = header.get("tenant_key") or "default"
        background_tasks.add_task(process_feishu_message, event)
    return {"code": 0}


@router.get(
    "/channels/secure/{token}", response_model=AgentRunResponse, tags=["channels"]
)
async def secure_channel_run(token: str, session: DatabaseSession) -> AgentRunResponse:
    run_id, user_id = channel_service.decode_channel_link(token)
    run = await agent_runtime.owned_run(session, user_id, run_id)
    return await agent_runtime.present_run(session, run)


@router.post(
    "/channels/secure/{token}/resume", response_model=AgentRunResponse, tags=["channels"]
)
async def resume_secure_channel_run(
    token: str, payload: AgentResumeRequest, session: DatabaseSession
) -> AgentRunResponse:
    run_id, user_id = channel_service.decode_channel_link(token)
    run = await agent_runtime.resume_run(session, user_id, run_id, payload)
    return await agent_runtime.present_run(session, run)

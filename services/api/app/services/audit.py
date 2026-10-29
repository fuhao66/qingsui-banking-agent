import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditEvent

SENSITIVE_KEY_FRAGMENTS = (
    "account",
    "authorization",
    "code",
    "credential",
    "otp",
    "password",
    "secret",
    "token",
)


def redact_details(value: object, key: str = "") -> object:
    normalized_key = key.lower()
    if any(fragment in normalized_key for fragment in SENSITIVE_KEY_FRAGMENTS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): redact_details(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [redact_details(item) for item in value]
    return value


def event_digest(event: AuditEvent) -> str:
    created_at = event.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    payload = {
        "id": event.id,
        "user_id": event.user_id,
        "correlation_id": event.correlation_id,
        "action": event.action,
        "outcome": event.outcome,
        "risk_level": event.risk_level,
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "reason_codes": event.reason_codes,
        "details": event.details,
        "previous_hash": event.previous_hash,
        "created_at": created_at.astimezone(UTC).isoformat(),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def append_audit_event(
    session: AsyncSession,
    *,
    user_id: str,
    action: str,
    outcome: str,
    resource_type: str,
    resource_id: str,
    risk_level: str | None = None,
    reason_codes: list[str] | None = None,
    details: dict[str, object] | None = None,
    correlation_id: str | None = None,
) -> AuditEvent:
    previous = await session.scalar(
        select(AuditEvent)
        .where(AuditEvent.user_id == user_id)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(1)
    )
    event = AuditEvent(
        id=str(uuid4()),
        user_id=user_id,
        correlation_id=correlation_id or str(uuid4()),
        action=action,
        outcome=outcome,
        risk_level=risk_level,
        resource_type=resource_type,
        resource_id=resource_id,
        reason_codes=reason_codes or [],
        details=redact_details(details or {}),
        previous_hash=previous.event_hash if previous else None,
        event_hash="",
        created_at=datetime.now(UTC),
    )
    event.event_hash = event_digest(event)
    session.add(event)
    await session.flush()
    return event


async def list_audit_events(
    session: AsyncSession, user_id: str, limit: int
) -> list[AuditEvent]:
    rows = await session.scalars(
        select(AuditEvent)
        .where(AuditEvent.user_id == user_id)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(limit)
    )
    return list(rows)


def verify_audit_chain(events_newest_first: list[AuditEvent]) -> bool:
    events = list(reversed(events_newest_first))
    previous_hash = events[0].previous_hash if events else None
    for event in events:
        if event.previous_hash != previous_hash or event.event_hash != event_digest(event):
            return False
        previous_hash = event.event_hash
    return True

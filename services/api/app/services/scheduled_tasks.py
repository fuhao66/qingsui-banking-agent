from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Account, ScheduledTask
from app.services import banking as banking_service
from app.services.audit import append_audit_event

ACTIVE_STATUSES = ("scheduled", "paused")
TRANSITIONS = {
    "scheduled": {"pause": "paused", "cancel": "cancelled"},
    "paused": {"resume": "scheduled", "cancel": "cancelled"},
}


async def list_user_tasks(
    session: AsyncSession, user_id: str, task_status: str | None = None
) -> list[ScheduledTask]:
    statement = select(ScheduledTask).where(ScheduledTask.user_id == user_id)
    if task_status:
        statement = statement.where(ScheduledTask.status == task_status)
    rows = await session.scalars(statement.order_by(ScheduledTask.execute_at, ScheduledTask.created_at))
    return list(rows)


async def get_owned_task(
    session: AsyncSession, user_id: str, task_id: str, *, lock: bool = False
) -> ScheduledTask:
    statement = select(ScheduledTask).where(
        ScheduledTask.id == task_id, ScheduledTask.user_id == user_id
    )
    if lock:
        statement = statement.with_for_update()
    task = await session.scalar(statement)
    if task is None:
        raise banking_service.domain_error(
            status.HTTP_404_NOT_FOUND, "SCHEDULED_TASK_NOT_FOUND", "定时任务不存在。"
        )
    return task


async def active_reserved_total(
    session: AsyncSession, user_id: str, account_id: str | None = None
) -> Decimal:
    statement = select(func.coalesce(func.sum(ScheduledTask.reserved_amount), 0)).where(
        ScheduledTask.user_id == user_id, ScheduledTask.status.in_(ACTIVE_STATUSES)
    )
    if account_id:
        statement = statement.where(ScheduledTask.source_account_id == account_id)
    return Decimal(str(await session.scalar(statement) or 0))


async def create_occasion_task(
    session: AsyncSession,
    *,
    user_id: str,
    run_id: str,
    account: Account,
    person: str,
    occasion: str,
    execute_at: datetime,
    budget: Decimal,
    items: list[dict[str, object]],
    plan: list[dict[str, object]],
) -> ScheduledTask:
    locked_account = await session.scalar(
        select(Account)
        .where(Account.id == account.id, Account.user_id == user_id, Account.status == "active")
        .with_for_update()
    )
    if locked_account is None:
        raise banking_service.domain_error(
            status.HTTP_409_CONFLICT, "ACCOUNT_NOT_ACTIVE", "预算账户当前不可用。"
        )
    reserved = await active_reserved_total(session, user_id, locked_account.id)
    available = locked_account.balance - reserved
    if budget > available:
        raise banking_service.domain_error(
            status.HTTP_409_CONFLICT,
            "INSUFFICIENT_AVAILABLE_BUDGET",
            f"扣除已预留资金后，可用余额仅为 {available:.2f} 元。",
        )
    task = ScheduledTask(
        id=str(uuid4()),
        user_id=user_id,
        run_id=run_id,
        source_account_id=locked_account.id,
        task_type="occasion_preparation",
        title=f"为{person}准备{occasion}惊喜",
        status="scheduled",
        execute_at=execute_at,
        budget=budget,
        reserved_amount=budget,
        currency="CNY",
        risk_level="yellow",
        plan=plan,
        items=items,
    )
    session.add(task)
    await session.flush()
    await append_audit_event(
        session,
        user_id=user_id,
        action="scheduled_task.create",
        outcome="allowed",
        risk_level="yellow",
        resource_type="scheduled_task",
        resource_id=task.id,
        correlation_id=run_id,
        reason_codes=["USER_CONFIRMED", "BUDGET_AVAILABLE", "WHITELIST_DAG"],
        details={
            "title": task.title,
            "execute_at": execute_at.isoformat(),
            "budget": str(budget),
            "source_account_id": locked_account.id,
        },
    )
    await session.commit()
    return task


async def transition_task(
    session: AsyncSession, user_id: str, task_id: str, action: str
) -> ScheduledTask:
    task = await get_owned_task(session, user_id, task_id, lock=True)
    target = TRANSITIONS.get(task.status, {}).get(action)
    if target is None:
        raise banking_service.domain_error(
            status.HTTP_409_CONFLICT,
            "INVALID_TASK_TRANSITION",
            f"任务处于 {task.status} 状态，不能执行 {action}。",
        )
    previous = task.status
    task.status = target
    if target == "cancelled":
        task.reserved_amount = Decimal(0)
    await append_audit_event(
        session,
        user_id=user_id,
        action=f"scheduled_task.{action}",
        outcome="allowed",
        risk_level="yellow",
        resource_type="scheduled_task",
        resource_id=task.id,
        reason_codes=["USER_CONFIRMED", "VALID_STATE_TRANSITION"],
        details={"from": previous, "to": target},
    )
    await session.commit()
    return task

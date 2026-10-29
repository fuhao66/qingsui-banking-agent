from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    phone_masked: Mapped[str] = mapped_column(String(24), nullable=False)
    customer_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    risk_profile: Mapped[str] = mapped_column(String(24), default="balanced", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class ChannelIdentity(Base):
    """Maps an external IM identity to an isolated banking sandbox user."""

    __tablename__ = "channel_identities"
    __table_args__ = (
        UniqueConstraint(
            "provider", "tenant_key", "external_user_id", name="uq_channel_identity_external"
        ),
        Index("ix_channel_identity_user", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    tenant_key: Mapped[str] = mapped_column(String(80), default="default", nullable=False)
    external_user_id: Mapped[str] = mapped_column(String(160), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(String(36))
    active_run_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now,
        server_default=func.now(), nullable=False
    )


class ChannelMessageReceipt(Base):
    """Provides idempotency and traceability for inbound channel messages."""

    __tablename__ = "channel_message_receipts"
    __table_args__ = (
        UniqueConstraint("provider", "external_message_id", name="uq_channel_message_external"),
        Index("ix_channel_message_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    external_message_id: Mapped[str] = mapped_column(String(160), nullable=False)
    external_chat_id: Mapped[str] = mapped_column(String(160), nullable=False)
    identity_id: Mapped[str] = mapped_column(ForeignKey("channel_identities.id"), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(24), default="received", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("balance >= 0", name="ck_accounts_balance_nonnegative"),
        CheckConstraint("status IN ('active', 'frozen', 'closed')", name="ck_accounts_status"),
        Index("ix_accounts_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    account_type: Mapped[str] = mapped_column(String(24), nullable=False)
    masked_number: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="CNY", nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class Payee(Base):
    __tablename__ = "payees"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "account_token", name="uq_payees_owner_token"),
        Index("ix_payees_owner_name", "owner_user_id", "name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    alias: Mapped[str | None] = mapped_column(String(120))
    bank_name: Mapped[str] = mapped_column(String(80), nullable=False)
    account_masked: Mapped[str] = mapped_column(String(32), nullable=False)
    account_token: Mapped[str] = mapped_column(String(80), nullable=False)
    phone_masked: Mapped[str | None] = mapped_column(String(24))
    phone_last4: Mapped[str | None] = mapped_column(String(4))
    is_frequent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_transfer_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        CheckConstraint("direction IN ('credit', 'debit')", name="ck_transactions_direction"),
        CheckConstraint(
            "status IN ('pending', 'completed', 'failed', 'reversed')",
            name="ck_transactions_status",
        ),
        Index("ix_transactions_account_occurred", "account_id", "occurred_at"),
        Index("ix_transactions_category_occurred", "category", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="CNY", nullable=False)
    merchant: Mapped[str | None] = mapped_column(String(120))
    counterparty_name: Mapped[str | None] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="completed", nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    risk_flag: Mapped[str | None] = mapped_column(String(40))
    external_reference: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_subscriptions_amount_positive"),
        CheckConstraint(
            "status IN ('active', 'paused', 'cancelled')", name="ck_subscriptions_status"
        ),
        Index("ix_subscriptions_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    merchant: Mapped[str] = mapped_column(String(120), nullable=False)
    product_name: Mapped[str] = mapped_column(String(120), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="CNY", nullable=False)
    billing_cycle: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    next_charge_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_charge_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_channel: Mapped[str | None] = mapped_column(String(120))
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal(1))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class BankCard(Base):
    __tablename__ = "bank_cards"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'locked', 'lost')", name="ck_bank_cards_status"
        ),
        CheckConstraint("daily_limit > 0", name="ck_bank_cards_daily_limit_positive"),
        UniqueConstraint("user_id", "last4", name="uq_bank_cards_user_last4"),
        Index("ix_bank_cards_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    card_name: Mapped[str] = mapped_column(String(80), nullable=False)
    network: Mapped[str] = mapped_column(String(24), nullable=False)
    masked_number: Mapped[str] = mapped_column(String(32), nullable=False)
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    daily_limit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    transaction_limit: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("5000.00"), nullable=False
    )
    online_transactions_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )


class InvestmentProduct(Base):
    __tablename__ = "investment_products"
    __table_args__ = (
        CheckConstraint(
            "risk_level IN ('low', 'medium', 'high')",
            name="ck_investment_products_risk",
        ),
        CheckConstraint("min_amount > 0", name="ck_investment_products_min_amount"),
        CheckConstraint("term_months >= 0", name="ck_investment_products_term"),
        CheckConstraint("status IN ('active', 'inactive')", name="ck_investment_products_status"),
        Index("ix_investment_products_risk_status", "risk_level", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    min_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    expected_return_low: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    expected_return_high: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    term_months: Mapped[int] = mapped_column(Integer, nullable=False)
    liquidity: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class TransferDraft(Base):
    __tablename__ = "transfer_drafts"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transfer_drafts_amount_positive"),
        CheckConstraint(
            "status IN ('pending_policy', 'awaiting_confirmation', 'awaiting_auth', "
            "'approved', 'executed', 'cancelled', 'expired')",
            name="ck_transfer_drafts_status",
        ),
        Index("ix_transfer_drafts_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    source_account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    payee_id: Mapped[str] = mapped_column(ForeignKey("payees.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="CNY", nullable=False)
    memo: Mapped[str | None] = mapped_column(String(80))
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="pending_policy", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class PolicyDecision(Base):
    __tablename__ = "policy_decisions"
    __table_args__ = (
        CheckConstraint("risk_level IN ('green', 'yellow', 'red')", name="ck_policy_risk_level"),
        CheckConstraint(
            "required_action IN ('automatic', 'confirmation', 'strong_auth')",
            name="ck_policy_required_action",
        ),
        UniqueConstraint("draft_id", name="uq_policy_decisions_draft"),
        Index("ix_policy_decisions_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    draft_id: Mapped[str] = mapped_column(ForeignKey("transfer_drafts.id"), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(12), nullable=False)
    required_action: Mapped[str] = mapped_column(String(24), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(24), nullable=False)
    daily_total_before: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    projected_daily_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    prompt_signals: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class AuthChallenge(Base):
    __tablename__ = "auth_challenges"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'verified', 'failed', 'expired', 'locked')",
            name="ck_auth_challenges_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_auth_challenges_attempts_nonnegative"),
        Index("ix_auth_challenges_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    draft_id: Mapped[str] = mapped_column(ForeignKey("transfer_drafts.id"), nullable=False)
    method: Mapped[str] = mapped_column(String(24), nullable=False)
    destination_masked: Mapped[str] = mapped_column(String(40), nullable=False)
    code_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class OperationAuthChallenge(Base):
    __tablename__ = "operation_auth_challenges"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'verified', 'failed', 'expired', 'locked')",
            name="ck_operation_auth_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_operation_auth_attempts"),
        Index("ix_operation_auth_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    method: Mapped[str] = mapped_column(String(24), nullable=False)
    destination_masked: Mapped[str] = mapped_column(String(40), nullable=False)
    code_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class SecurityState(Base):
    __tablename__ = "security_states"
    __table_args__ = (
        CheckConstraint("consecutive_failures >= 0", name="ck_security_failures_nonnegative"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )


class TransferExecution(Base):
    __tablename__ = "transfer_executions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transfer_executions_amount_positive"),
        CheckConstraint(
            "status IN ('succeeded', 'failed', 'reversed')",
            name="ck_transfer_executions_status",
        ),
        UniqueConstraint("draft_id", name="uq_transfer_executions_draft"),
        UniqueConstraint("transaction_id", name="uq_transfer_executions_transaction"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_transfer_executions_user_key"),
        Index("ix_transfer_executions_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    draft_id: Mapped[str] = mapped_column(ForeignKey("transfer_drafts.id"), nullable=False)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    receipt_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('allowed', 'denied', 'failed', 'recorded')",
            name="ck_audit_events_outcome",
        ),
        Index("ix_audit_events_user_created", "user_id", "created_at"),
        Index("ix_audit_events_resource", "resource_type", "resource_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    risk_level: Mapped[str | None] = mapped_column(String(12))
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    details: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    previous_hash: Mapped[str | None] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentConversation(Base):
    __tablename__ = "agent_conversations"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'closed')", name="ck_agent_conversations_status"),
        Index("ix_agent_conversations_user_updated", "user_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    memory: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('planning', 'running', 'waiting_clarification', "
            "'waiting_confirmation', 'waiting_auth', 'human_review', "
            "'completed', 'cancelled', 'failed')",
            name="ck_agent_runs_status",
        ),
        Index("ix_agent_runs_conversation_created", "conversation_id", "created_at"),
        Index("ix_agent_runs_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("agent_conversations.id"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(24), nullable=False)
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    plan: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    context: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    current_node_id: Mapped[str | None] = mapped_column(String(64))
    pending_action: Mapped[dict[str, object] | None] = mapped_column(JSON)
    result: Mapped[dict[str, object] | None] = mapped_column(JSON)
    response_text: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )


class AgentStep(Base):
    __tablename__ = "agent_steps"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'paused', 'failed', 'skipped')",
            name="ck_agent_steps_status",
        ),
        UniqueConstraint("run_id", "node_id", name="uq_agent_steps_run_node"),
        Index("ix_agent_steps_run_sequence", "run_id", "sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), nullable=False)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    input_data: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    output_data: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GuardianAssessment(Base):
    __tablename__ = "guardian_assessments"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_guardian_assessments_run"),
        Index("ix_guardian_assessments_user_created", "user_id", "created_at"),
        Index("ix_guardian_assessments_disposition", "disposition", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    scam_score: Mapped[int] = mapped_column(Integer, nullable=False)
    disposition: Mapped[str] = mapped_column(String(20), nullable=False)
    original_risk: Mapped[str] = mapped_column(String(12), nullable=False)
    effective_risk: Mapped[str] = mapped_column(String(12), nullable=False)
    signals: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    evidence_summary: Mapped[str | None] = mapped_column(Text)
    evidence_fingerprint: Mapped[str | None] = mapped_column(String(64))
    banker_proposal: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    counterfactual: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    decision_receipt: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    receipt_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now,
        server_default=func.now(), nullable=False
    )


class AgentHandoff(Base):
    __tablename__ = "agent_handoffs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('requested', 'resolved')", name="ck_agent_handoffs_status"
        ),
        Index("ix_agent_handoffs_run_status", "run_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(String(240), nullable=False)
    resume_status: Mapped[str] = mapped_column(String(32), nullable=False)
    resolution: Mapped[str | None] = mapped_column(String(240))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('scheduled', 'paused', 'cancelled', 'completed', 'failed')",
            name="ck_scheduled_tasks_status",
        ),
        CheckConstraint("budget > 0", name="ck_scheduled_tasks_budget_positive"),
        CheckConstraint(
            "reserved_amount >= 0 AND reserved_amount <= budget",
            name="ck_scheduled_tasks_reserved_amount",
        ),
        Index("ix_scheduled_tasks_user_status", "user_id", "status"),
        Index("ix_scheduled_tasks_execute_at", "execute_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), nullable=False)
    source_account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    task_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="scheduled", nullable=False)
    execute_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    budget: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    reserved_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="CNY", nullable=False)
    risk_level: Mapped[str] = mapped_column(String(12), default="yellow", nullable=False)
    plan: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    items: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )


class ExperienceSession(Base):
    __tablename__ = "experience_sessions"
    __table_args__ = (
        CheckConstraint("request_count >= 0", name="ck_experience_sessions_request_count"),
        Index("ix_experience_sessions_user_expires", "user_id", "expires_at"),
        Index("ix_experience_sessions_expires_revoked", "expires_at", "revoked"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(40), nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    request_window_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BusinessOperation(Base):
    """Auditable sandbox record for non-transfer banking side effects.

    The payload is produced from validated slots and a whitelist executor, never
    interpreted as executable code.
    """

    __tablename__ = "business_operations"
    __table_args__ = (
        Index("ix_business_operations_user_type", "user_id", "operation_type"),
        Index("ix_business_operations_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"))
    operation_type: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(12), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    result: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now,
        server_default=func.now(), nullable=False
    )


class LifeEvent(Base):
    __tablename__ = "life_events"
    __table_args__ = (Index("ix_life_events_user_date", "user_id", "event_date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    person: Mapped[str] = mapped_column(String(40), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    event_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    default_budget: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )

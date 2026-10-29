"""Add the security control plane and auditable execution ledger.

Revision ID: 20260903_0002
Revises: 20260903_0001
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_0002"
down_revision: str | None = "20260903_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "security_states",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "consecutive_failures >= 0", name="ck_security_failures_nonnegative"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.execute(
        sa.text(
            "INSERT INTO security_states "
            "(user_id, consecutive_failures, locked_until, last_failure_at, updated_at) "
            "SELECT id, 0, NULL, NULL, CURRENT_TIMESTAMP FROM users"
        )
    )
    op.create_table(
        "policy_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("draft_id", sa.String(length=36), nullable=False),
        sa.Column("risk_level", sa.String(length=12), nullable=False),
        sa.Column("required_action", sa.String(length=24), nullable=False),
        sa.Column("policy_version", sa.String(length=24), nullable=False),
        sa.Column("daily_total_before", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column(
            "projected_daily_total", sa.Numeric(precision=18, scale=2), nullable=False
        ),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("prompt_signals", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "risk_level IN ('green', 'yellow', 'red')", name="ck_policy_risk_level"
        ),
        sa.CheckConstraint(
            "required_action IN ('automatic', 'confirmation', 'strong_auth')",
            name="ck_policy_required_action",
        ),
        sa.ForeignKeyConstraint(["draft_id"], ["transfer_drafts.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_id", name="uq_policy_decisions_draft"),
    )
    op.create_index(
        "ix_policy_decisions_user_created", "policy_decisions", ["user_id", "created_at"]
    )
    op.create_table(
        "auth_challenges",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("draft_id", sa.String(length=36), nullable=False),
        sa.Column("method", sa.String(length=24), nullable=False),
        sa.Column("destination_masked", sa.String(length=40), nullable=False),
        sa.Column("code_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'verified', 'failed', 'expired', 'locked')",
            name="ck_auth_challenges_status",
        ),
        sa.CheckConstraint(
            "attempts >= 0", name="ck_auth_challenges_attempts_nonnegative"
        ),
        sa.ForeignKeyConstraint(["draft_id"], ["transfer_drafts.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_auth_challenges_user_status", "auth_challenges", ["user_id", "status"]
    )
    op.create_table(
        "transfer_executions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("draft_id", sa.String(length=36), nullable=False),
        sa.Column("transaction_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=80), nullable=False),
        sa.Column("receipt_no", sa.String(length=64), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "amount > 0", name="ck_transfer_executions_amount_positive"
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed', 'reversed')",
            name="ck_transfer_executions_status",
        ),
        sa.ForeignKeyConstraint(["draft_id"], ["transfer_drafts.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_id", name="uq_transfer_executions_draft"),
        sa.UniqueConstraint(
            "transaction_id", name="uq_transfer_executions_transaction"
        ),
        sa.UniqueConstraint(
            "user_id", "idempotency_key", name="uq_transfer_executions_user_key"
        ),
        sa.UniqueConstraint("receipt_no"),
    )
    op.create_index(
        "ix_transfer_executions_user_created",
        "transfer_executions",
        ["user_id", "created_at"],
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("risk_level", sa.String(length=12), nullable=True),
        sa.Column("resource_type", sa.String(length=40), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("previous_hash", sa.String(length=64), nullable=True),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('allowed', 'denied', 'failed', 'recorded')",
            name="ck_audit_events_outcome",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_hash"),
    )
    op.create_index(
        "ix_audit_events_resource", "audit_events", ["resource_type", "resource_id"]
    )
    op.create_index(
        "ix_audit_events_user_created", "audit_events", ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_user_created", table_name="audit_events")
    op.drop_index("ix_audit_events_resource", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index(
        "ix_transfer_executions_user_created", table_name="transfer_executions"
    )
    op.drop_table("transfer_executions")
    op.drop_index("ix_auth_challenges_user_status", table_name="auth_challenges")
    op.drop_table("auth_challenges")
    op.drop_index("ix_policy_decisions_user_created", table_name="policy_decisions")
    op.drop_table("policy_decisions")
    op.drop_table("security_states")

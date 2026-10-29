"""Complete competition example scenarios.

Revision ID: 20260904_0007
Revises: 20260904_0006
"""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "20260904_0007"
down_revision: str | None = "20260904_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("bank_cards") as batch:
        batch.add_column(sa.Column("transaction_limit", sa.Numeric(18, 2), nullable=False, server_default="5000.00"))
        batch.add_column(sa.Column("online_transactions_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table(
        "business_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("agent_runs.id"), nullable=True),
        sa.Column("operation_type", sa.String(48), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("risk_level", sa.String(12), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_business_operations_user_type", "business_operations", ["user_id", "operation_type"])
    op.create_index("ix_business_operations_user_status", "business_operations", ["user_id", "status"])
    op.create_table(
        "life_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("person", sa.String(40), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("default_budget", sa.Numeric(18, 2), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_life_events_user_date", "life_events", ["user_id", "event_date"])


def downgrade() -> None:
    op.drop_index("ix_life_events_user_date", table_name="life_events")
    op.drop_table("life_events")
    op.drop_index("ix_business_operations_user_status", table_name="business_operations")
    op.drop_index("ix_business_operations_user_type", table_name="business_operations")
    op.drop_table("business_operations")
    with op.batch_alter_table("bank_cards") as batch:
        batch.drop_column("online_transactions_enabled")
        batch.drop_column("transaction_limit")

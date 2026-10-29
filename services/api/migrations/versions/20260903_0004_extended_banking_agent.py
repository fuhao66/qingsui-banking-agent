"""Add cards, investment products, and generic operation authentication.

Revision ID: 20260903_0004
Revises: 20260903_0003
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_0004"
down_revision: str | None = "20260903_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bank_cards",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("card_name", sa.String(length=80), nullable=False),
        sa.Column("network", sa.String(length=24), nullable=False),
        sa.Column("masked_number", sa.String(length=32), nullable=False),
        sa.Column("last4", sa.String(length=4), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("daily_limit", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("status IN ('active', 'locked', 'lost')", name="ck_bank_cards_status"),
        sa.CheckConstraint("daily_limit > 0", name="ck_bank_cards_daily_limit_positive"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "last4", name="uq_bank_cards_user_last4"),
    )
    op.create_index("ix_bank_cards_user_status", "bank_cards", ["user_id", "status"])

    op.create_table(
        "investment_products",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("min_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("expected_return_low", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("expected_return_high", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("term_months", sa.Integer(), nullable=False),
        sa.Column("liquidity", sa.String(length=40), nullable=False),
        sa.Column("description", sa.String(length=240), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("risk_level IN ('low', 'medium', 'high')", name="ck_investment_products_risk"),
        sa.CheckConstraint("min_amount > 0", name="ck_investment_products_min_amount"),
        sa.CheckConstraint("term_months >= 0", name="ck_investment_products_term"),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_investment_products_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_investment_products_risk_status",
        "investment_products",
        ["risk_level", "status"],
    )

    op.create_table(
        "operation_auth_challenges",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("resource_type", sa.String(length=40), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("method", sa.String(length=24), nullable=False),
        sa.Column("destination_masked", sa.String(length=40), nullable=False),
        sa.Column("code_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'verified', 'failed', 'expired', 'locked')",
            name="ck_operation_auth_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_operation_auth_attempts"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_operation_auth_user_status",
        "operation_auth_challenges",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_operation_auth_user_status", table_name="operation_auth_challenges")
    op.drop_table("operation_auth_challenges")
    op.drop_index("ix_investment_products_risk_status", table_name="investment_products")
    op.drop_table("investment_products")
    op.drop_index("ix_bank_cards_user_status", table_name="bank_cards")
    op.drop_table("bank_cards")

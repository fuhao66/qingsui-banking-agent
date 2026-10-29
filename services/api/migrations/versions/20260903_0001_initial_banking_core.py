"""Create the sandbox banking core.

Revision ID: 20260903_0001
Revises:
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("phone_masked", sa.String(length=24), nullable=False),
        sa.Column("customer_no", sa.String(length=32), nullable=False),
        sa.Column("risk_profile", sa.String(length=24), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_no"),
    )
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("account_type", sa.String(length=24), nullable=False),
        sa.Column("masked_number", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("balance", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.CheckConstraint("balance >= 0", name="ck_accounts_balance_nonnegative"),
        sa.CheckConstraint("status IN ('active', 'frozen', 'closed')", name="ck_accounts_status"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_accounts_user_status", "accounts", ["user_id", "status"])
    op.create_table(
        "payees",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("alias", sa.String(length=120), nullable=True),
        sa.Column("bank_name", sa.String(length=80), nullable=False),
        sa.Column("account_masked", sa.String(length=32), nullable=False),
        sa.Column("account_token", sa.String(length=80), nullable=False),
        sa.Column("phone_masked", sa.String(length=24), nullable=True),
        sa.Column("phone_last4", sa.String(length=4), nullable=True),
        sa.Column("is_frequent", sa.Boolean(), nullable=False),
        sa.Column("last_transfer_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_user_id", "account_token", name="uq_payees_owner_token"),
    )
    op.create_index("ix_payees_owner_name", "payees", ["owner_user_id", "name"])
    op.create_table(
        "transactions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("merchant", sa.String(length=120), nullable=True),
        sa.Column("counterparty_name", sa.String(length=80), nullable=True),
        sa.Column("description", sa.String(length=240), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_recurring", sa.Boolean(), nullable=False),
        sa.Column("risk_flag", sa.String(length=40), nullable=True),
        sa.Column("external_reference", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        sa.CheckConstraint("direction IN ('credit', 'debit')", name="ck_transactions_direction"),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'failed', 'reversed')",
            name="ck_transactions_status",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_reference"),
    )
    op.create_index(
        "ix_transactions_account_occurred", "transactions", ["account_id", "occurred_at"]
    )
    op.create_index(
        "ix_transactions_category_occurred", "transactions", ["category", "occurred_at"]
    )
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("merchant", sa.String(length=120), nullable=False),
        sa.Column("product_name", sa.String(length=120), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("billing_cycle", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("next_charge_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_charge_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_channel", sa.String(length=120), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.CheckConstraint("amount > 0", name="ck_subscriptions_amount_positive"),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'cancelled')", name="ck_subscriptions_status"
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_subscriptions_user_status", "subscriptions", ["user_id", "status"]
    )
    op.create_table(
        "transfer_drafts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("source_account_id", sa.String(length=36), nullable=False),
        sa.Column("payee_id", sa.String(length=36), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("memo", sa.String(length=80), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.CheckConstraint("amount > 0", name="ck_transfer_drafts_amount_positive"),
        sa.CheckConstraint(
            "status IN ('pending_policy', 'awaiting_confirmation', 'awaiting_auth', "
            "'approved', 'executed', 'cancelled', 'expired')",
            name="ck_transfer_drafts_status",
        ),
        sa.ForeignKeyConstraint(["payee_id"], ["payees.id"]),
        sa.ForeignKeyConstraint(["source_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_transfer_drafts_user_status", "transfer_drafts", ["user_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_transfer_drafts_user_status", table_name="transfer_drafts")
    op.drop_table("transfer_drafts")
    op.drop_index("ix_subscriptions_user_status", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_index("ix_transactions_category_occurred", table_name="transactions")
    op.drop_index("ix_transactions_account_occurred", table_name="transactions")
    op.drop_table("transactions")
    op.drop_index("ix_payees_owner_name", table_name="payees")
    op.drop_table("payees")
    op.drop_index("ix_accounts_user_status", table_name="accounts")
    op.drop_table("accounts")
    op.drop_table("users")

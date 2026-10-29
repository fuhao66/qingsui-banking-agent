"""Add cross-scenario scheduled tasks.

Revision ID: 20260904_0005
Revises: 20260903_0004
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260904_0005"
down_revision: str | None = "20260903_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduled_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("source_account_id", sa.String(length=36), nullable=False),
        sa.Column("task_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("execute_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("budget", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("reserved_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("risk_level", sa.String(length=12), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('scheduled', 'paused', 'cancelled', 'completed', 'failed')",
            name="ck_scheduled_tasks_status",
        ),
        sa.CheckConstraint("budget > 0", name="ck_scheduled_tasks_budget_positive"),
        sa.CheckConstraint(
            "reserved_amount >= 0 AND reserved_amount <= budget",
            name="ck_scheduled_tasks_reserved_amount",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"]),
        sa.ForeignKeyConstraint(["source_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scheduled_tasks_user_status", "scheduled_tasks", ["user_id", "status"]
    )
    op.create_index("ix_scheduled_tasks_execute_at", "scheduled_tasks", ["execute_at"])


def downgrade() -> None:
    op.drop_index("ix_scheduled_tasks_execute_at", table_name="scheduled_tasks")
    op.drop_index("ix_scheduled_tasks_user_status", table_name="scheduled_tasks")
    op.drop_table("scheduled_tasks")

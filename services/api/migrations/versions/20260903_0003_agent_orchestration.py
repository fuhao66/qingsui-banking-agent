"""Add persistent agent conversations, runs, steps, and human handoffs.

Revision ID: 20260903_0003
Revises: 20260903_0002
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_0003"
down_revision: str | None = "20260903_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_conversations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("channel", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("memory", sa.JSON(), nullable=False),
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
            "status IN ('active', 'closed')", name="ck_agent_conversations_status"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_conversations_user_updated",
        "agent_conversations",
        ["user_id", "updated_at"],
    )
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("channel", sa.String(length=24), nullable=False),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("model_provider", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("current_node_id", sa.String(length=64), nullable=True),
        sa.Column("pending_action", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
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
            "status IN ('planning', 'running', 'waiting_clarification', "
            "'waiting_confirmation', 'waiting_auth', 'human_review', "
            "'completed', 'cancelled', 'failed')",
            name="ck_agent_runs_status",
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["agent_conversations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_runs_conversation_created",
        "agent_runs",
        ["conversation_id", "created_at"],
    )
    op.create_index("ix_agent_runs_user_status", "agent_runs", ["user_id", "status"])
    op.create_table(
        "agent_steps",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("input_data", sa.JSON(), nullable=False),
        sa.Column("output_data", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'paused', 'failed', 'skipped')",
            name="ck_agent_steps_status",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "node_id", name="uq_agent_steps_run_node"),
    )
    op.create_index(
        "ix_agent_steps_run_sequence", "agent_steps", ["run_id", "sequence"]
    )
    op.create_table(
        "agent_handoffs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=240), nullable=False),
        sa.Column("resume_status", sa.String(length=32), nullable=False),
        sa.Column("resolution", sa.String(length=240), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('requested', 'resolved')", name="ck_agent_handoffs_status"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_handoffs_run_status", "agent_handoffs", ["run_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_agent_handoffs_run_status", table_name="agent_handoffs")
    op.drop_table("agent_handoffs")
    op.drop_index("ix_agent_steps_run_sequence", table_name="agent_steps")
    op.drop_table("agent_steps")
    op.drop_index("ix_agent_runs_user_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_conversation_created", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index(
        "ix_agent_conversations_user_updated", table_name="agent_conversations"
    )
    op.drop_table("agent_conversations")

"""Add isolated public experience sessions.

Revision ID: 20260904_0006
Revises: 20260904_0005
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260904_0006"
down_revision: str | None = "20260904_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "experience_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=40), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("request_window_count", sa.Integer(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("request_count >= 0", name="ck_experience_sessions_request_count"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_digest"),
    )
    op.create_index(
        "ix_experience_sessions_user_expires", "experience_sessions", ["user_id", "expires_at"]
    )
    op.create_index(
        "ix_experience_sessions_expires_revoked",
        "experience_sessions",
        ["expires_at", "revoked"],
    )


def downgrade() -> None:
    op.drop_index("ix_experience_sessions_expires_revoked", table_name="experience_sessions")
    op.drop_index("ix_experience_sessions_user_expires", table_name="experience_sessions")
    op.drop_table("experience_sessions")

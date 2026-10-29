"""Add external channel identities and idempotent message receipts.

Revision ID: 20260907_0009
Revises: 20260906_0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0009"
down_revision: str | None = "20260906_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "channel_identities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("tenant_key", sa.String(80), nullable=False, server_default="default"),
        sa.Column("external_user_id", sa.String(160), nullable=False),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=True),
        sa.Column("active_run_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.UniqueConstraint("provider", "tenant_key", "external_user_id", name="uq_channel_identity_external"),
    )
    op.create_index("ix_channel_identity_user", "channel_identities", ["user_id"])
    op.create_table(
        "channel_message_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("external_message_id", sa.String(160), nullable=False),
        sa.Column("external_chat_id", sa.String(160), nullable=False),
        sa.Column("identity_id", sa.String(36), sa.ForeignKey("channel_identities.id"), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="received"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.UniqueConstraint("provider", "external_message_id", name="uq_channel_message_external"),
    )
    op.create_index("ix_channel_message_created", "channel_message_receipts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_channel_message_created", table_name="channel_message_receipts")
    op.drop_table("channel_message_receipts")
    op.drop_index("ix_channel_identity_user", table_name="channel_identities")
    op.drop_table("channel_identities")

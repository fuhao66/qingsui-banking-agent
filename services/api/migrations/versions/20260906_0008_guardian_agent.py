"""Add Guardian Agent assessments and decision receipts.

Revision ID: 20260906_0008
Revises: 20260904_0007
"""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "20260906_0008"
down_revision: str | None = "20260904_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "guardian_assessments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source_type", sa.String(24), nullable=False),
        sa.Column("model_provider", sa.String(32), nullable=False),
        sa.Column("scam_score", sa.Integer(), nullable=False),
        sa.Column("disposition", sa.String(20), nullable=False),
        sa.Column("original_risk", sa.String(12), nullable=False),
        sa.Column("effective_risk", sa.String(12), nullable=False),
        sa.Column("signals", sa.JSON(), nullable=False),
        sa.Column("evidence_summary", sa.Text(), nullable=True),
        sa.Column("evidence_fingerprint", sa.String(64), nullable=True),
        sa.Column("banker_proposal", sa.JSON(), nullable=False),
        sa.Column("counterfactual", sa.JSON(), nullable=False),
        sa.Column("decision_receipt", sa.JSON(), nullable=False),
        sa.Column("receipt_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_guardian_assessments_user_created", "guardian_assessments", ["user_id", "created_at"])
    op.create_index("ix_guardian_assessments_disposition", "guardian_assessments", ["disposition", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_guardian_assessments_disposition", table_name="guardian_assessments")
    op.drop_index("ix_guardian_assessments_user_created", table_name="guardian_assessments")
    op.drop_table("guardian_assessments")

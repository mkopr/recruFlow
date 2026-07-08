"""dead letter queues

Revision ID: 7130773ba67b
Revises: bef7908f5330
Create Date: 2026-07-08 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7130773ba67b"
down_revision: str | Sequence[str] | None = "bef7908f5330"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "ingestion_failures",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dedup_key", sa.String(length=255), nullable=False),
        sa.Column("failure_type", sa.String(length=30), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="open", nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("scheduler_run_id", sa.Integer(), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.ForeignKeyConstraint(["scheduler_run_id"], ["scheduler_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedup_key"),
    )
    op.create_index(
        "ix_ingestion_failures_source_id_occurred_at",
        "ingestion_failures",
        ["source_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "scoring_failures",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dedup_key", sa.String(length=255), nullable=False),
        sa.Column("failure_type", sa.String(length=30), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="open", nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("offer_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["offer_id"], ["offers.id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedup_key"),
    )
    op.create_index(
        "ix_scoring_failures_offer_id_occurred_at",
        "scoring_failures",
        ["offer_id", "occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_scoring_failures_offer_id_occurred_at", table_name="scoring_failures")
    op.drop_table("scoring_failures")
    op.drop_index("ix_ingestion_failures_source_id_occurred_at", table_name="ingestion_failures")
    op.drop_table("ingestion_failures")

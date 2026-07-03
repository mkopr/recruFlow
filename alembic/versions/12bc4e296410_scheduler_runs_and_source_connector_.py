"""scheduler runs and source connector column

Revision ID: 12bc4e296410
Revises: aa3fa339111b
Create Date: 2026-07-03 10:15:20.166597

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "12bc4e296410"
down_revision: str | Sequence[str] | None = "aa3fa339111b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("sources", sa.Column("connector", sa.String(length=50), nullable=True))
    op.create_table(
        "scheduler_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("trigger_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="running", nullable=False),
        sa.Column("fetched_count", sa.Integer(), nullable=True),
        sa.Column("created_count", sa.Integer(), nullable=True),
        sa.Column("warning", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scheduler_runs_source_id_started_at",
        "scheduler_runs",
        ["source_id", "started_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_scheduler_runs_source_id_started_at", table_name="scheduler_runs")
    op.drop_table("scheduler_runs")
    op.drop_column("sources", "connector")

"""detail fetch blocked dlq

Revision ID: a1c2d4e6f8b0
Revises: 306f60011cef
Create Date: 2026-07-29 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1c2d4e6f8b0"
down_revision: str | Sequence[str] | None = "306f60011cef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("ingestion_failures", sa.Column("url", sa.Text(), nullable=True))
    op.add_column("ingestion_failures", sa.Column("blocked_status", sa.Integer(), nullable=True))
    op.add_column(
        "ingestion_failures",
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_index(
        "ix_ingestion_failures_status_blocked_status",
        "ingestion_failures",
        ["status", "blocked_status"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_ingestion_failures_status_blocked_status", table_name="ingestion_failures")
    op.drop_column("ingestion_failures", "retry_count")
    op.drop_column("ingestion_failures", "blocked_status")
    op.drop_column("ingestion_failures", "url")

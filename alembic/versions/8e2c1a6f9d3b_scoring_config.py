"""scoring_config

Revision ID: 8e2c1a6f9d3b
Revises: 4d99f6acbb29
Create Date: 2026-07-06 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8e2c1a6f9d3b"
down_revision: str | Sequence[str] | None = "4d99f6acbb29"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "scoring_config",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("grade_a", sa.Float(), server_default="0.85", nullable=False),
        sa.Column("grade_b", sa.Float(), server_default="0.70", nullable=False),
        sa.Column("grade_c", sa.Float(), server_default="0.55", nullable=False),
        sa.Column("grade_d", sa.Float(), server_default="0.40", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("scoring_config")

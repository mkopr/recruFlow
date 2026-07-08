"""drop_scoring_config

Revision ID: ae9db2ab1e4a
Revises: ae533f38f5b2
Create Date: 2026-07-08 06:00:06.129504

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ae9db2ab1e4a"
down_revision: str | Sequence[str] | None = "ae533f38f5b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_table("scoring_config")


def downgrade() -> None:
    """Downgrade schema."""
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

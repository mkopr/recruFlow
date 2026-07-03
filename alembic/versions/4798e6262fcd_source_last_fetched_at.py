"""source last_fetched_at

Revision ID: 4798e6262fcd
Revises: 12bc4e296410
Create Date: 2026-07-03 16:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4798e6262fcd"
down_revision: str | Sequence[str] | None = "12bc4e296410"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "sources", sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("sources", "last_fetched_at")

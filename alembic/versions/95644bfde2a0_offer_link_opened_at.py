"""offer_link_opened_at

Revision ID: 95644bfde2a0
Revises: 7130773ba67b
Create Date: 2026-07-10 07:18:32.069079

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "95644bfde2a0"
down_revision: str | Sequence[str] | None = "7130773ba67b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("offers", sa.Column("link_opened_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("offers", "link_opened_at")

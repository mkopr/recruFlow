"""offer_location_unbounded

Revision ID: 306f60011cef
Revises: 95644bfde2a0
Create Date: 2026-07-15 13:51:08.629953

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "306f60011cef"
down_revision: str | Sequence[str] | None = "95644bfde2a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "offers",
        "location",
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "offers",
        "location",
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        existing_nullable=True,
    )

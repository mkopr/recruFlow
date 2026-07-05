"""offer_industry_tags

Revision ID: 4d99f6acbb29
Revises: 4798e6262fcd
Create Date: 2026-07-04 15:10:15.823328

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "4d99f6acbb29"
down_revision: str | Sequence[str] | None = "4798e6262fcd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "offers",
        sa.Column(
            "industry_tags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("offers", "industry_tags")

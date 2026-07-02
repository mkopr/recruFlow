"""offer_description_and_nullable_canonical_url

Revision ID: aa3fa339111b
Revises: df5297add8cb
Create Date: 2026-07-02 14:21:14.941527

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "aa3fa339111b"
down_revision: str | Sequence[str] | None = "df5297add8cb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("offers", sa.Column("description", sa.Text(), nullable=True))
    op.alter_column("offers", "canonical_url", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("offers", "canonical_url", existing_type=sa.Text(), nullable=False)
    op.drop_column("offers", "description")

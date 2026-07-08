"""match_scores_score_percent

Revision ID: ae533f38f5b2
Revises: 8e2c1a6f9d3b
Create Date: 2026-07-08 07:59:28.516323

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ae533f38f5b2"
down_revision: str | Sequence[str] | None = "8e2c1a6f9d3b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("match_scores", sa.Column("score_percent", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE match_scores SET score_percent = CASE grade "
        "WHEN 'A' THEN 92 WHEN 'B' THEN 77 WHEN 'C' THEN 62 WHEN 'D' THEN 47 ELSE 20 END"
    )
    op.alter_column("match_scores", "score_percent", nullable=False)
    op.drop_column("match_scores", "grade")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column("match_scores", sa.Column("grade", sa.String(length=1), nullable=True))
    op.execute(
        "UPDATE match_scores SET grade = CASE "
        "WHEN score_percent >= 85 THEN 'A' WHEN score_percent >= 70 THEN 'B' "
        "WHEN score_percent >= 55 THEN 'C' WHEN score_percent >= 40 THEN 'D' ELSE 'F' END"
    )
    op.alter_column("match_scores", "grade", nullable=False)
    op.drop_column("match_scores", "score_percent")

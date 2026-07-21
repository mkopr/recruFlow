"""match_scores_dedupe_race_duplicates

Revision ID: 134e4fa8b06d
Revises: ae9db2ab1e4a
Create Date: 2026-07-08 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "134e4fa8b06d"
down_revision: str | Sequence[str] | None = "ae9db2ab1e4a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Two unsynchronized scoring triggers previously raced and produced duplicate `match_scores`
    rows for the same (offer_id, profile_id) pair -- pure waste, since each row scored the
    exact same offer/profile combination. This is a one-off cleanup of that specific damage,
    keeping the newest row (highest id) per pair.

    No unique constraint is added on (offer_id, profile_id): docs/architecture/matching.md's
    "Unified Match Score schema" section documents this as a deliberate design decision -- the
    schema intentionally allows multiple `MatchScore` rows per offer over time (re-scores),
    with reads always taking the most recent row. The race's actual root cause (the two
    triggers scheduling concurrent runs against the same unscored backlog) is fixed in
    application code instead: the redundant trigger is removed and `run_batch_scoring` now
    serializes on a module-level lock, so it can never again schedule two concurrent runs
    against the same unscored backlog.
    """
    op.execute(
        "DELETE FROM match_scores a USING match_scores b "
        "WHERE a.offer_id = b.offer_id AND a.profile_id = b.profile_id AND a.id < b.id"
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Deleted duplicate rows cannot be un-deleted; nothing to reverse.

import asyncio
import logging
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import MatchScore as MatchScoreModel
from app.db.models import Offer as OfferModel
from app.db.models import ScoringFailure, Source
from app.db.profile_repo import get_active_profile
from app.ingestion.runner import resolve_fetch_range
from app.llm import matcher
from app.llm.matcher import MatcherChain, score_offers_with_langchain
from app.scoring.events import ScoreEvent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BatchScoringSummary:
    scored: int
    skipped: int
    failed: int
    remaining: int = 0
    score_events: tuple[ScoreEvent, ...] = ()


@dataclass
class ScoringProgress:
    """In-memory, single-process view of the current/last batch scoring run.

    A local single-user tool with one API process, so a module-level global is
    enough — no need for DB-backed job state just to answer "is scoring running
    right now" for the offer list page's progress banner.
    """

    running: bool = False
    processed: int = 0
    total: int = 0
    remaining_backlog: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_scored: int = 0
    last_skipped: int = 0
    last_failed: int = 0


_progress = ScoringProgress()

# BUG29: run_batch_scoring has independent callers (the scheduled backlog job and the
# manual /score/batch route) that can otherwise overlap in the same event loop -- each
# opens its own session and awaits real network calls to Ollama, leaving plenty of time
# for a second call to pick up the same "unscored" offers before the first commits. This
# lock serializes every run_batch_scoring call regardless of caller.
_scoring_lock = asyncio.Lock()


def get_scoring_progress() -> ScoringProgress:
    return _progress


def _open_scoring_failures(profile_id: int) -> Select[tuple[int]]:
    """Offer ids with an unresolved ScoringFailure for this profile.

    Excluded from selection so a batch doesn't keep spending its whole limit
    re-attempting offers that fail deterministically (e.g. BUG32's salary_fit
    validation bug) -- that starved genuinely-new offers of any progress since
    the same handful of offers are always "newest unscored" and get reselected
    every run. Resolving (or retrying via POST /failures/scoring/{id}/retry)
    the underlying ScoringFailure row makes an offer eligible again.
    """
    return select(ScoringFailure.offer_id).where(
        ScoringFailure.profile_id == profile_id, ScoringFailure.status == "open"
    )


def _candidate_offers_stmt(
    profile_id: int, connectors: Collection[str]
) -> Select[tuple[OfferModel, str, dict[str, Any]]]:
    already_scored = select(MatchScoreModel.offer_id).where(
        MatchScoreModel.profile_id == profile_id
    )
    return (
        select(OfferModel, Source.connector, Source.config_json)
        .join(Source, OfferModel.source_id == Source.id)
        .where(Source.connector.in_(connectors))
        .where(OfferModel.id.not_in(already_scored))
        .where(OfferModel.id.not_in(_open_scoring_failures(profile_id)))
        .order_by(
            OfferModel.posted_at.desc().nulls_last(),
            OfferModel.created_at.desc(),
            OfferModel.id.desc(),
        )
    )


def _in_fetch_range(offer: OfferModel, config_json: dict[str, Any] | None) -> bool:
    """Whether `offer` falls inside its Source's configured `fetch_range` (US34/US36).

    Undated offers evaluate as "now", same fallback `resolve_fetch_range`'s callers in
    `app/ingestion/runner.py` use (ADR 0017) -- never as "always eligible", since a
    genuinely narrow `until` should still exclude an offer with no determinable date.
    """
    since, until = resolve_fetch_range((config_json or {}).get("fetch_range"))
    if since is None and until is None:
        return True
    effective_date = offer.posted_at if offer.posted_at is not None else datetime.now(UTC)
    if since is not None and effective_date < since:
        return False
    if until is not None and effective_date > until:
        return False
    return True


@dataclass(frozen=True)
class CandidateSelection:
    """Result of `select_scoring_candidates`: a page of candidates plus the true total."""

    selected: tuple[tuple[OfferModel, str], ...]
    total: int


async def select_scoring_candidates(
    session: AsyncSession, profile_id: int, *, connectors: Collection[str], limit: int
) -> CandidateSelection:
    """The single seam for scoring candidate selection: ordering, exclusion,
    fetch-range, and connector scope, in one query.

    `total` in the result covers every in-range candidate regardless of `limit`,
    so a caller wanting only the count can pass `limit=0` -- one scan serves both
    a capped page and an accurate backlog total, instead of two independently
    re-executed statements.
    """
    rows = (await session.execute(_candidate_offers_stmt(profile_id, connectors))).all()
    in_range = tuple(
        (offer, connector)
        for offer, connector, config_json in rows
        if _in_fetch_range(offer, config_json)
    )
    return CandidateSelection(selected=in_range[:limit], total=len(in_range))


async def _count_already_scored(
    session: AsyncSession, profile_id: int, *, connectors: Collection[str]
) -> int:
    already_scored = select(MatchScoreModel.offer_id).where(
        MatchScoreModel.profile_id == profile_id
    )
    stmt = (
        select(func.count())
        .select_from(OfferModel)
        .join(Source, OfferModel.source_id == Source.id)
        .where(Source.connector.in_(connectors))
        .where(OfferModel.id.in_(already_scored))
    )
    return (await session.execute(stmt)).scalar_one()


async def count_unscored_backlog(
    session: AsyncSession, *, connectors: Collection[str] | None = None
) -> int:
    """Live count of offers not yet scored for the active profile.

    Computed on demand rather than cached from the last run, so it reflects the
    backlog immediately after a profile switch/edit -- before any run has picked
    it up.
    """
    profile_row = await get_active_profile(session)
    if profile_row is None:
        return 0
    scope = connectors if connectors is not None else matcher.LANGCHAIN_SOURCES
    selection = await select_scoring_candidates(session, profile_row.id, connectors=scope, limit=0)
    return selection.total


async def run_batch_scoring(
    session: AsyncSession,
    *,
    limit: int | None = None,
    connectors: Collection[str] | None = None,
    chain_factory: Callable[[], MatcherChain] | None = None,
) -> BatchScoringSummary:
    async with _scoring_lock:
        return await _run_batch_scoring_locked(
            session, limit=limit, connectors=connectors, chain_factory=chain_factory
        )


async def _run_batch_scoring_locked(
    session: AsyncSession,
    *,
    limit: int | None,
    connectors: Collection[str] | None,
    chain_factory: Callable[[], MatcherChain] | None,
) -> BatchScoringSummary:
    profile_row = await get_active_profile(session)
    if profile_row is None:
        logger.info("batch scoring skipped: no active profile")
        return BatchScoringSummary(scored=0, skipped=0, failed=0, remaining=0)

    scope = connectors if connectors is not None else matcher.LANGCHAIN_SOURCES
    batch_limit = limit if limit is not None else get_settings().batch_scoring_limit
    selection = await select_scoring_candidates(
        session, profile_row.id, connectors=scope, limit=batch_limit
    )
    total_unscored = selection.total
    unscored = list(selection.selected)
    skipped = await _count_already_scored(session, profile_row.id, connectors=scope)

    _progress.running = True
    _progress.processed = 0
    _progress.total = len(unscored)
    _progress.started_at = datetime.now(UTC)
    _progress.finished_at = None
    try:
        if chain_factory is not None:
            results = await score_offers_with_langchain(
                session,
                profile_row,
                unscored,
                connectors=scope,
                chain_factory=chain_factory,
                on_progress=_record_progress,
            )
        else:
            results = await score_offers_with_langchain(
                session,
                profile_row,
                unscored,
                connectors=scope,
                on_progress=_record_progress,
            )
    finally:
        _progress.running = False
        _progress.finished_at = datetime.now(UTC)

    await session.flush()
    offer_by_id = {offer.id: offer for offer, _ in unscored}
    score_events = tuple(
        ScoreEvent(
            score_id=row.id,
            offer_id=row.offer_id,
            title=offer_by_id[row.offer_id].title,
            company=offer_by_id[row.offer_id].company,
            score_percent=row.score_percent,
        )
        for row in results
    )

    failed = len(unscored) - len(results)
    remaining = max(total_unscored - len(unscored), 0)
    _progress.last_scored = len(results)
    _progress.last_skipped = skipped
    _progress.last_failed = failed
    _progress.remaining_backlog = remaining

    logger.info(
        "batch scoring run complete: scored=%d skipped=%d failed=%d remaining=%d",
        len(results),
        skipped,
        failed,
        remaining,
    )
    return BatchScoringSummary(
        scored=len(results),
        skipped=skipped,
        failed=failed,
        remaining=remaining,
        score_events=score_events,
    )


def _record_progress(processed: int) -> None:
    _progress.processed = processed

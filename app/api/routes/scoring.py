import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from app.api.deps import SessionDep
from app.schemas.scoring import BatchScoringResponse, ScoringStatusResponse
from app.scoring.batch import (
    count_total_offers,
    count_unscored_backlog,
    get_scoring_progress,
    run_batch_scoring,
)
from app.scoring.events import publish_score, subscribe, unsubscribe

router = APIRouter()


@router.post("/score/batch")
async def trigger_batch_scoring(session: SessionDep) -> BatchScoringResponse:
    summary = await run_batch_scoring(session)
    await session.commit()
    for event in summary.score_events:
        publish_score(event)
    return BatchScoringResponse(
        scored=summary.scored,
        skipped=summary.skipped,
        failed=summary.failed,
        remaining=summary.remaining,
    )


@router.get("/scoring/status")
async def scoring_status(session: SessionDep) -> ScoringStatusResponse:
    progress = get_scoring_progress()
    unscored_backlog = await count_unscored_backlog(session)
    total_offers = await count_total_offers(session)
    return ScoringStatusResponse(
        running=progress.running,
        processed=progress.processed,
        total=progress.total,
        remaining_backlog=progress.remaining_backlog,
        unscored_backlog=unscored_backlog,
        total_offers=total_offers,
        started_at=progress.started_at,
        finished_at=progress.finished_at,
        last_scored=progress.last_scored,
        last_skipped=progress.last_skipped,
        last_failed=progress.last_failed,
    )


@router.get("/scoring/events")
async def scoring_events(request: Request) -> EventSourceResponse:
    async def event_stream() -> AsyncIterator[dict[str, str]]:
        queue = subscribe()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    continue
                yield {
                    "event": "score",
                    "data": json.dumps(
                        {
                            "score_id": event.score_id,
                            "offer_id": event.offer_id,
                            "title": event.title,
                            "company": event.company,
                            "score_percent": event.score_percent,
                        }
                    ),
                }
        finally:
            unsubscribe(queue)

    return EventSourceResponse(event_stream())

from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class ScoreEvent:
    score_id: int
    offer_id: int
    title: str
    company: str
    score_percent: int


_subscribers: set[asyncio.Queue[ScoreEvent]] = set()


def subscribe() -> asyncio.Queue[ScoreEvent]:
    queue: asyncio.Queue[ScoreEvent] = asyncio.Queue()
    _subscribers.add(queue)
    return queue


def unsubscribe(queue: asyncio.Queue[ScoreEvent]) -> None:
    _subscribers.discard(queue)


def publish_score(event: ScoreEvent) -> None:
    for queue in _subscribers:
        queue.put_nowait(event)

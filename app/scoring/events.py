from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class GradeAEvent:
    score_id: int
    offer_id: int
    title: str
    company: str


_subscribers: set[asyncio.Queue[GradeAEvent]] = set()


def subscribe() -> asyncio.Queue[GradeAEvent]:
    queue: asyncio.Queue[GradeAEvent] = asyncio.Queue()
    _subscribers.add(queue)
    return queue


def unsubscribe(queue: asyncio.Queue[GradeAEvent]) -> None:
    _subscribers.discard(queue)


def publish_grade_a(event: GradeAEvent) -> None:
    for queue in _subscribers:
        queue.put_nowait(event)

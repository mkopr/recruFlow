import asyncio
import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Offer, Profile, Source
from app.db.session import get_sessionmaker

SEED_SOURCE_NAME = "seed"
SEED_PROFILE_NAME = "stub-profile"
SEED_OFFERS: list[dict[str, Any]] = [
    {
        "canonical_url": "https://example.com/jobs/backend-engineer",
        "title": "Backend Engineer",
        "company": "Example Sp. z o.o.",
        "location": "Warsaw",
        "remote": True,
        "seniority": "mid",
    },
    {
        "canonical_url": "https://example.com/jobs/data-engineer",
        "title": "Data Engineer",
        "company": "Example Sp. z o.o.",
        "location": "Krakow",
        "remote": False,
        "seniority": "senior",
    },
    {
        "canonical_url": "https://example.com/jobs/frontend-engineer",
        "title": "Frontend Engineer",
        "company": "Example Sp. z o.o.",
        "location": "Wroclaw",
        "remote": True,
        "seniority": "junior",
    },
]


def _dedup_hash(canonical_url: str) -> str:
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()


async def run_seed(session: AsyncSession) -> None:
    source_id = await _seed_source(session)
    await _seed_offers(session, source_id)
    await _seed_profile(session)


async def _seed_source(session: AsyncSession) -> int:
    stmt = (
        pg_insert(Source)
        .values(name=SEED_SOURCE_NAME, config_json={})
        .on_conflict_do_nothing(index_elements=[Source.name])
    )
    await session.execute(stmt)
    source_id = await session.scalar(select(Source.id).where(Source.name == SEED_SOURCE_NAME))
    assert source_id is not None
    return source_id


async def _seed_offers(session: AsyncSession, source_id: int) -> None:
    for offer in SEED_OFFERS:
        stmt = (
            pg_insert(Offer)
            .values(
                source_id=source_id,
                dedup_hash=_dedup_hash(offer["canonical_url"]),
                raw_payload={},
                **offer,
            )
            .on_conflict_do_nothing(index_elements=[Offer.dedup_hash])
        )
        await session.execute(stmt)


async def _seed_profile(session: AsyncSession) -> None:
    stmt = (
        pg_insert(Profile)
        .values(name=SEED_PROFILE_NAME, status="active", is_active=True, data={})
        .on_conflict_do_nothing(index_elements=[Profile.name])
    )
    await session.execute(stmt)


async def main() -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        await run_seed(session)
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())

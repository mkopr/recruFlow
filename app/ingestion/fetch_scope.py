from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.profile_repo import get_active_profile
from app.schemas.profile import Profile, hard_skill_names

FETCH_SCOPE_ALL = "all"
FETCH_SCOPE_FILTERED = "filtered"


@dataclass(frozen=True)
class FetchScopeResolution:
    mode: str
    terms: list[str]
    blocked_reason: str | None


def resolve_fetch_scope_mode(fetch_scope: dict[str, Any] | None) -> str:
    """Fails open to `FETCH_SCOPE_ALL` for a missing key or any malformed/unrecognised shape,
    mirroring `resolve_fetch_range`'s own convention (`app/ingestion/runner.py`)."""
    if not isinstance(fetch_scope, dict) or fetch_scope.get("mode") != FETCH_SCOPE_FILTERED:
        return FETCH_SCOPE_ALL
    return FETCH_SCOPE_FILTERED


def resolve_fetch_scope(mode: str, profile: Profile | None) -> FetchScopeResolution:
    if mode != FETCH_SCOPE_FILTERED:
        return FetchScopeResolution(mode=FETCH_SCOPE_ALL, terms=[], blocked_reason=None)
    if profile is None:
        return FetchScopeResolution(
            mode=FETCH_SCOPE_FILTERED,
            terms=[],
            blocked_reason="fetch scope is 'filtered' but no active profile is set",
        )
    terms = hard_skill_names(profile)
    if not terms:
        return FetchScopeResolution(
            mode=FETCH_SCOPE_FILTERED,
            terms=[],
            blocked_reason=(
                "fetch scope is 'filtered' but the active profile has no starred (hard) skills"
            ),
        )
    return FetchScopeResolution(mode=FETCH_SCOPE_FILTERED, terms=terms, blocked_reason=None)


async def resolve_fetch_scope_terms(
    session: AsyncSession, config: dict[str, Any]
) -> FetchScopeResolution:
    mode = resolve_fetch_scope_mode(config.get("fetch_scope"))
    if mode != FETCH_SCOPE_FILTERED:
        return FetchScopeResolution(mode=FETCH_SCOPE_ALL, terms=[], blocked_reason=None)
    profile_row = await get_active_profile(session)
    profile = Profile(**profile_row.data) if profile_row is not None else None
    return resolve_fetch_scope(FETCH_SCOPE_FILTERED, profile)

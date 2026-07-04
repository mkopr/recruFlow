from datetime import UTC, datetime

from app.api.routes.profile import _profile_response
from app.db.models import Profile as ProfileModel


def test_profile_response_builds_from_row_without_db() -> None:
    row = ProfileModel(
        id=1,
        name="active-profile",
        status="active",
        is_active=True,
        data={
            "skills": [],
            "past_roles": [],
            "education": [],
            "certifications": [],
            "languages": [],
            "deal_breakers": [],
        },
        created_at=datetime(2026, 6, 2, tzinfo=UTC),
        updated_at=datetime(2026, 6, 3, tzinfo=UTC),
    )

    result = _profile_response(row)

    assert result.id == 1
    assert result.name == "active-profile"
    assert result.status == "active"
    assert result.is_active is True
    assert result.profile.skills == []
    assert result.created_at == row.created_at
    assert result.updated_at == row.updated_at

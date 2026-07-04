import io
from collections.abc import AsyncGenerator

import docx
import httpx
import pytest
import pytest_asyncio
from app.db.models import Profile as ProfileModel
from app.llm.cv_extraction import CVExtractionError
from app.schemas.profile import CVExtraction, Skill
from reportlab.pdfgen import canvas
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

_SEEDED_ACTIVE_PROFILE_NAME = "upload-test-active-profile"


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _build_pdf_bytes(text: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, text)
    c.showPage()
    c.save()
    return buf.getvalue()


def _build_docx_bytes(text: str) -> bytes:
    buf = io.BytesIO()
    document = docx.Document()
    document.add_paragraph(text)
    document.save(buf)
    return buf.getvalue()


async def _delete_profile_by_name(session: AsyncSession, name: str) -> None:
    await session.execute(delete(ProfileModel).where(ProfileModel.name == name))
    await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upload_pdf_cv_creates_draft_profile(
    client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_call_llm(cv_text: str) -> CVExtraction:
        return CVExtraction(skills=[Skill(name="Go")])

    monkeypatch.setattr("app.llm.cv_extraction._call_llm", fake_call_llm)

    response = await client.post(
        "/profile/upload",
        files={"file": ("cv.pdf", _build_pdf_bytes("Go"), "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "draft"
    assert body["is_active"] is False
    assert body["profile"]["skills"][0]["name"] == "Go"

    await _delete_profile_by_name(db_session, body["name"])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upload_docx_cv_creates_draft_profile(
    client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_call_llm(cv_text: str) -> CVExtraction:
        return CVExtraction(skills=[Skill(name="Rust")])

    monkeypatch.setattr("app.llm.cv_extraction._call_llm", fake_call_llm)

    response = await client.post(
        "/profile/upload",
        files={
            "file": (
                "cv.docx",
                _build_docx_bytes("Rust"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "draft"
    assert body["is_active"] is False
    assert body["profile"]["skills"][0]["name"] == "Rust"

    await _delete_profile_by_name(db_session, body["name"])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upload_rejects_txt_file_with_415(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    count_before = len((await db_session.execute(select(ProfileModel))).scalars().all())

    response = await client.post(
        "/profile/upload",
        files={"file": ("cv.txt", b"not a cv", "text/plain")},
    )

    assert response.status_code == 415
    assert "detail" in response.json()

    count_after = len((await db_session.execute(select(ProfileModel))).scalars().all())
    assert count_after == count_before


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upload_cv_missing_optional_section_still_succeeds(
    client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_call_llm(cv_text: str) -> CVExtraction:
        return CVExtraction(skills=[Skill(name="Python")], certifications=[])

    monkeypatch.setattr("app.llm.cv_extraction._call_llm", fake_call_llm)

    response = await client.post(
        "/profile/upload",
        files={"file": ("cv.pdf", _build_pdf_bytes("Python"), "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["profile"]["certifications"] == []

    await _delete_profile_by_name(db_session, body["name"])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upload_draft_is_not_returned_as_active_profile(
    client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Other test modules can leave a stray active row behind between runs (they reset at the
    # start of their own tests, not the end) - clear every row's flag before seeding ours so
    # GET /profile can only see the row this test seeds.
    await db_session.execute(update(ProfileModel).values(is_active=False))
    await _delete_profile_by_name(db_session, _SEEDED_ACTIVE_PROFILE_NAME)
    active_row = ProfileModel(
        name=_SEEDED_ACTIVE_PROFILE_NAME,
        status="active",
        is_active=True,
        data={
            "skills": [{"name": "Java"}],
            "past_roles": [],
            "education": [],
            "certifications": [],
            "languages": [],
            "deal_breakers": [],
        },
    )
    db_session.add(active_row)
    await db_session.commit()

    async def fake_call_llm(cv_text: str) -> CVExtraction:
        return CVExtraction(skills=[Skill(name="Go")])

    monkeypatch.setattr("app.llm.cv_extraction._call_llm", fake_call_llm)

    upload_response = await client.post(
        "/profile/upload",
        files={"file": ("cv.pdf", _build_pdf_bytes("Go"), "application/pdf")},
    )
    draft_name = upload_response.json()["name"]

    get_response = await client.get("/profile")

    assert get_response.json()["profile"]["skills"][0]["name"] == "Java"

    active_rows = (
        (await db_session.execute(select(ProfileModel).where(ProfileModel.is_active.is_(True))))
        .scalars()
        .all()
    )
    assert len(active_rows) == 1
    assert active_rows[0].name == _SEEDED_ACTIVE_PROFILE_NAME

    await _delete_profile_by_name(db_session, draft_name)
    await _delete_profile_by_name(db_session, _SEEDED_ACTIVE_PROFILE_NAME)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upload_cv_extraction_failure_returns_503(
    client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_call_llm(cv_text: str) -> CVExtraction:
        raise CVExtractionError("ollama unreachable")

    monkeypatch.setattr("app.llm.cv_extraction._call_llm", fake_call_llm)

    count_before = len((await db_session.execute(select(ProfileModel))).scalars().all())

    response = await client.post(
        "/profile/upload",
        files={"file": ("cv.pdf", _build_pdf_bytes("Go"), "application/pdf")},
    )

    assert response.status_code == 503
    assert "ollama unreachable" in response.json()["detail"]

    count_after = len((await db_session.execute(select(ProfileModel))).scalars().all())
    assert count_after == count_before

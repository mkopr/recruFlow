import httpx
import pytest
from app.llm.cv_extraction import (
    _CONTACT_SYSTEM_PROMPT,
    _CORE_SYSTEM_PROMPT,
    _PROJECTS_SYSTEM_PROMPT,
    CVExtractionError,
    _build_messages,
    extract_profile_from_cv_text,
)
from app.schemas.profile import CVExtraction, Skill
from langchain_core.messages import BaseMessage


@pytest.mark.asyncio
async def test_extract_profile_from_cv_text_maps_extraction_into_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_call_llm(cv_text: str) -> CVExtraction:
        return CVExtraction(
            skills=[Skill(name="Go", category="language")],
            certifications=[],
            industry_tags=["fintech"],
            headline="Software Developer",
            email="marcin@example.com",
        )

    monkeypatch.setattr("app.llm.cv_extraction._call_llm", fake_call_llm)

    profile = await extract_profile_from_cv_text("irrelevant text")

    assert profile.skills[0].name == "Go"
    assert profile.skills[0].category == "language"
    assert profile.certifications == []
    assert profile.projects == []
    assert profile.industry_tags == ["fintech"]
    assert profile.headline == "Software Developer"
    assert profile.summary is None
    assert profile.email == "marcin@example.com"
    assert profile.phone is None
    assert profile.location is None
    assert profile.links == []
    assert profile.contract_type_preference is None
    assert profile.salary_min is None
    assert profile.salary_target is None
    assert profile.location_preference is None
    assert profile.remote_preference is None
    assert profile.deal_breakers == []


@pytest.mark.asyncio
async def test_extract_profile_from_cv_text_wraps_core_llm_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingChain:
        async def ainvoke(self, messages: list[BaseMessage]) -> None:
            raise httpx.HTTPError("connection refused")

    monkeypatch.setattr("app.llm.cv_extraction._build_core_chain", lambda: _FailingChain())

    with pytest.raises(CVExtractionError):
        await extract_profile_from_cv_text("irrelevant text")


@pytest.mark.asyncio
async def test_extract_profile_from_cv_text_wraps_contact_llm_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SucceedingChain:
        async def ainvoke(self, messages: list[BaseMessage]) -> object:
            return object()

    class _FailingChain:
        async def ainvoke(self, messages: list[BaseMessage]) -> None:
            raise httpx.HTTPError("connection refused")

    monkeypatch.setattr("app.llm.cv_extraction._build_core_chain", lambda: _SucceedingChain())
    monkeypatch.setattr("app.llm.cv_extraction._build_contact_chain", lambda: _FailingChain())

    with pytest.raises(CVExtractionError):
        await extract_profile_from_cv_text("irrelevant text")


@pytest.mark.asyncio
async def test_extract_profile_from_cv_text_wraps_projects_llm_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SucceedingChain:
        async def ainvoke(self, messages: list[BaseMessage]) -> object:
            return object()

    class _FailingChain:
        async def ainvoke(self, messages: list[BaseMessage]) -> None:
            raise httpx.HTTPError("connection refused")

    monkeypatch.setattr("app.llm.cv_extraction._build_core_chain", lambda: _SucceedingChain())
    monkeypatch.setattr("app.llm.cv_extraction._build_contact_chain", lambda: _SucceedingChain())
    monkeypatch.setattr("app.llm.cv_extraction._build_projects_chain", lambda: _FailingChain())

    with pytest.raises(CVExtractionError):
        await extract_profile_from_cv_text("irrelevant text")


@pytest.mark.asyncio
async def test_extract_profile_from_cv_text_reports_timeout_class_when_str_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _TimingOutChain:
        async def ainvoke(self, messages: list[BaseMessage]) -> None:
            raise httpx.ReadTimeout("")

    monkeypatch.setattr("app.llm.cv_extraction._build_core_chain", lambda: _TimingOutChain())

    with pytest.raises(CVExtractionError, match="CV extraction failed: ReadTimeout"):
        await extract_profile_from_cv_text("irrelevant text")


def test_build_messages_includes_core_facts_only_instruction() -> None:
    messages = _build_messages(_CORE_SYSTEM_PROMPT, "some cv text")

    system_message, human_message = messages
    assert isinstance(system_message.content, str)
    assert isinstance(human_message.content, str)
    system_text = system_message.content.lower()
    assert "infer" in system_text or "embellish" in system_text
    assert human_message.content == "some cv text"


def test_core_system_prompt_instructs_whole_document_skill_mining() -> None:
    system_text = _CORE_SYSTEM_PROMPT.lower()

    assert "entire" in system_text or "whole" in system_text
    assert "role" in system_text or "project" in system_text
    assert "summary" in system_text or "headline" in system_text
    assert "collapse" in system_text or "single skill entry" in system_text


def test_build_messages_includes_contact_facts_instruction() -> None:
    messages = _build_messages(_CONTACT_SYSTEM_PROMPT, "some cv text")

    system_message, human_message = messages
    assert isinstance(system_message.content, str)
    system_text = system_message.content.lower()
    assert "infer" in system_text or "embellish" in system_text
    assert "contact" in system_text or "email" in system_text
    assert human_message.content == "some cv text"


def test_build_messages_includes_projects_facts_instruction() -> None:
    messages = _build_messages(_PROJECTS_SYSTEM_PROMPT, "some cv text")

    system_message, human_message = messages
    assert isinstance(system_message.content, str)
    system_text = system_message.content.lower()
    assert "infer" in system_text or "embellish" in system_text
    assert "industry" in system_text
    assert "project" in system_text
    assert human_message.content == "some cv text"

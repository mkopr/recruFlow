import httpx
import pytest
from app.llm.cv_extraction import CVExtractionError, _build_messages, extract_profile_from_cv_text
from app.schemas.profile import CVExtraction, Skill
from langchain_core.messages import BaseMessage


@pytest.mark.asyncio
async def test_extract_profile_from_cv_text_maps_extraction_into_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_call_llm(cv_text: str) -> CVExtraction:
        return CVExtraction(skills=[Skill(name="Go")], certifications=[])

    monkeypatch.setattr("app.llm.cv_extraction._call_llm", fake_call_llm)

    profile = await extract_profile_from_cv_text("irrelevant text")

    assert profile.skills[0].name == "Go"
    assert profile.certifications == []
    assert profile.contract_type_preference is None
    assert profile.salary_min is None
    assert profile.salary_target is None
    assert profile.location_preference is None
    assert profile.remote_preference is None
    assert profile.deal_breakers == []


@pytest.mark.asyncio
async def test_extract_profile_from_cv_text_wraps_llm_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingChain:
        async def ainvoke(self, messages: list[BaseMessage]) -> CVExtraction:
            raise httpx.HTTPError("connection refused")

    monkeypatch.setattr("app.llm.cv_extraction._build_chain", lambda: _FailingChain())

    with pytest.raises(CVExtractionError):
        await extract_profile_from_cv_text("irrelevant text")


def test_build_messages_includes_facts_only_instruction() -> None:
    messages = _build_messages("some cv text")

    system_message, human_message = messages
    assert isinstance(system_message.content, str)
    assert isinstance(human_message.content, str)
    system_text = system_message.content.lower()
    assert "infer" in system_text or "embellish" in system_text
    assert human_message.content == "some cv text"

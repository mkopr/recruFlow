import logging

import httpx
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from langchain_ollama import ChatOllama
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.schemas.profile import (
    Certification,
    CVExtraction,
    Education,
    Language,
    PastRole,
    Profile,
    Project,
    Skill,
)

logger = logging.getLogger(__name__)

# Split into three smaller structured-output calls instead of one call covering every
# CVExtraction field. A single call (or even one covering all "extra" fields at once) pushes
# the combined input + schema + generated output past what this local 8B model can reliably
# produce within its context window - it was silently emitting empty lists for whatever didn't
# fit, rather than erroring, and testing showed even a "core + everything else" two-way split
# still dropped projects/industry_tags. Three focused calls keep each one's schema and expected
# output small enough to extract reliably.


class _CoreExtraction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    skills: list[Skill] = Field(default_factory=list)
    past_roles: list[PastRole] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)


class _ContactExtraction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    headline: str | None = None
    summary: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: list[str] = Field(default_factory=list)


class _ProjectsExtraction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    projects: list[Project] = Field(default_factory=list)
    industry_tags: list[str] = Field(default_factory=list)


_CORE_SYSTEM_PROMPT = (
    "You are extracting structured facts from a candidate's CV text. "
    "Extract only skills, past roles, education, certifications, and languages that are "
    "explicitly present in the CV text. "
    "For skills, search the *entire* document, not just a dedicated Skills/Tools section: also "
    "mine the summary/headline paragraph and every role or project description for named "
    "technologies, tools, methodologies, and other skills, and include every one of them. "
    "Collapse a skill mentioned in more than one place (e.g. once in a Skills section and again "
    "in a role description) into a single Skill entry. "
    "For each skill, set its category (e.g. language, framework, database, cloud, methodology, "
    "other) only if the CV itself groups skills under such a heading. "
    "Never infer, embellish, guess, or add anything that is not literally stated in the text. "
    "If a section is not present in the CV, leave the corresponding field as an empty list. "
    "Return structured output matching the given schema."
)

_CONTACT_SYSTEM_PROMPT = (
    "You are extracting structured facts from a candidate's CV text. "
    "Extract only a headline/summary and contact details (email, phone, location, links such as "
    "GitHub/LinkedIn) that are explicitly present in the CV text. "
    "Never infer, embellish, guess, or add anything that is not literally stated in the text. "
    "If a field is not present in the CV, leave it as an empty list (or null for a single "
    "value). "
    "Return structured output matching the given schema."
)

_PROJECTS_SYSTEM_PROMPT = (
    "You are extracting structured facts from a candidate's CV text. "
    "Extract only selected projects and industry/domain tags that are explicitly present in "
    "the CV text. "
    "Selected projects are distinct from past employment roles: extract them into 'projects' "
    "with their own name, description, tech stack, client, and team size only when the CV has "
    "a dedicated projects section separate from its employment history. "
    "For industry_tags, list only the industries/domains a role or project is explicitly named "
    "or described as belonging to (e.g. 'automotive', 'fintech') — never guess an industry from "
    "a company name alone. "
    "Never infer, embellish, guess, or add anything that is not literally stated in the text. "
    "If a section is not present in the CV, leave the corresponding field as an empty list. "
    "Return structured output matching the given schema."
)

_LLM_REQUEST_TIMEOUT_SECONDS = 120.0


class CVExtractionError(Exception):
    pass


def _build_messages(system_prompt: str, cv_text: str) -> list[BaseMessage]:
    return [SystemMessage(content=system_prompt), HumanMessage(content=cv_text)]


def _build_llm() -> ChatOllama:
    settings = get_settings()
    return ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=0,
        client_kwargs={"timeout": _LLM_REQUEST_TIMEOUT_SECONDS},
    )


def _build_core_chain() -> Runnable[list[BaseMessage], _CoreExtraction]:
    return _build_llm().with_structured_output(_CoreExtraction, method="json_schema")  # type: ignore[return-value]


def _build_contact_chain() -> Runnable[list[BaseMessage], _ContactExtraction]:
    return _build_llm().with_structured_output(_ContactExtraction, method="json_schema")  # type: ignore[return-value]


def _build_projects_chain() -> Runnable[list[BaseMessage], _ProjectsExtraction]:
    return _build_llm().with_structured_output(_ProjectsExtraction, method="json_schema")  # type: ignore[return-value]


def _describe(exc: Exception) -> str:
    return str(exc) or exc.__class__.__name__


async def _call_llm(cv_text: str) -> CVExtraction:
    try:
        core = await _build_core_chain().ainvoke(_build_messages(_CORE_SYSTEM_PROMPT, cv_text))
        contact = await _build_contact_chain().ainvoke(
            _build_messages(_CONTACT_SYSTEM_PROMPT, cv_text)
        )
        projects = await _build_projects_chain().ainvoke(
            _build_messages(_PROJECTS_SYSTEM_PROMPT, cv_text)
        )
    except (httpx.HTTPError, OSError) as exc:
        logger.error("CV extraction LLM call failed: %s", exc, exc_info=True)
        raise CVExtractionError(f"CV extraction failed: {_describe(exc)}") from exc
    except Exception as exc:
        logger.error("CV extraction LLM call failed unexpectedly: %s", exc, exc_info=True)
        raise CVExtractionError(f"CV extraction failed: {_describe(exc)}") from exc

    return CVExtraction(**core.model_dump(), **contact.model_dump(), **projects.model_dump())


async def extract_profile_from_cv_text(cv_text: str) -> Profile:
    extraction = await _call_llm(cv_text)
    return Profile(**extraction.model_dump())

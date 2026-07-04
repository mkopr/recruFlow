import logging

import httpx
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from langchain_ollama import ChatOllama

from app.config import get_settings
from app.schemas.profile import CVExtraction, Profile

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are extracting structured facts from a candidate's CV text. "
    "Extract only skills, past roles, education, certifications, and languages that are "
    "explicitly present in the CV text. "
    "Never infer, embellish, guess, or add anything that is not literally stated in the text. "
    "If a section is not present in the CV, leave the corresponding field as an empty list. "
    "Return structured output matching the given schema."
)

_LLM_REQUEST_TIMEOUT_SECONDS = 120.0


class CVExtractionError(Exception):
    pass


def _build_messages(cv_text: str) -> list[BaseMessage]:
    return [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=cv_text)]


def _build_chain() -> Runnable[list[BaseMessage], CVExtraction]:
    settings = get_settings()
    llm = ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=0,
        client_kwargs={"timeout": _LLM_REQUEST_TIMEOUT_SECONDS},
    )
    return llm.with_structured_output(CVExtraction, method="json_schema")  # type: ignore[return-value]


def _describe(exc: Exception) -> str:
    return str(exc) or exc.__class__.__name__


async def _call_llm(cv_text: str) -> CVExtraction:
    try:
        return await _build_chain().ainvoke(_build_messages(cv_text))
    except (httpx.HTTPError, OSError) as exc:
        logger.error("CV extraction LLM call failed: %s", exc, exc_info=True)
        raise CVExtractionError(f"CV extraction failed: {_describe(exc)}") from exc
    except Exception as exc:
        logger.error("CV extraction LLM call failed unexpectedly: %s", exc, exc_info=True)
        raise CVExtractionError(f"CV extraction failed: {_describe(exc)}") from exc


async def extract_profile_from_cv_text(cv_text: str) -> Profile:
    extraction = await _call_llm(cv_text)
    return Profile(**extraction.model_dump())

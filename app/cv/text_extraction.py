import io
import logging
from pathlib import Path

import docx
import pdfplumber

logger = logging.getLogger(__name__)


class UnsupportedFileTypeError(Exception):
    pass


def _extract_pdf_text(content: bytes) -> str:
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _extract_docx_text(content: bytes) -> str:
    document = docx.Document(io.BytesIO(content))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def extract_cv_text(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf_text(content)
    if suffix == ".docx":
        return _extract_docx_text(content)

    logger.warning("rejected unsupported CV file type: filename=%r", filename)
    raise UnsupportedFileTypeError(f"unsupported file type: {suffix or 'unknown'}")

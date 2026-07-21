import io
import logging
from dataclasses import dataclass
from pathlib import Path

import docx
import pdfplumber
from pdfplumber.page import Page

logger = logging.getLogger(__name__)


class UnsupportedFileTypeError(Exception):
    pass


# Multi-column CVs (e.g. a narrow skills sidebar next to a wide experience column) place
# unrelated columns at overlapping vertical positions. pdfplumber's plain extract_text() only
# clusters words into lines by vertical position and reads left-to-right across the full page
# width, so it splices sidebar words into the middle of unrelated body-column sentences.
# The heuristics below detect recurring x-position gaps between words on the same line and, when
# a gap recurs often enough to be a real column gutter (not just wide inter-word spacing), split
# each line at that gutter and emit each column as its own contiguous block of text instead.
_COLUMN_GAP_THRESHOLD = 10.0
_ROW_TOP_TOLERANCE = 3.0
_COLUMN_CLUSTER_TOLERANCE = 12.0
_MIN_ROWS_FOR_COLUMN = 3


@dataclass
class _Word:
    text: str
    x0: float
    x1: float
    top: float


def _page_words(page: Page) -> list[_Word]:
    return [
        _Word(text=word["text"], x0=word["x0"], x1=word["x1"], top=word["top"])
        for word in page.extract_words()
    ]


def _group_into_rows(words: list[_Word]) -> list[list[_Word]]:
    rows: list[list[_Word]] = []
    current: list[_Word] = []
    current_top: float | None = None
    for word in sorted(words, key=lambda w: w.top):
        if current_top is None or abs(word.top - current_top) <= _ROW_TOP_TOLERANCE:
            current.append(word)
            current_top = word.top if current_top is None else current_top
        else:
            rows.append(sorted(current, key=lambda w: w.x0))
            current = [word]
            current_top = word.top
    if current:
        rows.append(sorted(current, key=lambda w: w.x0))
    return rows


def _row_segments(row: list[_Word]) -> list[list[_Word]]:
    segments: list[list[_Word]] = [[row[0]]]
    for previous, word in zip(row, row[1:], strict=False):
        if word.x0 - previous.x1 >= _COLUMN_GAP_THRESHOLD:
            segments.append([])
        segments[-1].append(word)
    return segments


def _find_column_boundaries(rows: list[list[_Word]]) -> list[float]:
    # Cluster on the x0 of the word *after* each gap (the next column's left edge), which
    # stays fixed across rows, rather than the gap's midpoint, which drifts with how much the
    # preceding column's content happens to fill its line.
    column_starts = sorted(
        word.x0
        for row in rows
        for previous, word in zip(row, row[1:], strict=False)
        if word.x0 - previous.x1 >= _COLUMN_GAP_THRESHOLD
    )

    clusters: list[list[float]] = []
    for start in column_starts:
        if clusters and start - clusters[-1][-1] <= _COLUMN_CLUSTER_TOLERANCE:
            clusters[-1].append(start)
        else:
            clusters.append([start])

    return sorted(
        sum(cluster) / len(cluster) for cluster in clusters if len(cluster) >= _MIN_ROWS_FOR_COLUMN
    )


def _column_index(x: float, boundaries: list[float]) -> int:
    for index, boundary in enumerate(boundaries):
        if x < boundary:
            return index
    return len(boundaries)


def _join_rows_in_reading_order(rows: list[list[_Word]]) -> str:
    return "\n".join(" ".join(word.text for word in row) for row in rows)


def _join_rows_by_column(rows: list[list[_Word]], boundaries: list[float]) -> str:
    columns: dict[int, list[str]] = {}
    for row in rows:
        for segment in _row_segments(row):
            column = _column_index(segment[0].x0, boundaries)
            columns.setdefault(column, []).append(" ".join(word.text for word in segment))
    return "\n\n".join("\n".join(columns[index]) for index in sorted(columns))


def _extract_page_text(page: Page) -> str:
    rows = _group_into_rows(_page_words(page))
    if not rows:
        return ""

    boundaries = _find_column_boundaries(rows)
    if not boundaries:
        return _join_rows_in_reading_order(rows)
    return _join_rows_by_column(rows, boundaries)


def _extract_pdf_text(content: bytes) -> str:
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return "\n".join(_extract_page_text(page) for page in pdf.pages)


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

import io

import docx
import pytest
from app.cv.text_extraction import UnsupportedFileTypeError, extract_cv_text
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


def test_extract_cv_text_from_pdf_returns_text() -> None:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, "Python")
    c.drawString(72, 700, "Rust")
    c.showPage()
    c.save()

    result = extract_cv_text("cv.pdf", buf.getvalue())

    assert "Python" in result
    assert "Rust" in result


def _draw_char_by_char(c: canvas.Canvas, x: float, y: float, text: str, size: int = 12) -> None:
    """Draw each glyph as its own positioned text-show operator.

    Reproduces the per-glyph text-positioning some CV-builder exports use, which is
    what caused pypdf's extract_text() to shred real CVs into single letters.
    """
    cursor = x
    for ch in text:
        c.drawString(cursor, y, ch)
        cursor += stringWidth(ch, "Helvetica", size)


def test_extract_cv_text_from_pdf_with_per_glyph_positioning_does_not_shred_words() -> None:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    _draw_char_by_char(c, 72, 720, "Python")
    _draw_char_by_char(c, 72, 700, "Rust")
    c.showPage()
    c.save()

    result = extract_cv_text("cv.pdf", buf.getvalue())

    assert "Python" in result
    assert "Rust" in result
    assert "P y t h o n" not in result


def test_extract_cv_text_from_docx_returns_text() -> None:
    buf = io.BytesIO()
    document = docx.Document()
    document.add_paragraph("Senior Engineer")
    document.save(buf)

    result = extract_cv_text("cv.docx", buf.getvalue())

    assert "Senior Engineer" in result


def test_extract_cv_text_rejects_txt_extension() -> None:
    with pytest.raises(UnsupportedFileTypeError):
        extract_cv_text("cv.txt", b"plain text")


def test_extract_cv_text_rejects_missing_extension() -> None:
    with pytest.raises(UnsupportedFileTypeError):
        extract_cv_text("cv", b"...")


def test_extract_cv_text_from_pdf_with_two_column_layout_keeps_columns_intact() -> None:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    sidebar_lines = ["Skills:", "Python, Bash", "Django, Flask"]
    body_lines = ["Nov 2020 - NOW", "Senior Engineer", "Built things at Acme"]
    y = 700
    for sidebar_line, body_line in zip(sidebar_lines, body_lines, strict=True):
        c.drawString(50, y, sidebar_line)
        c.drawString(300, y, body_line)
        y -= 20
    c.showPage()
    c.save()

    result = extract_cv_text("cv.pdf", buf.getvalue())
    lines = [line for line in result.split("\n") if line.strip()]

    for sidebar_line in sidebar_lines:
        assert sidebar_line in lines
    for body_line in body_lines:
        assert body_line in lines
    for sidebar_line, body_line in zip(sidebar_lines, body_lines, strict=True):
        assert f"{sidebar_line} {body_line}" not in result
        assert f"{body_line} {sidebar_line}" not in result


def test_extract_cv_text_pdf_with_no_text_returns_empty_string_not_error() -> None:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.showPage()
    c.save()

    result = extract_cv_text("blank.pdf", buf.getvalue())

    assert isinstance(result, str)

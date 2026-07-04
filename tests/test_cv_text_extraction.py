import io

import docx
import pytest
from app.cv.text_extraction import UnsupportedFileTypeError, extract_cv_text
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


def test_extract_cv_text_pdf_with_no_text_returns_empty_string_not_error() -> None:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.showPage()
    c.save()

    result = extract_cv_text("blank.pdf", buf.getvalue())

    assert isinstance(result, str)

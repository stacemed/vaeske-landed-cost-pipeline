"""Tests for the text-layer/OCR-fallback compose logic.

These monkeypatch both the pypdf-backed extractor and the OCR module, so
the test suite never needs pypdf, PyMuPDF, pytesseract, or a real
`tesseract-ocr` binary installed -- only code that actually reads a real
PDF does.
"""

import landed_cost.drive.ocr as ocr_module
from landed_cost.drive import pdf_text


def test_uses_real_text_layer_without_touching_ocr(monkeypatch):
    monkeypatch.setattr(pdf_text, "extract_text_from_pdf_bytes", lambda data: "real invoice text")

    def _fail(*args, **kwargs):
        raise AssertionError("OCR should not run when the text layer has content")

    monkeypatch.setattr(ocr_module, "extract_text_via_ocr", _fail)

    text, used_ocr = pdf_text.extract_text_with_ocr_fallback(b"pdf-bytes")

    assert text == "real invoice text"
    assert used_ocr is False


def test_falls_back_to_ocr_when_text_layer_is_empty(monkeypatch):
    monkeypatch.setattr(pdf_text, "extract_text_from_pdf_bytes", lambda data: "")
    monkeypatch.setattr(ocr_module, "extract_text_via_ocr", lambda data, dpi=300: "ocr'd text")

    text, used_ocr = pdf_text.extract_text_with_ocr_fallback(b"pdf-bytes")

    assert text == "ocr'd text"
    assert used_ocr is True


def test_falls_back_to_ocr_when_text_layer_is_whitespace_only(monkeypatch):
    monkeypatch.setattr(pdf_text, "extract_text_from_pdf_bytes", lambda data: "   \n\n  ")
    monkeypatch.setattr(ocr_module, "extract_text_via_ocr", lambda data, dpi=300: "ocr'd text")

    text, used_ocr = pdf_text.extract_text_with_ocr_fallback(b"pdf-bytes")

    assert used_ocr is True


def test_ocr_still_empty_is_reported_as_used_ocr_true(monkeypatch):
    # A truly blank page: OCR was tried but found nothing either.
    monkeypatch.setattr(pdf_text, "extract_text_from_pdf_bytes", lambda data: "")
    monkeypatch.setattr(ocr_module, "extract_text_via_ocr", lambda data, dpi=300: "")

    text, used_ocr = pdf_text.extract_text_with_ocr_fallback(b"pdf-bytes")

    assert text == ""
    assert used_ocr is True

"""Extract plain text from a PDF's raw bytes.

Lazy-imports ``pypdf`` (optional ``drive`` dependency group) so the rest
of the package and its tests never need it installed -- only code that
actually reads a PDF's content does.
"""

from __future__ import annotations

import io


def extract_text_from_pdf_bytes(data: bytes) -> str:
    """Return the concatenated text of every page's real text layer.

    Returns "" if the PDF has no extractable text layer -- most commonly
    a scan or phone photo saved as PDF. Never attempts OCR itself; see
    ``extract_text_with_ocr_fallback`` for that.
    """
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_text_with_ocr_fallback(data: bytes) -> tuple[str, bool]:
    """Try the real text layer first; OCR the rendered page only if that
    comes back empty.

    Returns ``(text, used_ocr)`` so callers can flag OCR'd text as
    lower-confidence (it misreads characters -- confirmed on real files)
    rather than treating it the same as a genuine text layer. Requires
    the OCR extras (PyMuPDF, pytesseract, Pillow, and the system
    ``tesseract-ocr`` binary) only when the fallback actually triggers --
    see docs/DRIVE_INGESTION.md.
    """
    text = extract_text_from_pdf_bytes(data)
    if text.strip():
        return text, False

    from .ocr import extract_text_via_ocr

    return extract_text_via_ocr(data), True

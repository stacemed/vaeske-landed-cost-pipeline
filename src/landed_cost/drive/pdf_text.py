"""Extract plain text from a PDF's raw bytes.

Lazy-imports ``pypdf`` (optional ``drive`` dependency group) so the rest
of the package and its tests never need it installed -- only code that
actually reads a PDF's content does.
"""

from __future__ import annotations

import io


def extract_text_from_pdf_bytes(data: bytes) -> str:
    """Return the concatenated text of every page.

    Returns "" if the PDF has no extractable text layer -- most commonly
    a scanned image with no OCR pass, which this does not attempt (see
    the ``pdf`` skill/project for OCR if that becomes necessary).
    """
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)

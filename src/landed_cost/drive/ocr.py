"""OCR fallback for PDFs with no extractable text layer.

Some source documents are scans or phone photos saved as PDF -- pypdf
finds nothing because there's no text layer to find, not because
anything is broken. Confirmed 2026-09-09 against real Drive files: pypdf
returns "" and finds zero embedded image objects via ``page.images``, yet
the same files are clearly readable to a human -- the content is drawn
straight onto the page rather than stored as a separate image XObject
pypdf's shortcut walks. Rendering the page to a raster image and running
OCR on that sidesteps how the content got onto the page in the first
place.

Requires the optional ``ocr`` dependency group (PyMuPDF, pytesseract,
Pillow) AND the system ``tesseract-ocr`` binary
(``apt install tesseract-ocr`` / ``brew install tesseract``) -- see
docs/DRIVE_INGESTION.md. Lazy-imported so nothing else in the package
needs any of this installed.
"""

from __future__ import annotations


def extract_text_via_ocr(pdf_bytes: bytes, dpi: int = 300) -> str:
    """Render every page to an image and OCR it, returning the joined text.

    Meaningfully less reliable than a real text layer -- OCR
    misreads characters (seen on real files: "Bundle" -> "Bunlde",
    "Huang" -> "Huana", a stray space inserted mid-token). Callers should
    never treat OCR'd text as trustworthy enough to auto-file without a
    human check; see ``ExtractedInvoice`` usage in ``extract.py`` and
    ``InboxProposal`` in ``inbox.py``.
    """
    import io

    import pymupdf
    import pytesseract
    from PIL import Image

    document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    matrix = pymupdf.Matrix(dpi / 72, dpi / 72)

    texts = []
    for page in document:
        pixmap = page.get_pixmap(matrix=matrix)
        image = Image.open(io.BytesIO(pixmap.tobytes("png")))
        texts.append(pytesseract.image_to_string(image))
    return "\n".join(texts)

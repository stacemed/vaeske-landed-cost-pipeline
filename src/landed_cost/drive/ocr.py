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

2026-09-15: some scans are saved sideways -- confirmed on a real file
(a Wells Fargo wire confirmation) where OCR came back as unreadable
garbage ("6TTESCCCOVOOOOMO...") even though the page is perfectly
legible to a human once you tilt your head, because it was rendered
90 degrees from upright. ``page.rotation`` (the PDF's own ``/Rotate``
attribute) read 0 for this file -- the sideways orientation is baked
into how the page content itself was scanned, not page metadata, so
there was nothing to correct it against. Each page image is now passed
through Tesseract's own orientation detection first and rotated
upright before the real OCR pass runs.
"""

from __future__ import annotations


def _correct_orientation(image):
    """Rotate a PIL ``image`` upright first if Tesseract's orientation
    detection is confident it's sideways or upside down.

    Orientation detection needs enough real text on the page to work
    with, and raises on a near-blank or image-only page -- left as-is
    in that case (and on any other detection error) rather than
    guessing. A confirmed real fix, not a defensive guard: without
    this, a sideways scan silently comes back as garbage rather than as
    an error, and nothing downstream would notice.
    """
    import pytesseract

    try:
        osd = pytesseract.image_to_osd(image, output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractError:
        return image
    rotate = osd.get("rotate", 0)
    return image.rotate(-rotate, expand=True) if rotate else image


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
        image = _correct_orientation(image)
        texts.append(pytesseract.image_to_string(image))
    return "\n".join(texts)

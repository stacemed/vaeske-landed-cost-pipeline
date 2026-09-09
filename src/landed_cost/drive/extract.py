"""Guess a document's standardized filename fields from its PDF text.

This is a heuristic, not a guarantee. Freight (Shenzhen Linkhub) and
overhead (Weimin Huang inspection invoices) follow tight, regular formats
and extract reliably. Component purchase invoices don't: vendors use
inconsistent, one-off invoice-number formats, and the workbook itself has
purchase lines with no invoice number recorded at all (see
docs/DATA_MODEL.md on ComponentPurchaseLine). So components are always
flagged with an issue -- never silently auto-filed -- no matter how
plausible a guess looks, and a human confirms the invoice number and doc
type by hand for that category.

Tuned 2026-09-05 against a real batch of 85 2024 invoices/confirmations:
domestic wire confirmations to Weimin Huang show the payee as "WHYMON
FEDWIRE", never his name or company, so that's now a components-vendor
signal in its own right; some older Wells Fargo confirmations read "You
successfully submitted your wire" instead of "You submitted your wire";
and dates aren't always zero-padded (``4/21/2024``, not ``04/21/2024``).

2026-09-08: overhead invoice numbers drop the source text's "INV-"
prefix (``#INV-Inspection-250930`` in the PDF becomes ``Inspection-250930``
in the filename) -- redundant next to the doc-type suffix that already
says INV-paid/pconf/etc.

2026-09-09: OCR'd two more real overhead invoices and found Weimin Huang
issues more than one invoice *type* under the same "#INV-<Type>-######"
template -- "Inspection" and "Support" confirmed so far, likely others.
Routing no longer hardcodes "inspection": any text mentioning him (or his
"WHYMON" wire alias) that also contains a "#[INV-]<Word>-<ref>"-shaped
reference is treated as overhead; the same text without that reference
(a wire confirmation, a mention in passing) falls back to components,
which is the safe direction since components never auto-file anyway.
OCR itself misreads characters (seen: "Bundle" -> "Bunlde", a stray
space inside a reference number) -- text that came from OCR rather than
a real text layer never marks a document ready_to_file regardless of how
clean the guess looks; see ``InboxProposal.via_ocr`` in ``inbox.py``.

Never raises: an unrecognized document comes back with every field None
and an issue explaining why, so one weird PDF doesn't stop a batch run.
"""

from __future__ import annotations

import re
from datetime import date as date_cls
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from ..models.enums import Category, DocumentType

_DATE_FORMATS = ("%d-%b-%Y", "%d-%b-%y", "%m/%d/%Y", "%Y-%m-%d", "%b %d, %Y")

# Weimin Huang's own invoice template numbers references "#INV-<Type>-<ref>"
# (e.g. "#INV-Inspection-250930", "#INV-Support-240407") -- a shape that,
# per real evidence, Shenzhen Minzhi's component invoices don't use (their
# codes mix letters and digits in the "type" segment itself, e.g.
# "USR2312-01", which this pattern's letters-only type segment rejects).
_OVERHEAD_REFERENCE_RE = r"#\s*(?:INV-)?([A-Za-z]+-\s*[\w&]+)"

_WIRE_CONFIRMATION_KEYWORDS = (
    "wire money - confirmation",
    "you submitted your wire",
    "you successfully submitted your wire",
    "transfer confirmation",
    "wise us inc",
)
_REFUND_KEYWORDS = ("refund", "over payment", "overpayment")

# The entire extracted text is a bare filename -- Drive couldn't read this
# file's real content (seen with PDFs converted from an embedded .xlsx).
_FILENAME_STUB_RE = re.compile(r"^[\w .,&()'-]+\.(?:xlsx|xls|docx|doc|pdf|csv)$", re.IGNORECASE)

_KNOWN_COMPONENT_NAMES = (
    "rack box",
    "rack",
    "12 qt container",
    "12 qt lid",
    "12 qt sleeve",
    "12 qt master carton",
    "26 qt container",
    "26 qt lid",
    "26 qt sleeve",
    "26 qt inner box",
    "26 qt master carton",
    "insert card",
    "product label",
)


class ExtractedInvoice(BaseModel):
    """What the heuristic could (and couldn't) determine about a document."""

    model_config = ConfigDict(frozen=True)

    vendor_abbrev: str | None = None
    category: Category | None = None
    category_tag: str | None = None
    invoice_number: str | None = None
    doc_date: date_cls | None = None
    doc_type: DocumentType | None = None
    issues: tuple[str, ...] = ()

    @property
    def is_ready_to_file(self) -> bool:
        """True only when every field was found AND nothing was flagged.

        Components can never satisfy this -- see the module docstring --
        by design, not by accident.
        """
        return (
            not self.issues
            and self.vendor_abbrev is not None
            and self.category is not None
            and self.category_tag is not None
            and self.invoice_number is not None
            and self.doc_date is not None
            and self.doc_type is not None
        )


def _find_first(text: str, patterns: list[str]) -> str | None:
    """Return the first regex match across ``patterns`` that contains at
    least one digit.

    Every real invoice number in this business has a digit in it (dates,
    order codes, quantities baked into the code). Without this filter, a
    loose pattern like "invoice ... <word>" happily captures ordinary
    words such as "Subject" or "Transfer" when they follow the word
    "invoice" or "order" in running text -- a real false positive seen in
    a components wire-confirmation batch (2026-09-05).
    """
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            candidate = match.group(1)
            if any(ch.isdigit() for ch in candidate):
                return candidate
    return None


def _find_date(text: str, patterns: list[str]) -> date_cls | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        token = match.group(1)
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(token, fmt).date()
            except ValueError:
                continue
    return None


def _guess_doc_type(text: str, default: DocumentType | None) -> DocumentType | None:
    lowered = text.lower()
    if any(keyword in lowered for keyword in _WIRE_CONFIRMATION_KEYWORDS):
        return DocumentType.PAYMENT_CONFIRMATION
    if any(keyword in lowered for keyword in _REFUND_KEYWORDS):
        return DocumentType.REFUND_INVOICE
    return default


def _find_overhead_reference(text: str) -> str | None:
    """Find and normalize a "#[INV-]<Type>-<ref>" style reference, or
    None if the text doesn't have one. Strips any internal whitespace an
    OCR pass may have inserted (e.g. "Inspection- 240301" -> "Inspection-240301").
    """
    raw = _find_first(text, [_OVERHEAD_REFERENCE_RE])
    if raw is None:
        return None
    return re.sub(r"\s+", "", raw)


def extract_from_text(text: str) -> ExtractedInvoice:
    stripped = text.strip()
    if _FILENAME_STUB_RE.match(stripped):
        return ExtractedInvoice(
            issues=(
                "extracted text is just a filename, not real content -- Drive "
                "could not read this file (seen with PDFs converted from an "
                "embedded spreadsheet)",
            )
        )

    lowered = stripped.lower()

    if "shenzhen linkhub" in lowered or "fbabee" in lowered:
        return _extract_freight(text)

    # Components-vendor company names take priority over a personal-name
    # match below -- a components wire/invoice can still mention Weimin
    # Huang by name (he's the one being paid) without being his own
    # service invoice.
    if "shenzhen minzhi" in lowered or "byj trading" in lowered:
        return _extract_components(text)

    if "weimin huang" in lowered or "whymon huang" in lowered or "whymon" in lowered:
        # His own invoice template (any service type) has a
        # "#[INV-]<Type>-<ref>" reference; a wire confirmation or a
        # components document that merely mentions him doesn't. Treating
        # an ambiguous case as components is the safe direction --
        # components never auto-file, overhead can.
        if _find_overhead_reference(text) is not None:
            return _extract_overhead(text)
        return _extract_components(text)

    return ExtractedInvoice(issues=("could not identify a known vendor in the document text",))


def _extract_freight(text: str) -> ExtractedInvoice:
    issues: list[str] = []

    invoice_number = _find_first(text, [r"\b(JG\d{8,}[A-Z](?:-\w+)?)\b"])
    if invoice_number is None:
        issues.append("could not find a Linkhub-style invoice number (JG########E)")

    doc_date = _find_date(
        text,
        [
            r"INVOICE DATE\s+(\d{1,2}-[A-Za-z]{3}-\d{4})",
            r"INVOICE DATE\s+(\d{1,2}/\d{1,2}/\d{4})",
            r"You (?:successfully )?submitted your wire on\s+(\d{1,2}/\d{1,2}/\d{4})",
            r"SEND ON\s+(\d{1,2}/\d{1,2}/\d{4})",
        ],
    )
    if doc_date is None:
        issues.append("could not find an invoice or wire date")

    doc_type = _guess_doc_type(text, default=DocumentType.PAID_INVOICE)

    return ExtractedInvoice(
        vendor_abbrev="FBSL",
        category=Category.FREIGHT_BUNDLING_PACKAGING,
        category_tag="Frei-Bund",
        invoice_number=invoice_number,
        doc_date=doc_date,
        doc_type=doc_type,
        issues=tuple(issues),
    )


def _extract_overhead(text: str) -> ExtractedInvoice:
    issues: list[str] = []

    # The source text reads "#INV-Inspection-250930" or "#INV-Support-240407",
    # but the "INV-" is redundant in the filename (the doc-type suffix
    # already says INV-paid/pconf/etc.) -- normalized to drop it, per
    # 2026-09-08, and to strip any OCR-inserted whitespace, per 2026-09-09.
    invoice_number = _find_overhead_reference(text)
    if invoice_number is None:
        issues.append("could not find a '#[INV-]<Type>-<ref>' reference (e.g. Inspection, Support)")

    doc_date = _find_date(
        text,
        [
            r"Invoice Date:\s*(\d{1,2}-[A-Za-z]{3}-\d{2,4})",
            r"Invoice Date:\s*([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})",
        ],
    )
    if doc_date is None:
        issues.append("could not find an invoice date")

    doc_type = _guess_doc_type(text, default=DocumentType.PAID_INVOICE)

    return ExtractedInvoice(
        vendor_abbrev="WH",
        category=Category.OVERHEAD,
        category_tag="Over",
        invoice_number=invoice_number,
        doc_date=doc_date,
        doc_type=doc_type,
        issues=tuple(issues),
    )


def _extract_components(text: str) -> ExtractedInvoice:
    lowered = text.lower()
    issues: list[str] = [
        "component invoice numbers follow no consistent format across vendors "
        "(the workbook itself has purchase lines with none at all) -- always "
        "confirm the invoice number and doc type by hand for this category"
    ]

    invoice_number = _find_first(
        text,
        [
            r"(?:invoice|order)\s*#?\s*[:\-]?\s*([A-Z][A-Z0-9\-]{3,})",
            r"\b(INV-[A-Z0-9\-]+)\b",
        ],
    )

    doc_date = _find_date(
        text,
        [
            r"Invoice Date:\s*(\d{1,2}-[A-Za-z]{3}-\d{2,4})",
            r"Invoice Date:\s*([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})",
            r"You (?:successfully )?submitted your wire on\s+(\d{1,2}/\d{1,2}/\d{4})",
        ],
    )
    if doc_date is None:
        issues.append("could not find an invoice or wire date")

    doc_type = _guess_doc_type(text, default=None)

    matched_components = [name for name in _KNOWN_COMPONENT_NAMES if name in lowered]
    if matched_components:
        issues.append(f"matched known component names: {', '.join(matched_components)}")

    return ExtractedInvoice(
        vendor_abbrev="WHSM",
        category=Category.COMPONENTS,
        category_tag="comp",
        invoice_number=invoice_number,
        doc_date=doc_date,
        doc_type=doc_type,
        issues=tuple(issues),
    )


def propose_filename(extracted: ExtractedInvoice, extension: str) -> str:
    """Build a best-effort filename even from a partial extraction --
    missing fields become an ``UNKNOWN-*`` placeholder so a review report
    is legible instead of blank. Only meant to be applied to Drive
    (renaming a real file) when ``extracted.is_ready_to_file`` is True;
    the caller is responsible for checking that.
    """
    date_part = extracted.doc_date.isoformat() if extracted.doc_date else "UNKNOWN-DATE"
    vendor_part = extracted.vendor_abbrev or "UNKNOWN-VENDOR"
    category_part = extracted.category_tag or "UNKNOWN-CATEGORY"
    invoice_part = extracted.invoice_number or "UNKNOWN-INVOICE"
    doctype_part = extracted.doc_type.value if extracted.doc_type else "UNKNOWN-DOCTYPE"
    return f"{date_part}_{vendor_part}_{category_part}_{invoice_part}_{doctype_part}.{extension}"

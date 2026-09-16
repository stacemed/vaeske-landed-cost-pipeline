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

2026-09-15: components invoice numbers are sometimes absent from the
document's own invoice number field entirely but present in the
vendor's wire-payment memo instructions further down the page
("...message to receiver when making a payment: [ Black Oak Essentials
LLC] [USCLSLV26QT-24May] [...]") -- added as a fallback pattern, tried
only after the two body-text patterns come up empty. Drive's own text
extraction renders those brackets markdown-escaped (a literal backslash
before each "[" and "]"), so the pattern matches both escaped and plain
brackets.

2026-09-15: some invoices have their invoice-number/date header
rendered in a way ``pypdf``'s real text layer just doesn't pick up at
all (confirmed on a real file: the header is legible in the PDF viewer
but simply isn't in ``extract_text_from_pdf_bytes``'s output), while
the rest of the page extracts fine -- unlike the fully-blank-text-layer
case OCR already covered, this only shows up once you check which
*fields* came back empty, not whether the text as a whole did.
``ExtractedInvoice.is_fields_complete`` names that check (all six
fields, ignoring issues) so a caller can decide it's worth an OCR pass
on just the fields still missing; see ``propose_from_text``'s
``supplemental_text`` in ``inbox.py`` for where that pass happens.

2026-09-15: got the real Components naming convention (vendor
abbreviations, and how deposit/balance/full-payment invoices and their
confirmations are told apart) directly from the business owner --
previously this module just left doc_type at None for anything that
wasn't obviously a refund or a wire confirmation. Two changes:

- A second Components vendor, Shanghai Beone Industrial Co. (an
  Alibaba Trade Assurance seller, vendor_abbrev "SBIC"), alongside the
  existing Shenzhen Minzhi / Weimin Huang ("WHSM"). ``_extract_components``
  now takes ``vendor_abbrev`` from whichever company matched, rather
  than hardcoding "WHSM".
- ``_guess_components_doc_type`` classifies every Components document
  as a deposit, a balance, or a full (undivided) payment -- never just
  None -- using the invoice's own language. Confirmed on a real file
  that this isn't as simple as "which word appears": one invoice read
  "70% Down Payment Due" for what its own Subject line and payment
  breakdown make clear is actually the balance, since this vendor's
  standard split is 30% deposit / 70% balance. A percentage explicitly
  tied to "due" is trusted over the word sitting next to it for exactly
  this reason (see ``_guess_payment_stage``). Still never marks a
  Components document ready to file -- see the module's opening
  paragraph -- since the *installment number* on a balance (is this the
  first balance payment against this order, or the second?) genuinely
  can't be determined from one document in isolation.

2026-09-15: found (via the business owner manually reading 6 real
files that all landed in Review) that Weimin Huang's own *payment
confirmations* -- Wise "Transfer confirmation" documents -- almost
never carry the structured "#INV-Inspection-######" reference his
invoices do; just a free-text "Reference inspection 241027"-style memo
line, word order and spacing both varying. Routing required that
structured reference to treat a Whymon-mentioning document as
Overhead, so all 6 fell through to the Components fallback instead.
``_find_overhead_service_reference`` covers this specific real gap
(the word "inspection" plus a nearby date-code); confirmed against all
6 files, each producing the exact date/invoice-number/category the
business owner had already determined by hand. Scoped to "inspection"
only -- the other Overhead service types (Monthly retainer, Annual
bonus, Uncategorized transfer) don't have a confirmed real example of
this same gap yet.
"""

from __future__ import annotations

import re
from datetime import date as date_cls
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from ..models.enums import Category, DocumentType

_DATE_FORMATS = ("%d-%b-%Y", "%d-%b-%y", "%m/%d/%Y", "%Y-%m-%d", "%b %d, %Y", "%B %d, %Y")

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

# Components' second vendor (2026-09-15): orders placed through Alibaba's
# Trade Assurance flow, company name confirmed on a real order-details page.
_SBIC_KEYWORD = "shanghai beone"

# A component order is routinely split into a deposit and one or more
# balance payments; "down payment" and "deposit" are used interchangeably
# in practice. Real evidence (2026-09-15) also showed the reverse: a
# document that says "Down Payment Due" isn't always the deposit -- one
# vendor invoice read "70% Down Payment Due" for what its own Subject
# line and payment breakdown make clear is actually the *balance*
# (30% deposit / 70% balance is this vendor's usual split). So a
# percentage explicitly attached to "due" is trusted over the word next
# to it: >50% due means balance, <=50% means deposit, regardless of
# which word the vendor's template happened to use.
_DEPOSIT_KEYWORDS = ("deposit", "down payment")
_BALANCE_KEYWORDS = ("balance",)
_PCT_THEN_DUE_RE = r"(\d{1,3})\s*%\s*(?:down\s*payment|deposit|balance)(?:\s+payment)?\s+due"
_DUE_THEN_PCT_RE = r"due\s+(\d{1,3})\s*%"

# The entire extracted text is a bare filename -- Drive couldn't read this
# file's real content (seen with PDFs converted from an embedded .xlsx).
_FILENAME_STUB_RE = re.compile(r"^[\w .,&()'-]+\.(?:xlsx|xls|docx|doc|pdf|csv)$", re.IGNORECASE)

# Some invoices put the invoice number nowhere near the top -- it's
# buried in the vendor's own wire-payment memo instructions instead, as
# the second of three bracketed segments: "...message to receiver when
# making a payment: [ Black Oak Essentials LLC] [USCLSLV26QT-24May]
# [Containers&Lids&Sleeves]". Confirmed against a real 2024 invoice
# (2026-09-15) -- Drive's own text extraction renders the brackets
# markdown-escaped ("\[...\]"), so both forms are matched.
_REMARK_INVOICE_RE = (
    r"message to receiver when making (?:the |a )?payment:?\s*"
    r"\\?\[[^\]]*\\?\]\s*"
    r"\\?\[\s*([^\]\\]+?)\s*\\?\]"
)

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
    def is_fields_complete(self) -> bool:
        """True when every field was found, regardless of any issue flags.

        Distinct from ``is_ready_to_file``, which also requires zero
        issues -- a Components extraction (or one filled in partly via
        OCR) can have every field populated and still not be safe to
        auto-file. Used to decide whether it's worth trying harder (e.g.
        an OCR supplement pass) to fill in what's missing.
        """
        return (
            self.vendor_abbrev is not None
            and self.category is not None
            and self.category_tag is not None
            and self.invoice_number is not None
            and self.doc_date is not None
            and self.doc_type is not None
        )

    @property
    def is_ready_to_file(self) -> bool:
        """True only when every field was found AND nothing was flagged.

        Components can never satisfy this -- see the module docstring --
        by design, not by accident.
        """
        return not self.issues and self.is_fields_complete


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


def _normalize_date_token(token: str) -> str:
    """Undo two OCR artifacts seen on real invoices: the separator
    between a leading day number and month abbreviation sometimes
    renders as a space or vanishes entirely ("11 Jan-24", "2Jan-24"
    instead of "11-Jan-24"). A no-op on anything that doesn't start with
    digits immediately followed by letters, so month-first formats
    ("Jan 6, 2024") are untouched.
    """
    compact = token.replace(" ", "")
    return re.sub(r"^(\d{1,2})(?=[A-Za-z])", r"\1-", compact)


def _find_date(text: str, patterns: list[str]) -> date_cls | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        raw = match.group(1)
        for token in (raw, _normalize_date_token(raw)):
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


def _guess_payment_stage(text: str) -> str | None:
    """Return ``"deposit"``, ``"balance"``, or None (no split-payment
    language at all -- a single, undivided invoice).

    A percentage explicitly tied to "due" wins over which word (deposit/
    down payment/balance) it's attached to -- see the module-level
    comment on ``_PCT_THEN_DUE_RE`` for the real case this covers. Falls
    back to simple keyword presence when no such percentage is found;
    "balance" wins a tie only because by then a resolving percentage has
    already had its chance -- both keywords present with no percentage
    at all hasn't been observed on a real file yet.
    """
    lowered = text.lower()
    pct_match = re.search(_PCT_THEN_DUE_RE, lowered) or re.search(_DUE_THEN_PCT_RE, lowered)
    if pct_match:
        return "balance" if int(pct_match.group(1)) > 50 else "deposit"

    has_balance = any(keyword in lowered for keyword in _BALANCE_KEYWORDS)
    has_deposit = any(keyword in lowered for keyword in _DEPOSIT_KEYWORDS)
    if has_balance:
        return "balance"
    if has_deposit:
        return "deposit"
    return None


def _guess_components_doc_type(text: str, *, is_confirmation: bool) -> DocumentType:
    """Components tracks payment status per installment, unlike
    Overhead/Freight's simple paid-or-not -- see the ``DocumentType``
    docstring. Refund takes priority over payment-stage: a refund is a
    different kind of document entirely, not a deposit/balance/full
    invoice. Never returns None -- an invoice or confirmation with no
    split-payment or refund language at all is a single, undivided
    payment (``FULL_INVOICE`` / ``PAYMENT_CONFIRMATION_FULL``), per
    confirmed convention (2026-09-15). Always returns the *unnumbered*
    form even for a balance -- the automated guess can't know whether
    this is an order's first balance payment or its second, third...;
    a human bumps it to ``INV-bal2`` etc. by hand when it isn't the
    first (see the caution issue this triggers in ``_extract_components``).
    """
    lowered = text.lower()
    if any(keyword in lowered for keyword in _REFUND_KEYWORDS):
        return DocumentType.REFUND_INVOICE

    stage = _guess_payment_stage(text)
    if is_confirmation:
        if stage == "deposit":
            return DocumentType.PAYMENT_CONFIRMATION_DEPOSIT
        if stage == "balance":
            return DocumentType.PAYMENT_CONFIRMATION_BALANCE
        return DocumentType.PAYMENT_CONFIRMATION_FULL
    if stage == "deposit":
        return DocumentType.DEPOSIT_INVOICE
    if stage == "balance":
        return DocumentType.BALANCE_INVOICE
    return DocumentType.FULL_INVOICE


def _find_overhead_reference(text: str) -> str | None:
    """Find and normalize a "#[INV-]<Type>-<ref>" style reference, or
    None if the text doesn't have one. Strips any internal whitespace an
    OCR pass may have inserted (e.g. "Inspection- 240301" -> "Inspection-240301").
    """
    raw = _find_first(text, [_OVERHEAD_REFERENCE_RE])
    if raw is None:
        return None
    return re.sub(r"\s+", "", raw)


def _find_overhead_service_reference(text: str) -> str | None:
    """A looser fallback for Weimin Huang's own *payment confirmations*,
    which routinely don't carry the structured "#INV-Type-ref" reference
    at all -- confirmed on 6 real files (2026-09-15) misrouted to
    Components as a result, all Wise "Transfer confirmation" documents
    whose only reference is a free-text memo line: "Reference Inspection
    241027", "Reference inspection invoice 240112", "Reference rack
    inspection 240102" (word order and spacing both vary). Every one of
    those still has the word "inspection" with a trailing date-code
    nearby, which is what this looks for -- normalized to match the
    structured form ("Inspection-241027") so it reads the same in a
    filename either way. Only "inspection" is covered; the other
    Overhead service types (Monthly retainer, Annual bonus, Uncategorized
    transfer) don't have a confirmed real example of this gap yet, so
    guessing at those would be just that -- a guess.
    """
    match = re.search(r"inspection\D{0,20}?(\d{5,8})", text, re.IGNORECASE)
    if match is None:
        return None
    return f"Inspection-{match.group(1)}"


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

    # Weimin/company-specific signals are checked first, before the
    # freight signals below -- they're the more specific match, and a
    # document about something else can still mention "FBAbee" in
    # passing (e.g. an overhead invoice's line item reads "racks quality
    # check before FBAbee's bundling"; a components invoice reads
    # "delivery to FBABee warehouse"). Checking freight first mis-routed
    # both of those real files (2026-09-09).
    if "shenzhen minzhi" in lowered or "byj trading" in lowered:
        return _extract_components(text, vendor_abbrev="WHSM")

    if _SBIC_KEYWORD in lowered:
        return _extract_components(text, vendor_abbrev="SBIC")

    if "weimin huang" in lowered or "whymon huang" in lowered or "whymon" in lowered:
        # His own invoice template (any service type) has a
        # "#[INV-]<Type>-<ref>" reference; his *payment confirmations*
        # routinely don't -- just a free-text "Reference inspection
        # 241027" memo line instead, which _find_overhead_service_reference
        # covers (real bug, 2026-09-15: 6 real Inspection payment
        # confirmations fell through to Components before this, since
        # the safe-direction fallback below can't tell a real components
        # wire apart from an overhead one with no structured reference at
        # all). A components document that merely mentions him in passing
        # has neither.
        if _find_overhead_reference(text) is not None or _find_overhead_service_reference(text) is not None:
            return _extract_overhead(text)
        return _extract_components(text, vendor_abbrev="WHSM")

    # "to fbabee" (the wire recipient line), not bare "fbabee" -- the
    # word alone shows up incidentally in other vendors' documents too
    # (see the routing comment above).
    if "shenzhen linkhub" in lowered or "to fbabee" in lowered:
        return _extract_freight(text)

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
    # His payment confirmations don't carry that structured reference at
    # all -- _find_overhead_service_reference's looser "Reference
    # inspection ######" fallback covers those (2026-09-15).
    invoice_number = _find_overhead_reference(text) or _find_overhead_service_reference(text)
    if invoice_number is None:
        issues.append("could not find a '#[INV-]<Type>-<ref>' reference (e.g. Inspection, Support)")

    doc_date = _find_date(
        text,
        [
            r"Invoice Date[:.]?\s*(\d{1,2}\s*-?\s*[A-Za-z]{3,9}\s*-\s*\d{2,4})",
            r"Invoice Date[:.]?\s*([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})",
            # His Wise payment confirmations carry no "Invoice Date" at
            # all -- only "Transfer created <full month> <day>, <year>",
            # confirmed on the same 6 real files.
            r"Transfer created\s+([A-Za-z]+\s+\d{1,2},\s*\d{4})",
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


def _extract_components(text: str, *, vendor_abbrev: str) -> ExtractedInvoice:
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
            _REMARK_INVOICE_RE,
        ],
    )

    doc_date = _find_date(
        text,
        [
            r"Invoice Date[:.]?\s*(\d{1,2}\s*-?\s*[A-Za-z]{3,9}\s*-\s*\d{2,4})",
            r"Invoice Date[:.]?\s*([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})",
            r"You (?:successfully )?submitted your wire on\s+(\d{1,2}/\d{1,2}/\d{4})",
        ],
    )
    if doc_date is None:
        issues.append("could not find an invoice or wire date")

    is_confirmation = any(keyword in lowered for keyword in _WIRE_CONFIRMATION_KEYWORDS)
    doc_type = _guess_components_doc_type(text, is_confirmation=is_confirmation)
    if doc_type in (DocumentType.BALANCE_INVOICE, DocumentType.PAYMENT_CONFIRMATION_BALANCE):
        issues.append(
            "guessed this is a balance payment, but not which installment -- "
            "bump the doc-type suffix to bal2/bal3/etc. by hand if this isn't "
            "the first balance against this order"
        )

    matched_components = [name for name in _KNOWN_COMPONENT_NAMES if name in lowered]
    if matched_components:
        issues.append(f"matched known component names: {', '.join(matched_components)}")

    return ExtractedInvoice(
        vendor_abbrev=vendor_abbrev,
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

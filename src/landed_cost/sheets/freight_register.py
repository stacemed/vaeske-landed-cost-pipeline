"""Builds 1 TRANSACTIONS Section D (FREIGHT INVOICE REGISTER) rows from
the filed documents in "Invoices - Freight-Bundling", grouped by invoice
number.

Confirmed against real 2024-2026 Shenzhen Linkhub / FBSL documents
(2026-09-18):

- Older invoices (through mid-2024) use a fixed template with two
  "SUB TOTAL" lines -- the first under "FREIGHT CHARGES" (Freight $),
  the second under "ADDITIONAL CHARGES" (Bundling $) -- followed by a
  "GRAND TOTAL" that's their sum.
- Newer invoices (confirmed on real July 2024 and 2026 files) dropped
  that per-section breakdown entirely: every charge -- freight legs,
  Bundling, and sometimes extra packaging materials (Tape, Airbags,
  Polybags) or surcharges (Remote area surcharge) -- is just one more
  line item under a single combined "Subtotal"/"TOTAL US$", with no
  subtotal per category at all. For these,
  ``_extract_freight_and_bundling_from_line_items`` sums each
  recognized line item's own extended dollar amount (the LAST "$"
  figure on its line -- earlier ones are unit rates) into Freight $ or
  Bundling $ by keyword. The invoice's own "TOTAL US$" line (present on
  both template eras) is then used to cross-check the sum -- flagged,
  not blocked, if they disagree by more than a cent (a real invoice's
  own per-line rounding can differ from a re-summed total by exactly a
  cent; anything more suggests an unrecognized line-item keyword).
- The wire-confirmation payment document does NOT carry the Freight/
  Bundling split either way (e.g. "Amount $990.04" alone), so the
  dollar split always comes from the INVOICE text, never the payment
  confirmation's.
- The payment confirmation's "Amount $" line is still useful as a
  second cross check against the invoice's own Freight + Bundling
  total -- flagged (not blocking) if they disagree by more than a cent,
  since a wire fee or partial payment would show up here.
- Real invoice numbers sometimes carry a country suffix (``JG20240115E-CA``,
  ``JG20240422E-US``) when one shipment splits across FBA regions, but the
  wire that pays for them references only the base number
  (``JG20240115E``) -- confirmed via a real Wells Fargo confirmation whose
  "Message to recipient's bank" read "invoice JG20240108E" (unsuffixed).
  Per the user's own choice (2026-09-18): each suffixed invoice keeps its
  own register row (using its own stated Freight $/Bundling $, no
  summing), and every invoice sharing a base number gets the same Paid
  date once that base number's payment confirmation is found.
- A refund invoice (``INV-refund``) posts as a NEGATIVE Freight $ in the
  real sheet (confirmed: -$2,861.85 with $0 Bundling) -- there's no
  separate refund payment document, so Payment Link stays blank.
- Per DocumentType's own docstring, Freight-Bundling (unlike Components)
  never actually uses deposit/balance-staged doc types in practice -- so
  every invoice/payment pair here goes in Section D's "Deposit
  invoice"/"Deposit payment" columns (confirmed: every real Section D row
  uses only those two columns; "Balance invoice"/"Balance payment 1" are
  always blank).
"""

from __future__ import annotations

import re
from datetime import date as date_cls
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict

from ..models.documents import SourceDocument
from ..models.enums import DocumentType

_INVOICE_DOC_TYPES = {
    DocumentType.PAID_INVOICE,
    DocumentType.REFUND_INVOICE,
    DocumentType.FULL_INVOICE,
    DocumentType.UNPAID_INVOICE,
}
_PAYMENT_DOC_TYPES = {
    DocumentType.PAYMENT_CONFIRMATION,
    DocumentType.PAYMENT_CONFIRMATION_FULL,
}

_SUB_TOTAL_PATTERN = re.compile(r"SUB TOTAL\s+US\$\s*([\d,]+\.\d{2})", re.IGNORECASE)
_PAYMENT_AMOUNT_PATTERN = re.compile(r"\bAmount\s+\$\s*([\d,]+\.\d{2})", re.IGNORECASE)
# Present on both the old and new invoice templates alike -- "THANK YOU
# FOR YOUR BUSINESS TOTAL US$990.04" / "TOTAL US$2,144.19". The negative
# lookbehind excludes the old template's own "SUB TOTAL US$..." lines,
# which would otherwise match too (and, appearing earlier in the text,
# would be found first).
_INVOICE_TOTAL_PATTERN = re.compile(r"(?<!SUB )\bTOTAL\s+US\$\s*([\d,]+\.\d{2})", re.IGNORECASE)

# Newer-template line items, by which Section D column their own
# extended dollar amount belongs in. Confirmed against real July 2024
# and 2026 invoices -- a freight leg starts "DDP Sea Freight" or "DDP
# Truck Freight" (a real shipping-mode variant, confirmed 2026-09-24),
# and "Remote area surcharge" is a per-shipment surcharge tied to one of
# those legs, so all three count as Freight $; the rest are packaging
# materials/labor, so they count as Bundling $. Not exhaustive -- an
# unrecognized future line item (a real example: "Pickup Samples to
# testing company", confirmed 2026-09-24) is skipped rather than
# guessed at, and shows up as a Freight+Bundling sum that doesn't match
# the invoice's own TOTAL, which is flagged (see
# build_freight_register_rows), not silently dropped.
_FREIGHT_LINE_ITEM_KEYWORDS = ("DDP Sea Freight", "DDP Truck Freight", "Remote area surcharge")
_BUNDLING_LINE_ITEM_KEYWORDS = ("Bundling", "Tape", "Airbags", "Polybags")
_LINE_ITEM_AMOUNT_PATTERN = re.compile(r"\$\s*([\d,]+\.\d{2})")
_SUBTOTAL_STOP_PATTERN = re.compile(r"\bSubtotal\b", re.IGNORECASE)

# A base invoice number is "JG" + digits + "E"; anything after that is a
# per-shipment/region suffix ("-CA", "-US", "-CA+DE", "-Refurn", ...).
_BASE_INVOICE_NUMBER_PATTERN = re.compile(r"^(JG\d+E)(?:-.+)?$")


def _classify_line_item(chunk_lower: str) -> str | None:
    for keyword in _FREIGHT_LINE_ITEM_KEYWORDS:
        if chunk_lower.startswith(keyword.lower()):
            return "freight"
    for keyword in _BUNDLING_LINE_ITEM_KEYWORDS:
        if chunk_lower.startswith(keyword.lower()):
            return "bundling"
    return None


def _extract_freight_and_bundling_from_line_items(text: str) -> tuple[Decimal | None, Decimal | None]:
    """Fallback for the newer invoice template, which has no per-section
    subtotal at all -- sums each recognized line item's own extended
    dollar amount into Freight $ or Bundling $ by its starting keyword.

    Real text extracts as one "paragraph" (blank-line-delimited chunk)
    per logical unit -- a single-line item like "Bundling $0.62 per
    piece 1092 $672.34" is its own chunk; a freight leg splits across
    two ("DDP Sea Freight SPD LH01281197 Ship to BER8" naming the leg,
    then "20 CTNS | ... $2.10 per kgs 404.26 $848.95" with its amount).
    Working chunk-by-chunk (not by finding the next *recognized*
    keyword, tried first and reverted 2026-09-24) matters because an
    unrecognized line item can sit between two recognized ones (a real
    example: "Pickup Samples to testing company $16.00..." right after
    a real "Bundling $1,184.86..." line) -- reading up to the next
    recognized keyword would silently swallow that unrelated trailing
    amount as if it were the preceding line's own total. Chunking stops
    that at the paragraph boundary instead; an unrecognized chunk is
    just skipped, surfacing as a shortfall against the invoice's own
    stated total (see build_freight_register_rows) rather than a wrong
    number.
    """
    stop_match = _SUBTOTAL_STOP_PATTERN.search(text)
    region = text[:stop_match.start()] if stop_match else text
    chunks = [c.strip() for c in region.split("\n\n") if c.strip()]

    freight_total = Decimal("0")
    bundling_total = Decimal("0")
    found_any_amount = False
    i = 0
    while i < len(chunks):
        bucket = _classify_line_item(chunks[i].lower())
        if bucket is None:
            i += 1
            continue

        amounts = _LINE_ITEM_AMOUNT_PATTERN.findall(chunks[i])
        if not amounts and i + 1 < len(chunks):
            # A description-only chunk ("DDP Sea Freight...") -- its
            # amount is on the next chunk, the detail line. Consume it
            # too so it isn't re-examined as its own (unrecognized) item.
            i += 1
            amounts = _LINE_ITEM_AMOUNT_PATTERN.findall(chunks[i])

        if amounts:
            try:
                amount = Decimal(amounts[-1].replace(",", ""))
            except InvalidOperation:
                amount = None
            if amount is not None:
                found_any_amount = True
                if bucket == "freight":
                    freight_total += amount
                else:
                    bundling_total += amount
        i += 1

    if not found_any_amount:
        return None, None
    return freight_total, bundling_total


def extract_freight_and_bundling(text: str) -> tuple[Decimal | None, Decimal | None]:
    """Freight $ and Bundling $ from an invoice's own text.

    Tries the older two-"SUB TOTAL"-line template first (the first line
    is Freight, the second is Bundling -- or Bundling is ``Decimal("0")``
    if there's only one, an invoice with no bundling charge). Falls back
    to summing individual line items (see
    ``_extract_freight_and_bundling_from_line_items``) for the newer
    template, which has no per-section subtotal at all. Returns
    ``(None, None)`` if neither approach finds anything.
    """
    matches = _SUB_TOTAL_PATTERN.findall(text)
    if matches:
        try:
            amounts = [Decimal(m.replace(",", "")) for m in matches]
        except InvalidOperation:
            return _extract_freight_and_bundling_from_line_items(text)
        freight = amounts[0]
        bundling = amounts[1] if len(amounts) > 1 else Decimal("0")
        return freight, bundling
    return _extract_freight_and_bundling_from_line_items(text)


def extract_invoice_total(text: str) -> Decimal | None:
    """The invoice's own stated grand total -- used only as a cross
    check against the extracted Freight + Bundling sum, present on both
    the old and new template eras alike.
    """
    match = _INVOICE_TOTAL_PATTERN.search(text)
    if not match:
        return None
    try:
        return Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None


def extract_payment_amount(text: str) -> Decimal | None:
    """The wire confirmation's own stated "Amount $" -- used only as a
    cross-check against the invoice's Freight + Bundling total, never as
    the source of the split itself (the confirmation doesn't carry one).
    """
    match = _PAYMENT_AMOUNT_PATTERN.search(text)
    if not match:
        return None
    try:
        return Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None


def base_invoice_number(invoice_number: str) -> str:
    """Strip a per-region/shipment suffix down to the shared base number
    a combined wire payment actually references (e.g. ``JG20240115E-CA``
    -> ``JG20240115E``). Returns ``invoice_number`` unchanged if it
    doesn't match the ``JG########E`` shape at all.
    """
    match = _BASE_INVOICE_NUMBER_PATTERN.match(invoice_number)
    return match.group(1) if match else invoice_number


class FreightRegisterRow(BaseModel):
    """One row of 1 TRANSACTIONS Section D. ``prep_sheet_link`` is left
    blank here -- filled in by a separate Drive lookup step, since this
    module does no I/O.
    """

    model_config = ConfigDict(frozen=True)

    invoice_number: str
    invoice_date: date_cls | None
    paid_date: date_cls | None
    freight_amount: Decimal | None
    bundling_amount: Decimal | None
    invoice_link: str
    payment_link: str
    prep_sheet_label: str
    prep_sheet_link: str = ""
    flagged: bool
    flag_reason: str = ""


def _prep_sheet_label(d: date_cls) -> str:
    return f"{d:%Y-%m} {d:%b}".upper()


def build_freight_register_rows(
    documents: list[tuple[SourceDocument, str]],
) -> list[FreightRegisterRow]:
    """Group filed Freight documents by invoice number and build one
    register row per group.

    ``documents`` is every filed file's ``(SourceDocument, extracted PDF
    text)`` pair -- callers are responsible for reading each file's text
    (with OCR fallback) before calling this; this function does no I/O,
    so it's fully testable without Drive or PDF dependencies.
    """
    groups: dict[str, list[tuple[SourceDocument, str]]] = {}
    payments_by_base: dict[str, list[tuple[SourceDocument, str]]] = {}
    for doc, text in documents:
        groups.setdefault(doc.invoice_number, []).append((doc, text))
        if doc.doc_type in _PAYMENT_DOC_TYPES:
            payments_by_base.setdefault(base_invoice_number(doc.invoice_number), []).append((doc, text))

    # A payment confirmation that only ever pays for OTHER (suffixed)
    # invoices shares its own invoice_number with none of them -- e.g. a
    # "JG20240115E_pconf.pdf" paying for "JG20240115E-CA"/"-US" invoices
    # forms its own group here (invoice_number == "JG20240115E", no
    # invoice items). That group must not become its own register row --
    # its dollars are already attributed via payments_by_base below to
    # the invoices it actually pays for.
    bases_with_invoices = {
        base_invoice_number(inv_num)
        for inv_num, items in groups.items()
        if any(d.doc_type in _INVOICE_DOC_TYPES for d, _ in items)
    }

    rows: list[FreightRegisterRow] = []
    for invoice_number, items in sorted(groups.items()):
        invoice_items = [(d, t) for d, t in items if d.doc_type in _INVOICE_DOC_TYPES]
        payment_items = [(d, t) for d, t in items if d.doc_type in _PAYMENT_DOC_TYPES]

        if not invoice_items and base_invoice_number(invoice_number) in bases_with_invoices:
            continue

        # Multi-region invoices (a suffixed invoice_number) are paid by
        # one wire that references only the base number -- fall back to
        # every payment confirmation sharing that base when this exact
        # invoice number has none of its own.
        if not payment_items:
            payment_items = payments_by_base.get(base_invoice_number(invoice_number), [])

        invoice_link = ", ".join(sorted(d.raw_filename for d, _ in invoice_items))
        payment_link = ", ".join(sorted(d.raw_filename for d, _ in payment_items))

        invoice_date = invoice_items[0][0].doc_date if invoice_items else None
        payment_dates = [d.doc_date for d, _ in payment_items]
        paid_date = max(payment_dates) if payment_dates else invoice_date

        # The split only ever appears in an invoice's own text -- a
        # payment confirmation never carries it, but a best-effort
        # attempt costs nothing if one is ever filed with different text.
        freight_amount = bundling_amount = None
        for _, text in invoice_items:
            freight_amount, bundling_amount = extract_freight_and_bundling(text)
            if freight_amount is not None:
                break
        if freight_amount is None:
            for _, text in payment_items:
                freight_amount, bundling_amount = extract_freight_and_bundling(text)
                if freight_amount is not None:
                    break

        flagged = freight_amount is None
        flag_reason = (
            "could not extract Freight $/Bundling $ from any document for this "
            "invoice -- fill in by hand"
            if flagged
            else ""
        )

        if not flagged:
            computed_total = freight_amount + bundling_amount
            for _, text in invoice_items:
                stated_total = extract_invoice_total(text)
                if stated_total is None:
                    continue
                if abs(stated_total - computed_total) > Decimal("0.01"):
                    flagged = True
                    flag_reason = (
                        f"invoice states a total of ${stated_total} but the extracted "
                        f"Freight + Bundling line items sum to ${computed_total} -- a "
                        f"line item may not have been recognized, check by hand"
                    )
                break

        if not flagged and payment_items:
            computed_total = freight_amount + bundling_amount
            for _, text in payment_items:
                payment_amount = extract_payment_amount(text)
                if payment_amount is None:
                    continue
                if abs(payment_amount - computed_total) > Decimal("0.01"):
                    flagged = True
                    flag_reason = (
                        f"payment confirmation states ${payment_amount} but invoice "
                        f"Freight + Bundling totals ${computed_total} -- check for a "
                        f"wire fee or partial payment"
                    )
                break

        # Applied last, after both cross-checks -- they validate that
        # extraction read the invoice's own (always positive) line items
        # correctly, which is a separate question from the refund/credit
        # sign convention Section D itself stores.
        is_refund = any(d.doc_type == DocumentType.REFUND_INVOICE for d, _ in invoice_items)
        if is_refund and freight_amount is not None:
            freight_amount = -abs(freight_amount)
            bundling_amount = -abs(bundling_amount) if bundling_amount else bundling_amount

        paid_date_or_invoice_date = paid_date or invoice_date
        prep_sheet_label = _prep_sheet_label(paid_date_or_invoice_date) if paid_date_or_invoice_date else ""

        rows.append(
            FreightRegisterRow(
                invoice_number=invoice_number,
                invoice_date=invoice_date,
                paid_date=paid_date,
                freight_amount=freight_amount,
                bundling_amount=bundling_amount,
                invoice_link=invoice_link,
                payment_link=payment_link,
                prep_sheet_label=prep_sheet_label,
                flagged=flagged,
                flag_reason=flag_reason,
            )
        )
    return rows

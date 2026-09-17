"""Builds 1 TRANSACTIONS Section D (FREIGHT INVOICE REGISTER) rows from
the filed documents in "Invoices - Freight-Bundling", grouped by invoice
number.

Confirmed against real 2024-2025 Shenzhen Linkhub / FBSL documents
(2026-09-18):

- An invoice's own text is a fixed, machine-generated template with two
  "SUB TOTAL" lines -- the first under "FREIGHT CHARGES" (Freight $),
  the second under "ADDITIONAL CHARGES" (Bundling $) -- followed by a
  "GRAND TOTAL" that's their sum. The wire-confirmation payment document
  does NOT carry this split (e.g. "Amount $990.04" alone), so unlike
  Overhead, the dollar split is read from the INVOICE text, never the
  payment confirmation's.
- The payment confirmation's "Amount $" line is still useful as a cross
  check against the invoice's own Freight + Bundling total -- flagged
  (not blocking) if they disagree by more than a cent, since a wire fee
  or partial payment would show up here.
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

# A base invoice number is "JG" + digits + "E"; anything after that is a
# per-shipment/region suffix ("-CA", "-US", "-CA+DE", "-Refurn", ...).
_BASE_INVOICE_NUMBER_PATTERN = re.compile(r"^(JG\d+E)(?:-.+)?$")


def extract_freight_and_bundling(text: str) -> tuple[Decimal | None, Decimal | None]:
    """Freight $ and Bundling $ from an invoice's own text, in that
    order -- the first "SUB TOTAL" line is Freight, the second is
    Bundling. Returns ``(None, None)`` if no "SUB TOTAL" line is found
    at all; if exactly one is found (an invoice with no bundling charge),
    Bundling $ is ``Decimal("0")``.
    """
    matches = _SUB_TOTAL_PATTERN.findall(text)
    if not matches:
        return None, None
    try:
        amounts = [Decimal(m.replace(",", "")) for m in matches]
    except InvalidOperation:
        return None, None
    freight = amounts[0]
    bundling = amounts[1] if len(amounts) > 1 else Decimal("0")
    return freight, bundling


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

        is_refund = any(d.doc_type == DocumentType.REFUND_INVOICE for d, _ in invoice_items)
        if is_refund and freight_amount is not None:
            freight_amount = -abs(freight_amount)
            bundling_amount = -abs(bundling_amount) if bundling_amount else bundling_amount

        flagged = freight_amount is None
        flag_reason = (
            "could not extract Freight $/Bundling $ from any document for this "
            "invoice -- fill in by hand"
            if flagged
            else ""
        )

        if not flagged and payment_items:
            for _, text in payment_items:
                payment_amount = extract_payment_amount(text)
                if payment_amount is None:
                    continue
                invoice_total = freight_amount + bundling_amount
                if abs(payment_amount - invoice_total) > Decimal("0.01"):
                    flagged = True
                    flag_reason = (
                        f"payment confirmation states ${payment_amount} but invoice "
                        f"Freight + Bundling totals ${invoice_total} -- check for a "
                        f"wire fee or partial payment"
                    )
                break

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

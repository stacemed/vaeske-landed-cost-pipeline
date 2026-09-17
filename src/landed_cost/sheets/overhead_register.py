"""Builds 1 TRANSACTIONS Section E (OVERHEAD INVOICE REGISTER) rows from
the filed documents in "Invoices - Overhead", grouped by invoice number.

Unlike Section A (landed_cost.sheets.qbo), every field this needs except
the dollar amount is already free -- the filename convention Phase A
enforces already encodes invoice number, date, and whether a file is an
invoice or a payment confirmation (SourceDocument.doc_type). Only the
Overhead $ amount needs the PDF's actual content, since no filename
encodes a dollar figure.

Confirmed against real 2024 Weimin Huang documents (2026-09-17):

- A Wise payment confirmation's text always states the same amount at
  least twice, most reliably as "Total to WEIMIN HUANG <amount> USD" --
  e.g. "Total to WEIMIN HUANG 218.00 USD". This is what makes Overhead
  extraction trustworthy enough to not flag by default (unlike
  Components, whose vendor invoice formats are inconsistent): a Wise
  confirmation is a fixed, machine-generated template.
- Weimin Huang's own invoices (Inspection, Support, etc. -- often
  scanned, needs OCR) state the total as "Total $<amount>" or
  "Balance Due" followed by "$<amount>" on its own line.

Amount is always taken from a payment confirmation over an invoice when
both exist, matching the "use the pconf's actual paid amount" rule
established for Section A.
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
    DocumentType.DEPOSIT_INVOICE,
    DocumentType.BALANCE_INVOICE,
    DocumentType.UNPAID_INVOICE,
}
_PAYMENT_DOC_TYPES = {
    DocumentType.PAYMENT_CONFIRMATION,
    DocumentType.PAYMENT_CONFIRMATION_DEPOSIT,
    DocumentType.PAYMENT_CONFIRMATION_BALANCE,
    DocumentType.PAYMENT_CONFIRMATION_FULL,
}

# Ordered most-specific/reliable first. A Wise confirmation's "Total to
# WEIMIN HUANG" line is the most trustworthy -- it's the actual payee
# amount from a fixed machine-generated template, not free text.
_AMOUNT_PATTERNS = [
    re.compile(r"Total to WEIMIN HUANG\s+([\d,]+\.\d{2})\s*USD", re.IGNORECASE),
    re.compile(r"Transfer amount\s+([\d,]+\.\d{2})\s*USD", re.IGNORECASE),
    re.compile(r"Amount paid by[^\n]*?([\d,]+\.\d{2})\s*USD", re.IGNORECASE),
    re.compile(r"Balance Due\s*\n+\s*\$\s*([\d,]+\.\d{2})", re.IGNORECASE),
    re.compile(r"Total\s*\$\s*([\d,]+\.\d{2})", re.IGNORECASE),
]


def extract_overhead_amount(text: str) -> Decimal | None:
    """Best-effort dollar amount from an Overhead invoice/confirmation's
    text. Returns ``None`` (never a guess) if nothing matches.
    """
    for pattern in _AMOUNT_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                return Decimal(match.group(1).replace(",", ""))
            except InvalidOperation:
                continue
    return None


class OverheadRegisterRow(BaseModel):
    """One row of 1 TRANSACTIONS Section E."""

    model_config = ConfigDict(frozen=True)

    invoice_number: str
    invoice_date: date_cls | None
    paid_date: date_cls | None
    amount: Decimal | None
    invoice_link: str
    payment_link: str
    flagged: bool
    flag_reason: str = ""


def build_overhead_register_rows(
    documents: list[tuple[SourceDocument, str]],
) -> list[OverheadRegisterRow]:
    """Group filed Overhead documents by invoice number and build one
    register row per group.

    ``documents`` is every filed file's ``(SourceDocument, extracted PDF
    text)`` pair -- callers are responsible for reading each file's text
    (with OCR fallback) before calling this; this function does no I/O,
    so it's fully testable without Drive or PDF dependencies.
    """
    groups: dict[str, list[tuple[SourceDocument, str]]] = {}
    for doc, text in documents:
        groups.setdefault(doc.invoice_number, []).append((doc, text))

    rows: list[OverheadRegisterRow] = []
    for invoice_number, items in sorted(groups.items()):
        invoice_items = [(d, t) for d, t in items if d.doc_type in _INVOICE_DOC_TYPES]
        payment_items = [(d, t) for d, t in items if d.doc_type in _PAYMENT_DOC_TYPES]

        invoice_link = ", ".join(sorted(d.raw_filename for d, _ in invoice_items))
        payment_link = ", ".join(sorted(d.raw_filename for d, _ in payment_items))

        invoice_date = invoice_items[0][0].doc_date if invoice_items else None
        payment_dates = [d.doc_date for d, _ in payment_items]
        # Payment confirmation date preferred (actual cash movement);
        # fall back to the invoice's own date when no confirmation is
        # filed at all -- matches the Section A convention that an
        # Overhead/Freight invoice with no separate pconf is assumed
        # paid on its own stated date.
        paid_date = max(payment_dates) if payment_dates else invoice_date

        amount = None
        for _, text in payment_items:
            amount = extract_overhead_amount(text)
            if amount is not None:
                break
        if amount is None:
            for _, text in invoice_items:
                amount = extract_overhead_amount(text)
                if amount is not None:
                    break

        flagged = amount is None
        flag_reason = (
            "could not extract a dollar amount from any document for this "
            "invoice -- fill in Overhead $ by hand"
            if flagged
            else ""
        )

        rows.append(
            OverheadRegisterRow(
                invoice_number=invoice_number,
                invoice_date=invoice_date,
                paid_date=paid_date,
                amount=amount,
                invoice_link=invoice_link,
                payment_link=payment_link,
                flagged=flagged,
                flag_reason=flag_reason,
            )
        )
    return rows

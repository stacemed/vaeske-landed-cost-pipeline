"""Builds 1 TRANSACTIONS Section C (COMPONENT INVOICE REGISTER) rows from
the filed documents in "Invoices - Components" (and, per real Drive
layout, a second folder "Invoices - Components- Paid in 2025" -- the
2025 orders were filed there instead, under a different owner).

Components is meaningfully messier than Freight/Overhead, confirmed
against real 2024-2025 WHSM (Shenzhen Minzhi BYJ Trading Company) and
SBIC (Shanghai Beone Industrial Co., an Alibaba Trade Assurance seller)
documents (2026-10-20):

- An order is routinely split into a deposit and one or more balance
  payments (up to 4 tracked separately -- "Balance payment 1" through
  "Balance payment 4" in the real sheet), unlike Freight/Overhead's
  simple paid-or-not. A single, undivided order (no split at all) still
  uses the Deposit invoice/Deposit payment columns -- confirmed against
  a real register row (INV-26Q1PKG) whose only filed document is an
  "INV-paid-full" invoice sitting in the Deposit invoice slot.
- Real filenames drift from the documented "INV-bal[N]"/"pconf-bal[N]"
  convention in several ways -- "INV-bal-paid", "INV-paid-bal", bare
  numbered "pconf-1"/"pconf-2" with no "-bal" qualifier at all,
  "INV-paid-full" for a one-shot invoice, and a payment confirmation's
  own token carrying an accidental "INV-" prefix meant for an invoice
  token instead ("INV-pconf-dep", "INV-pconf-bal1"). See
  ``models.documents``'s ``_classify_doc_type`` for where these are now
  recognized.
- A single deposit document can fund TWO separate final orders that
  later get their own register rows (e.g. one "...-B1-B2_INV-dep.pdf"
  deposit, register rows "INV-25Q4RPC26S-B01"/"-B02" each with their
  own balance invoice) -- the deposit's own filename invoice number
  doesn't exactly match either register row's invoice number (neither
  the "-B1-B2" combined form nor a single "-B1" matches the register's
  zero-padded "-B01"). Per the project owner's own choice, this module
  never tries to auto-split or auto-normalize that -- it only matches a
  filed document to an EXISTING register row by an exact (case-
  insensitive) invoice-number match; a document whose invoice number
  doesn't exactly match any existing row is reported as unmatched, never
  guessed at or silently dropped.
- "Total Order $" is extracted from whichever filed document states it
  most reliably (tried in order: deposit invoice, balance invoice, full
  invoice), using known label phrasings per vendor -- "Sub Total" and
  "Total Invoice Amount"/"Total Invoice Cost" for WHSM (confirmed across
  two different real WHSM template eras), "Total Product Price USD" for
  SBIC (whose "invoice" is actually a saved Alibaba Trade Assurance
  order-details page, not a vendor-issued PDF at all). When extraction
  fails (a real 2025 WHSM balance invoice's own table layout extracts
  with the total number displaced from its "Sub Total" label entirely --
  confirmed via pypdf's actual output, not a guess), this is flagged,
  never guessed at, and the sheet's existing "Total Order $" value is
  left untouched by the caller rather than overwritten with nothing.
- "Invoice Adjustments" (exchange-rate fees/credits) is NEVER computed
  by this module at all, even though one real file explicitly states it
  ("Down Payment Considering Exchange Rate Change: 0.5%") -- the
  business owner already maintains this figure by hand for every
  existing order, and attempting to re-derive it from one observed,
  vendor-template-specific, easily-misread phrasing risks silently
  overwriting a correct, already-curated number with a wrong guess. A
  caller (components_sync.py) always preserves whatever is already in
  that column.
"""

from __future__ import annotations

import re
from datetime import date as date_cls
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field

from ..models.documents import SourceDocument
from ..models.enums import DocumentType

_DEPOSIT_INVOICE_DOC_TYPES = {
    DocumentType.DEPOSIT_INVOICE,
    DocumentType.FULL_INVOICE,
    DocumentType.PAID_INVOICE,
    DocumentType.UNPAID_INVOICE,
}
_DEPOSIT_PAYMENT_DOC_TYPES = {
    DocumentType.PAYMENT_CONFIRMATION_DEPOSIT,
    DocumentType.PAYMENT_CONFIRMATION_FULL,
    DocumentType.PAYMENT_CONFIRMATION,
}
_BALANCE_INVOICE_DOC_TYPES = {DocumentType.BALANCE_INVOICE}
_BALANCE_PAYMENT_DOC_TYPES = {DocumentType.PAYMENT_CONFIRMATION_BALANCE}

_MAX_BALANCE_PAYMENT_SLOTS = 4

# WHSM's own invoice text uses either of two known total-amount labels,
# confirmed across real invoices from different years/templates --
# "Sub Total" (both the 2024 deposit-invoice and 2025 single-undivided-
# invoice templates) and "Total Invoice Amount"/"Total Invoice Cost"
# (a different real 2024 balance-invoice template). SBIC's "invoice" is
# a saved Alibaba order-details page whose own total reads "Order
# total USD <amount>" (its "Total Product Price" line, checked second,
# is less reliable -- it's the line-item subtotal, not necessarily the
# same figure once shipping/fees are added).
_TOTAL_ORDER_AMOUNT_PATTERNS = (
    re.compile(r"Sub\s*Total\s*\$\s*([\d,]+\.\d{2})", re.IGNORECASE),
    re.compile(r"Total\s+Invoice\s+(?:Amount|Cost)\s*[:：]?\s*\$\s*([\d,]+\.\d{2})", re.IGNORECASE),
    re.compile(r"Order\s+total\s*\n?\s*USD\s*([\d,]+\.\d{2})", re.IGNORECASE),
    re.compile(r"Total\s+Product\s+Price\s+USD\s*([\d,]+\.\d{2})", re.IGNORECASE),
)

# A Wells Fargo wire confirmation's own stated amount -- same template
# Freight/Overhead's own payment confirmations use (see
# freight_register.py's _PAYMENT_AMOUNT_PATTERN), but without that
# pattern's \b/\s+ assumptions: a real Components confirmation's text
# runs the preceding word directly into "AMOUNT$<n>" with no separator
# at all ("Available balancAMOUNT$3,999.60"), confirmed via pypdf's own
# output -- a word-boundary anchor can never match that, so this is a
# plain substring search instead (safe here: no other word in this
# template's text ends in "amount").
_PAYMENT_AMOUNT_PATTERN = re.compile(r"AMOUNT\s*\$\s*([\d,]+\.\d{2})", re.IGNORECASE)
# SBIC's own payment is a credit/debit card charge through Alibaba, not
# a wire -- "Your payment amount USD 1255.50 is currently being
# processed."
_SBIC_PAYMENT_AMOUNT_PATTERN = re.compile(r"payment amount USD\s*([\d,]+\.\d{2})", re.IGNORECASE)

_CENT_TOLERANCE = Decimal("0.01")


def _parse_amount(match: re.Match[str] | None) -> Decimal | None:
    if match is None:
        return None
    try:
        return Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None


def extract_total_order_amount(text: str) -> Decimal | None:
    """The order's own stated total, before adding back in whatever
    "Invoice Adjustments" the sheet already carries for it -- see this
    module's docstring for why adjustments are never computed here.
    """
    for pattern in _TOTAL_ORDER_AMOUNT_PATTERNS:
        amount = _parse_amount(pattern.search(text))
        if amount is not None:
            return amount
    return None


def extract_payment_amount(text: str) -> Decimal | None:
    """A payment confirmation's own stated amount -- a wire's "AMOUNT"
    or Alibaba's "payment amount" -- used only as a cross-check against
    the matching invoice amount, never as the source of it.
    """
    amount = _parse_amount(_PAYMENT_AMOUNT_PATTERN.search(text))
    if amount is not None:
        return amount
    return _parse_amount(_SBIC_PAYMENT_AMOUNT_PATTERN.search(text))


def balance_installment_number(doc_type_raw: str) -> int:
    """Which of the 4 "Balance payment" columns a payment confirmation's
    own doc-type suffix belongs in -- the first digit found anywhere in
    the raw suffix (``pconf-bal2`` -> 2, bare ``pconf-1`` -> 1), or 1
    when there's no digit at all (``pconf-bal``, the unnumbered-first-
    balance convention).
    """
    match = re.search(r"\d+", doc_type_raw)
    return int(match.group()) if match else 1


class ComponentRegisterRow(BaseModel):
    """One row of 1 TRANSACTIONS Section C, rebuilt from every document
    CURRENTLY filed against an invoice number that already has a row in
    the live sheet -- see this module's docstring for why a brand-new
    invoice number, or a document that doesn't exactly match one, is
    never auto-inserted.

    ``total_order_amount`` is the freshly extracted figure (or None if
    extraction failed, in which case a caller must leave the sheet's
    existing value untouched -- never overwrite a real number with a
    blank). ``invoice_adjustments`` is deliberately absent: this module
    never computes it, a caller always preserves whatever is already in
    that column.
    """

    model_config = ConfigDict(frozen=True)

    invoice_number: str
    invoice_date: date_cls | None
    balance_paid_date: date_cls | None
    total_order_amount: Decimal | None

    deposit_invoice_link: str = ""
    deposit_invoice_file_ids: list[str] = Field(default_factory=list)
    deposit_payment_link: str = ""
    deposit_payment_file_ids: list[str] = Field(default_factory=list)
    balance_invoice_link: str = ""
    balance_invoice_file_ids: list[str] = Field(default_factory=list)
    # Index 0 -> "Balance payment 1" ... index 3 -> "Balance payment 4".
    balance_payment_links: tuple[str, str, str, str] = ("", "", "", "")
    balance_payment_file_ids: tuple[
        tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]
    ] = ((), (), (), ())

    flagged: bool = False
    flag_reason: str = ""


def _filenames_and_ids(
    items: list[tuple[SourceDocument, str]], file_ids: dict[str, str]
) -> tuple[str, list[str]]:
    names = sorted(d.raw_filename for d, _ in items)
    return ", ".join(names), [file_ids[n] for n in names if n in file_ids]


def build_components_register_rows(
    documents: list[tuple[SourceDocument, str]],
    existing_invoice_numbers: set[str],
    file_ids: dict[str, str] | None = None,
) -> tuple[list[ComponentRegisterRow], list[SourceDocument]]:
    """Group filed Components documents by invoice number, but ONLY for
    an ``invoice_number`` (case-insensitive exact match) already present
    in ``existing_invoice_numbers`` -- the live sheet's current Section C
    Invoice # column. Everything else comes back in the second return
    value (``unmatched``) for a caller to report, never silently
    dropped and never auto-inserted as a new row.

    ``documents`` is every filed file's ``(SourceDocument, extracted PDF
    text)`` pair from BOTH real Components folders, already combined by
    the caller -- this function does no I/O, so it's fully testable
    without Drive or PDF dependencies.
    """
    file_ids = file_ids or {}
    existing_lower = {inv.lower(): inv for inv in existing_invoice_numbers}

    groups: dict[str, list[tuple[SourceDocument, str]]] = {}
    unmatched: list[SourceDocument] = []
    for doc, text in documents:
        canonical = existing_lower.get(doc.invoice_number.lower())
        if canonical is None:
            unmatched.append(doc)
            continue
        groups.setdefault(canonical, []).append((doc, text))

    rows: list[ComponentRegisterRow] = []
    for invoice_number, items in sorted(groups.items()):
        deposit_invoice_items = [(d, t) for d, t in items if d.doc_type in _DEPOSIT_INVOICE_DOC_TYPES]
        deposit_payment_items = [(d, t) for d, t in items if d.doc_type in _DEPOSIT_PAYMENT_DOC_TYPES]
        balance_invoice_items = [(d, t) for d, t in items if d.doc_type in _BALANCE_INVOICE_DOC_TYPES]
        balance_payment_items = [(d, t) for d, t in items if d.doc_type in _BALANCE_PAYMENT_DOC_TYPES]
        refund_items = [(d, t) for d, t in items if d.doc_type is DocumentType.REFUND_INVOICE]
        other_items = [(d, t) for d, t in items if d.doc_type is DocumentType.OTHER]

        issues: list[str] = []

        deposit_invoice_link, deposit_invoice_file_ids = _filenames_and_ids(deposit_invoice_items, file_ids)
        deposit_payment_link, deposit_payment_file_ids = _filenames_and_ids(deposit_payment_items, file_ids)
        balance_invoice_link, balance_invoice_file_ids = _filenames_and_ids(balance_invoice_items, file_ids)

        balance_payment_by_slot: dict[int, list[tuple[SourceDocument, str]]] = {}
        for d, t in balance_payment_items:
            slot = balance_installment_number(d.doc_type_raw)
            if slot < 1 or slot > _MAX_BALANCE_PAYMENT_SLOTS:
                issues.append(
                    f"{d.raw_filename}: balance payment installment #{slot} has no "
                    f"column to go in (only {_MAX_BALANCE_PAYMENT_SLOTS} are tracked) -- filed, not linked"
                )
                continue
            balance_payment_by_slot.setdefault(slot, []).append((d, t))

        balance_payment_links: list[str] = []
        balance_payment_file_ids: list[tuple[str, ...]] = []
        for slot in range(1, _MAX_BALANCE_PAYMENT_SLOTS + 1):
            slot_items = balance_payment_by_slot.get(slot, [])
            link, ids = _filenames_and_ids(slot_items, file_ids)
            balance_payment_links.append(link)
            balance_payment_file_ids.append(tuple(ids))

        if refund_items:
            issues.append(
                f"{len(refund_items)} refund document(s) filed against this invoice -- "
                "no register column for a refund, review and adjust by hand"
            )
        if other_items:
            names = ", ".join(sorted(d.raw_filename for d, _ in other_items))
            issues.append(f"could not classify doc type for: {names} -- check by hand")

        invoice_date = deposit_invoice_items[0][0].doc_date if deposit_invoice_items else None
        balance_payment_dates = [d.doc_date for d, _ in balance_payment_items]
        deposit_payment_dates = [d.doc_date for d, _ in deposit_payment_items]
        balance_paid_date = (
            max(balance_payment_dates) if balance_payment_dates
            else max(deposit_payment_dates) if deposit_payment_dates
            else invoice_date
        )

        total_order_amount = None
        for _, text in deposit_invoice_items + balance_invoice_items:
            total_order_amount = extract_total_order_amount(text)
            if total_order_amount is not None:
                break
        if total_order_amount is None and (deposit_invoice_items or balance_invoice_items):
            issues.append(
                "could not extract Total Order $ from any filed invoice for this order "
                "-- existing sheet value left as-is, fill in/check by hand"
            )

        if total_order_amount is not None:
            for _, text in deposit_payment_items + sum(
                (balance_payment_by_slot.get(s, []) for s in range(1, _MAX_BALANCE_PAYMENT_SLOTS + 1)), []
            ):
                payment_amount = extract_payment_amount(text)
                if payment_amount is None:
                    continue
                # A payment is for ONE installment (deposit or a single
                # balance slot), not the whole order -- only flagged if
                # it's bigger than the whole order, which real per-
                # installment rounding/fees never produce, unlike an
                # exact-total mismatch which is expected and not a bug.
                if payment_amount > total_order_amount + _CENT_TOLERANCE:
                    issues.append(
                        f"a payment confirmation states ${payment_amount}, more than this "
                        f"order's own extracted total of ${total_order_amount} -- check by hand"
                    )

        rows.append(
            ComponentRegisterRow(
                invoice_number=invoice_number,
                invoice_date=invoice_date,
                balance_paid_date=balance_paid_date,
                total_order_amount=total_order_amount,
                deposit_invoice_link=deposit_invoice_link,
                deposit_invoice_file_ids=deposit_invoice_file_ids,
                deposit_payment_link=deposit_payment_link,
                deposit_payment_file_ids=deposit_payment_file_ids,
                balance_invoice_link=balance_invoice_link,
                balance_invoice_file_ids=balance_invoice_file_ids,
                balance_payment_links=tuple(balance_payment_links),
                balance_payment_file_ids=tuple(balance_payment_file_ids),
                flagged=bool(issues),
                flag_reason="; ".join(issues),
            )
        )
    return rows, unmatched

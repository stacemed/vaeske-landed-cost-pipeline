"""Parse a QBO "Account QuickReport" CSV and turn it into candidate rows
for 1 TRANSACTIONS Section A.

This is the fully mechanical slice of what docs/QBO_EXTRACTION_SOP.md
still does by hand with a Claude session: Section A is always literally
the QBO ledger (see that SOP's first rule), and classifying its category
by vendor pattern needs no invoice reading at all -- the vendor a wire
went to/from is right there in the QBO description text. Matching each
transaction to its real invoice number (Sections C/D/E, and a clean
Invoice # for Section A) still needs the invoice PDFs and is NOT done
here -- see the SOP for that half.

Real 2024 QBO export confirmed these vendor patterns (validated against
every 2024 Freight/Components/Overhead transaction by hand this
session -- Freight matched 21/21, Components and Overhead matched by
name/vendor text 100% of the time; the mismatches that session found
were amount-level reconciliation gaps, not classification errors):

- "Shenzhen Linkhub" in the wire memo -> Freight / bundling / packaging
- "Shenzhen Minzhi" in the memo, or "Alibaba" as the QBO Name -> Components
- "WEIMIN HUANG" in the memo (a personal wire, not through Shenzhen
  Minzhi) -> Overhead
- Anything else -> unclassified. Never guessed -- a handful of small,
  unrelated vendor charges (Alibaba aside) showed up in the real 2024
  data that don't belong to any of the three categories at all.
"""

from __future__ import annotations

import csv
import io
from datetime import date as date_cls
from datetime import datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict

from ..models.enums import Category


class QboTransaction(BaseModel):
    """One raw row from the QBO Account QuickReport CSV, before any
    classification -- exactly what the report says, nothing inferred.
    """

    model_config = ConfigDict(frozen=True)

    date: date_cls
    name: str
    description: str
    amount: Decimal


class SectionARow(BaseModel):
    """A candidate 1 TRANSACTIONS Section A row built from one
    ``QboTransaction``.

    Deliberately looser than ``InventoryTransaction`` (the model for a
    trusted, final row): ``category`` can be ``None``, and
    ``invoice_number`` is always ``""`` here -- it matches to the real
    vendor invoice/payment confirmation, which needs the invoice PDFs
    read and reconciled (see the module docstring and
    docs/QBO_EXTRACTION_SOP.md Step 2), not a QBO wire reference used as
    a stand-in. ``flagged`` is True whenever something here needs a
    human look before being trusted -- currently just an unclassified
    vendor.
    """

    model_config = ConfigDict(frozen=True)

    category: Category | None
    date: date_cls
    payee: str
    invoice_number: str
    amount: Decimal
    flagged: bool
    flag_reason: str = ""


def parse_qbo_quickreport_csv(text: str) -> list[QboTransaction]:
    """Parse every transaction row out of a QBO "Account QuickReport"
    export.

    The report has a handful of junk rows before the real header
    (title, date range, a blank line), a distribution-account marker
    and a "Beginning Balance" row, the transactions themselves, then
    "Total for <account>" / "TOTAL" footer rows and a trailing
    timestamp line. Rather than counting fixed row offsets (fragile --
    confirmed the exact junk-row count differs by report), this finds
    the real header by its "Transaction date" column and stops the
    moment a row's date column no longer parses as a date, which
    naturally excludes every footer row without needing to recognize
    their exact wording.
    """
    rows = list(csv.reader(io.StringIO(text)))
    header_idx = next(
        (i for i, r in enumerate(rows) if len(r) > 2 and r[2].strip() == "Transaction date"),
        None,
    )
    if header_idx is None:
        raise ValueError('could not find the "Transaction date" header row in this CSV')

    transactions: list[QboTransaction] = []
    for row in rows[header_idx + 1 :]:
        if len(row) < 10:
            continue
        date_str = row[2].strip()
        if not date_str:
            continue
        try:
            parsed_date = datetime.strptime(date_str, "%m/%d/%Y").date()
        except ValueError:
            continue
        amount_str = row[9].strip().replace(",", "").replace("$", "")
        try:
            amount = Decimal(amount_str)
        except InvalidOperation:
            continue
        transactions.append(
            QboTransaction(
                date=parsed_date,
                name=row[5].strip(),
                description=row[6].strip(),
                amount=amount,
            )
        )
    return transactions


def merge_qbo_csv_texts(texts: list[str]) -> list[QboTransaction]:
    """Parse several QBO CSV exports and combine them into one
    deduplicated transaction list.

    For when reports get exported per period and dropped in a Drive
    folder over time -- a later export often re-covers dates an earlier
    one already included. Dedup key is ``(date, amount)``, same as
    ``plan_section_a_sync`` uses against the live sheet -- two genuinely
    different transactions sharing both is rare enough that a missed
    one would be a visible gap, not a silently wrong number.
    """
    seen: set[tuple[date_cls, Decimal]] = set()
    merged: list[QboTransaction] = []
    for text in texts:
        for txn in parse_qbo_quickreport_csv(text):
            key = (txn.date, txn.amount)
            if key in seen:
                continue
            seen.add(key)
            merged.append(txn)
    return merged


def classify_category(name: str, description: str) -> Category | None:
    """Best-effort category from vendor text alone. Returns ``None``
    (never a guess) when nothing matches -- see the module docstring
    for the patterns and how they were validated.
    """
    combined = f"{name} {description}"
    if "Shenzhen Linkhub" in combined:
        return Category.FREIGHT_BUNDLING_PACKAGING
    if "Shenzhen Minzhi" in combined or "Alibaba" in name:
        return Category.COMPONENTS
    if "WEIMIN HUANG" in combined.upper():
        return Category.OVERHEAD
    return None


def clean_payee(name: str, description: str, category: Category | None) -> str:
    """A short, sheet-appropriate payee label in place of the raw wire
    memo text -- matches the vendor labels already used in the real
    workbook (e.g. "FBA Bee" for Shenzhen Linkhub freight wires).
    """
    if category is Category.FREIGHT_BUNDLING_PACKAGING:
        return "FBA Bee"
    if category is Category.OVERHEAD:
        return "Weimin Huang"
    if category is Category.COMPONENTS:
        return "Shanghai Beone (Alibaba)" if "Alibaba" in name else "Shenzhen Minzhi BYJ Trading Co"
    return name or description[:60]


def build_section_a_row(txn: QboTransaction) -> SectionARow:
    category = classify_category(txn.name, txn.description)
    payee = clean_payee(txn.name, txn.description, category)
    flagged = category is None
    flag_reason = (
        "vendor not recognized as Freight/Components/Overhead -- category left blank, needs your input"
        if flagged
        else ""
    )
    return SectionARow(
        category=category,
        date=txn.date,
        payee=payee,
        # Always blank -- the Invoice # column matches to the real
        # vendor invoice/payment confirmation, which needs the invoice
        # PDFs read and reconciled (docs/QBO_EXTRACTION_SOP.md Step 2).
        # This script never guesses at it, not even with a bank
        # reference number as a placeholder.
        invoice_number="",
        amount=txn.amount,
        flagged=flagged,
        flag_reason=flag_reason,
    )


def plan_section_a_sync(
    transactions: list[QboTransaction], existing_rows: list[tuple[date_cls, Decimal]]
) -> tuple[list[SectionARow], list[QboTransaction]]:
    """Split QBO transactions into new rows to write and ones already
    present in the sheet.

    Dedup key is ``(date, amount)`` -- the only stable pair available
    without matching to a real invoice number (see the module
    docstring). Good enough to avoid re-posting the same transaction on
    a re-run; a same-day, same-amount coincidence between two genuinely
    different transactions is rare enough, and would show up as a
    missing row a human would notice, not a wrong number silently
    posted twice.

    Returns ``(new_rows, skipped_as_duplicate)``.
    """
    existing = set(existing_rows)
    new_rows: list[SectionARow] = []
    skipped: list[QboTransaction] = []
    for txn in transactions:
        if (txn.date, txn.amount) in existing:
            skipped.append(txn)
            continue
        new_rows.append(build_section_a_row(txn))
    return new_rows, skipped

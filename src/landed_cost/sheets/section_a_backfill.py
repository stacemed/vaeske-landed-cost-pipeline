"""Reads 1 TRANSACTIONS Section A and matches a register row's payment
back to the one Section A transaction it belongs to.

Shared by every invoice register (Overhead's overhead_sync.py, Freight's
freight_sync.py, and eventually Components') -- the matching rule itself
doesn't depend on which register is calling it, only on which
``Category`` to match against.
"""

from __future__ import annotations

from datetime import date as date_cls
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from ..models.enums import Category
from .client import SheetsClient
from .sync import _parse_cell_amount, _parse_cell_date


class SectionATransaction(BaseModel):
    """One existing 1 TRANSACTIONS Section A row, for backfill matching."""

    model_config = ConfigDict(frozen=True)

    row_number: int
    category: Category | None
    date: date_cls | None
    amount: Decimal | None
    invoice_number: str  # current value; "" if blank


def read_section_a_rows(
    client: SheetsClient,
    spreadsheet_id: str,
    sheet_name: str,
    start_row: int,
    max_rows: int = 1000,
) -> list[SectionATransaction]:
    """Read every Section A row (Category, Date, Invoice #, Amount),
    keeping row numbers so a match can be written back to a single cell.

    Stops at the first row with an empty Date, same boundary rule as
    ``landed_cost.sheets.sync.read_existing_section_a`` -- Section A
    itself (unlike Section E) always has a date on every real row.
    """
    end_row = start_row + max_rows - 1
    values = client.get_values(spreadsheet_id, f"'{sheet_name}'!A{start_row}:E{end_row}")

    rows: list[SectionATransaction] = []
    row_number = start_row
    for row in values:
        parsed_date = _parse_cell_date(row[1]) if len(row) > 1 else None
        if parsed_date is None:
            break
        category_raw = row[0] if len(row) > 0 and row[0] else ""
        try:
            category = Category(category_raw) if category_raw else None
        except ValueError:
            category = None
        invoice_number = str(row[3]).strip() if len(row) > 3 and row[3] else ""
        amount = _parse_cell_amount(row[4]) if len(row) > 4 else None
        rows.append(
            SectionATransaction(
                row_number=row_number,
                category=category,
                date=parsed_date,
                amount=amount,
                invoice_number=invoice_number,
            )
        )
        row_number += 1
    return rows


_AMOUNT_TOLERANCE = Decimal("0.01")


def match_section_a_row(
    paid_date: date_cls,
    amount: Decimal,
    section_a_rows: list[SectionATransaction],
    category: Category,
) -> tuple[int | None, str]:
    """Find the one Section A row this register row's payment belongs to.

    Matches on: same category, amount within a cent (real invoice line
    items sometimes round to a total a cent off the true sum -- confirmed
    2026-09-25 on a real Freight invoice whose own stated total, AND the
    real Section A amount, both landed a cent short of the summed line
    items), same year+month (day may differ -- a wire's "sent" date and
    a document's own date are often a day or two apart), and --
    critically -- an Invoice # that's currently BLANK, so this never
    overwrites a value already filled in (by hand or a previous run).
    Zero or multiple candidates both return no row number: never guess,
    per the project's standing rule.
    """
    candidates = [
        r
        for r in section_a_rows
        if r.category == category
        and r.amount is not None
        and abs(r.amount - amount) <= _AMOUNT_TOLERANCE
        and r.date is not None
        and (r.date.year, r.date.month) == (paid_date.year, paid_date.month)
        and not r.invoice_number
    ]
    if not candidates:
        return None, "no matching Section A transaction found (or it already has an Invoice #)"
    if len(candidates) > 1:
        return None, f"{len(candidates)} matching Section A transactions found -- ambiguous, left blank"
    return candidates[0].row_number, "matched"

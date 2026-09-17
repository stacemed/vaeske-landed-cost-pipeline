"""Wires overhead_register.py's pure grouping/extraction logic to a
SheetsClient: reads what's already in 1 TRANSACTIONS Section E, upserts
register rows (updates an existing invoice number's row in place, inserts
brand-new ones), and backfills Section A's Invoice # column once a
payment is matched.

Section E lives in the same "1 TRANSACTIONS" tab as Section A -- just a
different row range -- so both are addressed with one sheet_name and two
separate start_row values.
"""

from __future__ import annotations

from datetime import date as date_cls
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from ..models.enums import Category
from .client import SheetsClient
from .overhead_register import OverheadRegisterRow
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


def match_section_a_row(
    paid_date: date_cls,
    amount: Decimal,
    section_a_rows: list[SectionATransaction],
    category: Category,
) -> tuple[int | None, str]:
    """Find the one Section A row this register row's payment belongs to.

    Matches on: same category, exact amount, same year+month (day may
    differ -- a wire's "sent" date and a document's own date are often a
    day or two apart), and -- critically -- an Invoice # that's
    currently BLANK, so this never overwrites a value already filled in
    (by hand or a previous run). Zero or multiple candidates both return
    no row number: never guess, per the project's standing rule.
    """
    candidates = [
        r
        for r in section_a_rows
        if r.category == category
        and r.amount == amount
        and r.date is not None
        and (r.date.year, r.date.month) == (paid_date.year, paid_date.month)
        and not r.invoice_number
    ]
    if not candidates:
        return None, "no matching Section A transaction found (or it already has an Invoice #)"
    if len(candidates) > 1:
        return None, f"{len(candidates)} matching Section A transactions found -- ambiguous, left blank"
    return candidates[0].row_number, "matched"


def read_existing_e_register(
    client: SheetsClient,
    spreadsheet_id: str,
    sheet_name: str,
    start_row: int,
    max_rows: int = 1000,
) -> tuple[dict[str, int], int]:
    """Map each already-registered invoice number to its row number.

    Stops at the first row with an empty Invoice # (column A) -- NOT an
    empty date, unlike Section A: real Section E rows for a monthly
    retainer wire routinely have no Invoice date at all (confirmed on
    the live sheet), so a blank date does not mean the row is unused.
    """
    end_row = start_row + max_rows - 1
    values = client.get_values(spreadsheet_id, f"'{sheet_name}'!A{start_row}:A{end_row}")

    existing: dict[str, int] = {}
    row_number = start_row
    for row in values:
        invoice_number = str(row[0]).strip() if row and row[0] else ""
        if not invoice_number:
            break
        existing[invoice_number] = row_number
        row_number += 1
    return existing, row_number


def _row_to_e_values(row: OverheadRegisterRow) -> list[object]:
    return [
        row.invoice_number,
        row.invoice_date.strftime("%m/%d/%Y") if row.invoice_date else "",
        row.paid_date.strftime("%m/%d/%Y") if row.paid_date else "",
        float(row.amount) if row.amount is not None else "",
        row.invoice_link,
        row.payment_link,
    ]


def sync_overhead_register(
    client: SheetsClient,
    spreadsheet_id: str,
    sheet_name: str,
    section_e_start_row: int,
    section_a_start_row: int,
    register_rows: list[OverheadRegisterRow],
    apply: bool,
    sort: bool = False,
) -> tuple[
    list[OverheadRegisterRow],
    list[tuple[int, OverheadRegisterRow]],
    list[tuple[OverheadRegisterRow, int | None, str]],
]:
    """Upsert Section E from freshly-built register rows, then backfill
    Section A's Invoice # for every row with a known amount + paid date.

    A register row is rebuilt from ALL currently-filed documents every
    run (see overhead_register.build_overhead_register_rows), so
    "updating" an existing invoice number is a full, idempotent
    overwrite of that row's cells -- not a diff/patch -- which is what
    correctly picks up e.g. a payment confirmation that gets filed after
    its invoice was already registered on its own.

    ``sort``, only meaningful together with ``apply`` and only when
    there are new rows to insert, sorts the whole Section E range by
    Paid date (ascending) after writing -- same opt-in native-sort
    behavior as Section A's ``sync_section_a``, but by Paid date
    (column C) rather than Invoice date (column B), since Paid date is
    the field this module already treats as the reliable one (it's
    what the Section A backfill matches on, and what falls back to the
    invoice's own date when no payment confirmation is filed). Passes
    ``num_columns=6`` to cover Section E's full A:F range -- Section
    A's 5-column default would leave the Payment Link column behind.

    Returns ``(new_rows, updated_rows, section_a_backfills)`` where
    ``updated_rows`` is ``(row_number, register_row)`` pairs and
    ``section_a_backfills`` is ``(register_row, matched_row_or_None,
    status)`` for every register row, whether or not ``apply`` actually
    ran (so a dry run can preview exactly what would happen).
    """
    existing_map, first_empty_row = read_existing_e_register(
        client, spreadsheet_id, sheet_name, section_e_start_row
    )

    new_rows: list[OverheadRegisterRow] = []
    updated_rows: list[tuple[int, OverheadRegisterRow]] = []
    for row in register_rows:
        if row.invoice_number in existing_map:
            updated_rows.append((existing_map[row.invoice_number], row))
        else:
            new_rows.append(row)

    insert_at = (
        first_empty_row - 1 if first_empty_row > section_e_start_row else section_e_start_row
    )

    # Read (never write) Section A even on a dry run, so the preview
    # shows exactly what --apply would do, including ambiguous/no-match
    # cases -- a caller shouldn't have to apply first to find out.
    section_a_rows = read_section_a_rows(client, spreadsheet_id, sheet_name, section_a_start_row)
    section_a_backfills: list[tuple[OverheadRegisterRow, int | None, str]] = []
    for row in register_rows:
        if row.amount is None or row.paid_date is None:
            section_a_backfills.append((row, None, "skipped -- no amount/paid date to match on"))
            continue
        match_row, status = match_section_a_row(
            row.paid_date, row.amount, section_a_rows, Category.OVERHEAD
        )
        section_a_backfills.append((row, match_row, status))

    if apply:
        for row_number, row in updated_rows:
            client.update_values(
                spreadsheet_id, f"'{sheet_name}'!A{row_number}:F{row_number}", [_row_to_e_values(row)]
            )

        if new_rows:
            sheet_id = client.get_sheet_id(spreadsheet_id, sheet_name)
            client.insert_rows(spreadsheet_id, sheet_id, insert_at, len(new_rows))
            last_row = insert_at + len(new_rows) - 1
            values = [_row_to_e_values(r) for r in new_rows]
            client.update_values(spreadsheet_id, f"'{sheet_name}'!A{insert_at}:F{last_row}", values)

            if sort:
                # Sort the WHOLE section, not just the new rows -- same
                # reasoning as sync_section_a: new rows landed above the
                # old last row (see insert_at above), so the unsorted
                # section spans section_e_start_row through the new end
                # of data regardless of where the new rows themselves sit.
                new_last_row = first_empty_row + len(new_rows) - 1
                client.sort_range(
                    spreadsheet_id, sheet_id, section_e_start_row, new_last_row,
                    sort_column_index=2, num_columns=6,
                )

        for row, match_row, _status in section_a_backfills:
            if match_row is not None:
                client.update_values(
                    spreadsheet_id, f"'{sheet_name}'!D{match_row}", [[row.invoice_number]]
                )

    return new_rows, updated_rows, section_a_backfills

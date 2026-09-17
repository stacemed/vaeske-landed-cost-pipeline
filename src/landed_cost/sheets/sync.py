"""Wires the QBO parsing/planning logic in ``qbo.py`` to a ``SheetsClient``:
finds where 1 TRANSACTIONS Section A's existing data ends, reads it for
dedup, and (only when the caller asks) writes new rows starting there.

Reads with ``valueRenderOption=UNFORMATTED_VALUE`` implicitly expected
from the client -- see ``GoogleSheetsClient.get_values`` -- so dates come
back as Sheets' own serial-number date (days since 1899-12-30) and
amounts as plain numbers, not whatever display format the cell happens
to be formatted with. A test fake can use plain ISO date strings and
numeric strings instead; ``_parse_cell_date``/``_parse_cell_amount``
accept either.
"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from .client import SheetsClient
from .qbo import QboTransaction, SectionARow, plan_section_a_sync

_SHEETS_EPOCH = date_cls(1899, 12, 30)


def _parse_cell_date(value: object) -> date_cls | None:
    if isinstance(value, (int, float)):
        return _SHEETS_EPOCH + timedelta(days=int(value))
    if isinstance(value, str) and value.strip():
        for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
    return None


def _parse_cell_amount(value: object) -> Decimal | None:
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str) and value.strip():
        try:
            return Decimal(value.strip().replace(",", "").replace("$", ""))
        except InvalidOperation:
            return None
    return None


def read_existing_section_a(
    client: SheetsClient,
    spreadsheet_id: str,
    sheet_name: str,
    start_row: int,
    max_rows: int = 1000,
) -> tuple[list[tuple[date_cls, Decimal]], int]:
    """Read Section A's data rows starting at ``start_row`` (the sheet
    row number of the FIRST data row -- one below the header row, e.g.
    6 if the header is on row 5). Stops at the first row with an empty
    Date column (column B), since that's where Section A's data ends in
    every sheet inspected this session (either a blank separator row or
    a TOTAL row follows, neither of which has a date).

    Returns ``(existing (date, amount) pairs for dedup, first empty row
    number -- where new rows should be written)``.
    """
    end_row = start_row + max_rows - 1
    values = client.get_values(spreadsheet_id, f"'{sheet_name}'!A{start_row}:E{end_row}")

    existing: list[tuple[date_cls, Decimal]] = []
    row_number = start_row
    for row in values:
        parsed_date = _parse_cell_date(row[1]) if len(row) > 1 else None
        if parsed_date is None:
            break
        amount = _parse_cell_amount(row[4]) if len(row) > 4 else None
        if amount is not None:
            existing.append((parsed_date, amount))
        row_number += 1

    return existing, row_number


def _row_to_values(row: SectionARow) -> list[object]:
    return [
        row.category.value if row.category is not None else "",
        row.date.strftime("%m/%d/%Y"),
        row.payee,
        row.invoice_number,
        float(row.amount),
    ]


def sync_section_a(
    client: SheetsClient,
    spreadsheet_id: str,
    sheet_name: str,
    start_row: int,
    transactions: list[QboTransaction],
    apply: bool,
) -> tuple[list[SectionARow], list[QboTransaction], int]:
    """Plan (and, only if ``apply``, write) new Section A rows for every
    QBO transaction not already present.

    Returns ``(new_rows, skipped_as_duplicate, first_write_row)`` --
    the caller (the CLI) decides how to report this; nothing is written
    unless ``apply`` is True.
    """
    existing, first_empty_row = read_existing_section_a(client, spreadsheet_id, sheet_name, start_row)
    new_rows, skipped = plan_section_a_sync(transactions, existing)

    if apply and new_rows:
        last_row = first_empty_row + len(new_rows) - 1
        values = [_row_to_values(row) for row in new_rows]
        client.update_values(spreadsheet_id, f"'{sheet_name}'!A{first_empty_row}:E{last_row}", values)

    return new_rows, skipped, first_empty_row

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
    sort: bool = False,
) -> tuple[list[SectionARow], list[QboTransaction], int]:
    """Plan (and, only if ``apply``, write) new Section A rows for every
    QBO transaction not already present.

    ``sort``, only meaningful together with ``apply``, sorts the whole
    Section A range by Date (ascending) after writing -- opt-in, not
    automatic, since it's a live financial ledger and reordering it is
    a real choice, not a side effect a caller should get for free. Uses
    a real Sheets range sort (SheetsClient.sort_range), not a
    read-sorted-values-then-rewrite, so per-row formatting moves with
    its data instead of staying stuck at the old row position.

    Returns ``(new_rows, skipped_as_duplicate, first_write_row)`` --
    the caller (the CLI) decides how to report this; nothing is written
    unless ``apply`` is True.
    """
    existing, first_empty_row = read_existing_section_a(client, spreadsheet_id, sheet_name, start_row)
    new_rows, skipped = plan_section_a_sync(transactions, existing)

    # Insert AT the last existing data row (not one past it), so the
    # old last row gets pushed down rather than the new rows landing
    # after everything. Deliberate, not off-by-one: Sheets only
    # auto-extends an existing formula's range (a Section A TOTAL's
    # SUM, or Section B's SUMIF/COUNTIF) when an insertion falls at or
    # within the range it already covers -- inserting one row past the
    # end never extends it, which is exactly the gap a real run hit (a
    # SUM(E5:E50) stayed frozen at row 50 after new rows landed at
    # 51-52). Inserting at row 50 itself keeps every such formula
    # correct with zero manual edits, at the cost of new rows landing
    # just above the previous last row instead of strictly at the
    # bottom -- fine, since nothing here depends on row order (the
    # dedup check does a full re-read every run regardless of
    # position). Computed even on a dry run so the reported row number
    # matches what --apply will actually do.
    insert_at = first_empty_row - 1 if first_empty_row > start_row else start_row

    if apply and new_rows:
        # Insert first, THEN write -- never overwrite a fixed range
        # directly. Section A shares its sheet with other sections
        # below it, separated by only a couple of blank buffer rows;
        # a plain overwrite is safe only by luck (only as many new
        # rows as there happen to be buffer rows). Inserting shifts
        # everything below down first, so new rows are always
        # genuinely blank no matter how many there are -- see
        # SheetsClient.insert_rows.
        sheet_id = client.get_sheet_id(spreadsheet_id, sheet_name)
        client.insert_rows(spreadsheet_id, sheet_id, insert_at, len(new_rows))
        last_row = insert_at + len(new_rows) - 1
        values = [_row_to_values(row) for row in new_rows]
        client.update_values(spreadsheet_id, f"'{sheet_name}'!A{insert_at}:E{last_row}", values)

        if sort:
            # Sort the WHOLE section, not just the new rows -- new
            # rows landed above the old last row (see insert_at above),
            # so the unsorted section spans start_row through the new
            # end of data regardless of where the new rows themselves
            # sit.
            new_last_row = first_empty_row + len(new_rows) - 1
            client.sort_range(
                spreadsheet_id, sheet_id, start_row, new_last_row, sort_column_index=1
            )

    return new_rows, skipped, insert_at

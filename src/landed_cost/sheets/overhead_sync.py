"""Wires overhead_register.py's pure grouping/extraction logic to a
SheetsClient: reads what's already in 1 TRANSACTIONS Section E, upserts
register rows (updates an existing invoice number's row in place, inserts
brand-new ones), and backfills Section A's Invoice # column once a
payment is matched.

Section E lives in the same "1 TRANSACTIONS" tab as Section A -- just a
different row range -- so both are addressed with one sheet_name and two
separate start_row values.

Column G holds "Flag Reason" -- free space past Section E's original
A:F columns, created (and its header written) the first time this
runs. Column A's own Invoice # cell, and Section A's own Invoice # cell
for a matched row, are written as ``=HYPERLINK(...)`` formulas cross-
linking the two -- see ``sync_overhead_register``'s docstring, and
freight_sync.py's (the same pattern, minus combined-wire grouping,
since Overhead never combines invoices onto one Section A row) for why
one direction is always safe to compute once and the other is
recomputed and rewritten on every single apply run.
"""

from __future__ import annotations

from ..models.enums import Category
from .client import SheetsClient
from .overhead_register import OverheadRegisterRow
from .section_a_backfill import SectionATransaction, match_section_a_row, read_section_a_rows, review_reason

__all__ = [
    "SectionATransaction",
    "match_section_a_row",
    "read_existing_e_register",
    "read_section_a_rows",
    "sync_overhead_register",
]


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


def _row_to_e_values(
    row: OverheadRegisterRow, sheet_id: int, section_a_match_row: int | None, flag_reason: str
) -> list[object]:
    # Safe to compute once, here -- Section A rows never shift position
    # once matched (see freight_sync.py's _row_to_d_values docstring).
    invoice_number_cell = (
        f'=HYPERLINK("#gid={sheet_id}&range=D{section_a_match_row}", "{row.invoice_number}")'
        if section_a_match_row is not None
        else row.invoice_number
    )
    return [
        invoice_number_cell,
        row.invoice_date.strftime("%m/%d/%Y") if row.invoice_date else "",
        row.paid_date.strftime("%m/%d/%Y") if row.paid_date else "",
        float(row.amount) if row.amount is not None else "",
        row.invoice_link,
        row.payment_link,
        flag_reason,
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
    ``num_columns=7`` to cover Section E's full A:G range (see below) --
    Section A's 5-column default would leave the Payment Link/Flag
    Reason columns behind.

    Every apply run also cross-links each matched pair of cells and
    marks rows needing review -- same mechanism as
    ``freight_sync.sync_freight_register`` (see its docstring for the
    full reasoning, including why the Section A -> register link is
    recomputed and rewritten every run rather than only for brand-new
    matches), minus combined-wire grouping since an Overhead payment
    never covers more than one invoice.

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

    match_by_invoice = {row.invoice_number: (match_row, status) for row, match_row, status in section_a_backfills}
    reason_by_invoice = {
        row.invoice_number: review_reason(
            row.flagged, row.flag_reason, match_by_invoice[row.invoice_number][1],
            row.invoice_number, section_a_rows,
        )
        for row in register_rows
    }

    if apply:
        sheet_id = client.get_sheet_id(spreadsheet_id, sheet_name)

        for row_number, row in updated_rows:
            match_row, _status = match_by_invoice[row.invoice_number]
            client.update_values(
                spreadsheet_id, f"'{sheet_name}'!A{row_number}:G{row_number}",
                [_row_to_e_values(row, sheet_id, match_row, reason_by_invoice[row.invoice_number])],
            )

        if new_rows:
            client.insert_rows(spreadsheet_id, sheet_id, insert_at, len(new_rows))
            last_row = insert_at + len(new_rows) - 1
            values = [
                _row_to_e_values(
                    r, sheet_id, match_by_invoice[r.invoice_number][0], reason_by_invoice[r.invoice_number]
                )
                for r in new_rows
            ]
            client.update_values(spreadsheet_id, f"'{sheet_name}'!A{insert_at}:G{last_row}", values)

            if sort:
                # Sort the WHOLE section, not just the new rows -- same
                # reasoning as sync_section_a: new rows landed above the
                # old last row (see insert_at above), so the unsorted
                # section spans section_e_start_row through the new end
                # of data regardless of where the new rows themselves sit.
                new_last_row = first_empty_row + len(new_rows) - 1
                client.sort_range(
                    spreadsheet_id, sheet_id, section_e_start_row, new_last_row,
                    sort_column_index=2, num_columns=7,
                )

        client.update_values(
            spreadsheet_id, f"'{sheet_name}'!G{section_e_start_row - 1}", [["Flag Reason"]]
        )

        # Re-read Section E's CURRENT row positions -- see
        # freight_sync.sync_freight_register's docstring for why every
        # Section A -> register link (not just new matches) is
        # recomputed and rewritten from this fresh read on every run.
        final_register_map, _ = read_existing_e_register(
            client, spreadsheet_id, sheet_name, section_e_start_row
        )

        # Category-filtered -- see freight_sync.py's equivalent comment
        # for why: Section A holds Freight/Components rows too, sharing
        # the same Invoice # column, and without this filter an Overhead
        # run would "refresh" (downgrading back to plain text) another
        # category's already-correct link.
        linked_match_rows: dict[int, str] = {
            r.row_number: r.invoice_number
            for r in section_a_rows
            if r.invoice_number and r.category == Category.OVERHEAD
        }
        for row, match_row, _status in section_a_backfills:
            if match_row is not None:
                linked_match_rows[match_row] = row.invoice_number

        for match_row, invoice_number in linked_match_rows.items():
            target_row = final_register_map.get(invoice_number)
            value = (
                f'=HYPERLINK("#gid={sheet_id}&range=A{target_row}", "{invoice_number}")'
                if target_row is not None else invoice_number
            )
            client.update_values(spreadsheet_id, f"'{sheet_name}'!D{match_row}", [[value]])

        row_flags = [
            (final_register_map[row.invoice_number], bool(reason_by_invoice[row.invoice_number]))
            for row in register_rows
            if row.invoice_number in final_register_map
        ]
        client.format_row_flags(spreadsheet_id, sheet_id, row_flags, num_columns=7)

    return new_rows, updated_rows, section_a_backfills

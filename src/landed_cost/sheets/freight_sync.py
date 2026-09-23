"""Wires freight_register.py's pure grouping/extraction logic to a
SheetsClient: reads what's already in 1 TRANSACTIONS Section D, upserts
register rows (updates an existing invoice number's row in place, inserts
brand-new ones), and backfills Section A's Invoice # column once a
payment is matched.

Section D lives in the same "1 TRANSACTIONS" tab as Section A -- just a
different row range -- so both are addressed with one sheet_name and two
separate start_row values.

Every real Section D row uses only the "Deposit invoice"/"Deposit
payment" columns (F/G) -- "Balance invoice"/"Balance payment 1" (H/I) are
always left blank, since Freight-Bundling invoices never actually use
deposit/balance staged doc types in practice (see DocumentType's own
docstring, and freight_register.py's module docstring for the real-data
confirmation).
"""

from __future__ import annotations

from decimal import Decimal

from ..models.enums import Category
from .client import SheetsClient
from .freight_register import FreightRegisterRow
from .section_a_backfill import SectionATransaction, match_section_a_row, read_section_a_rows

__all__ = [
    "SectionATransaction",
    "match_section_a_row",
    "read_existing_d_register",
    "read_section_a_rows",
    "sync_freight_register",
]


def read_existing_d_register(
    client: SheetsClient,
    spreadsheet_id: str,
    sheet_name: str,
    start_row: int,
    max_rows: int = 1000,
) -> tuple[dict[str, int], int]:
    """Map each already-registered invoice number to its row number.

    Stops at the first row with an empty Invoice # (column A) -- same
    boundary rule as Section E's read_existing_e_register.
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


def _row_to_d_values(row: FreightRegisterRow) -> list[object]:
    return [
        row.invoice_number,
        row.invoice_date.strftime("%m/%d/%Y") if row.invoice_date else "",
        row.paid_date.strftime("%m/%d/%Y") if row.paid_date else "",
        float(row.freight_amount) if row.freight_amount is not None else "",
        float(row.bundling_amount) if row.bundling_amount is not None else "",
        row.invoice_link,
        row.payment_link,
        "",  # Balance invoice -- always blank, see module docstring
        "",  # Balance payment 1 -- always blank, see module docstring
        row.prep_sheet_label,
        row.prep_sheet_link,
    ]


def sync_freight_register(
    client: SheetsClient,
    spreadsheet_id: str,
    sheet_name: str,
    section_d_start_row: int,
    section_a_start_row: int,
    register_rows: list[FreightRegisterRow],
    apply: bool,
    sort: bool = False,
) -> tuple[
    list[FreightRegisterRow],
    list[tuple[int, FreightRegisterRow]],
    list[tuple[FreightRegisterRow, int | None, str]],
]:
    """Upsert Section D from freshly-built register rows, then backfill
    Section A's Invoice # for every row with a known Freight+Bundling
    total and paid date.

    A register row is rebuilt from ALL currently-filed documents every
    run (see freight_register.build_freight_register_rows), so
    "updating" an existing invoice number is a full, idempotent
    overwrite of that row's cells -- not a diff/patch.

    The Section A backfill matches on Freight $ + Bundling $ combined
    (Section A's own "Freight / bundling / packaging" amount is always
    the full wire total, confirmed against real data: a $990.04 Section A
    row matches a $876.88 Freight + $113.16 Bundling invoice exactly).

    When a row's own total doesn't match anything by itself, it also
    tries the COMBINED total of every register row sharing its exact
    Paid date -- confirmed against real data that several Freight
    invoices routinely get paid together in one wire (both region-
    suffixed invoices sharing a base number, e.g. $2,321.58 +
    $6,517.08 = $8,838.66 matching one real Section A row exactly; and
    entirely separate invoice numbers that just happened to be paid
    together). Matches only on an exact combined sum (never guesses
    which subset of same-day invoices belong together), and writes ONE
    comma-joined Invoice # value listing every contributing invoice, not
    a last-write-wins overwrite from separate single-cell writes.

    ``sort``, only meaningful together with ``apply`` and only when there
    are new rows to insert, sorts the whole Section D range by Paid date
    (ascending) after writing -- same opt-in native-sort behavior as
    Section A's/Section E's sync functions. Passes ``num_columns=11`` to
    cover Section D's full A:K range.

    Returns ``(new_rows, updated_rows, section_a_backfills)`` where
    ``updated_rows`` is ``(row_number, register_row)`` pairs and
    ``section_a_backfills`` is ``(register_row, matched_row_or_None,
    status)`` for every register row, whether or not ``apply`` actually
    ran (so a dry run can preview exactly what would happen).
    """
    existing_map, first_empty_row = read_existing_d_register(
        client, spreadsheet_id, sheet_name, section_d_start_row
    )

    new_rows: list[FreightRegisterRow] = []
    updated_rows: list[tuple[int, FreightRegisterRow]] = []
    for row in register_rows:
        if row.invoice_number in existing_map:
            updated_rows.append((existing_map[row.invoice_number], row))
        else:
            new_rows.append(row)

    insert_at = (
        first_empty_row - 1 if first_empty_row > section_d_start_row else section_d_start_row
    )

    # Read (never write) Section A even on a dry run, so the preview
    # shows exactly what --apply would do, including ambiguous/no-match
    # cases -- a caller shouldn't have to apply first to find out.
    section_a_rows = read_section_a_rows(client, spreadsheet_id, sheet_name, section_a_start_row)

    # Rows with a known total and Paid date, grouped by that date -- the
    # candidate pool for combined-wire matching below.
    matchable_rows = [
        row for row in register_rows
        if row.freight_amount is not None and row.bundling_amount is not None and row.paid_date is not None
    ]
    rows_by_paid_date: dict[object, list[FreightRegisterRow]] = {}
    for row in matchable_rows:
        rows_by_paid_date.setdefault(row.paid_date, []).append(row)

    section_a_backfills: list[tuple[FreightRegisterRow, int | None, str]] = []
    for row in register_rows:
        if row.freight_amount is None or row.bundling_amount is None or row.paid_date is None:
            section_a_backfills.append((row, None, "skipped -- no amount/paid date to match on"))
            continue

        own_amount = row.freight_amount + row.bundling_amount
        match_row, status = match_section_a_row(
            row.paid_date, own_amount, section_a_rows, Category.FREIGHT_BUNDLING_PACKAGING
        )
        if match_row is None:
            siblings = rows_by_paid_date.get(row.paid_date, [])
            if len(siblings) > 1:
                combined_amount = sum(
                    (r.freight_amount + r.bundling_amount for r in siblings), Decimal("0")
                )
                combined_match_row, combined_status = match_section_a_row(
                    row.paid_date, combined_amount, section_a_rows, Category.FREIGHT_BUNDLING_PACKAGING
                )
                if combined_match_row is not None:
                    match_row = combined_match_row
                    status = f"matched as part of a combined wire with {len(siblings)} invoices total"
        section_a_backfills.append((row, match_row, status))

    if apply:
        for row_number, row in updated_rows:
            client.update_values(
                spreadsheet_id, f"'{sheet_name}'!A{row_number}:K{row_number}", [_row_to_d_values(row)]
            )

        if new_rows:
            sheet_id = client.get_sheet_id(spreadsheet_id, sheet_name)
            client.insert_rows(spreadsheet_id, sheet_id, insert_at, len(new_rows))
            last_row = insert_at + len(new_rows) - 1
            values = [_row_to_d_values(r) for r in new_rows]
            client.update_values(spreadsheet_id, f"'{sheet_name}'!A{insert_at}:K{last_row}", values)

            if sort:
                # Sort the WHOLE section, not just the new rows -- same
                # reasoning as sync_section_a/sync_overhead_register.
                new_last_row = first_empty_row + len(new_rows) - 1
                client.sort_range(
                    spreadsheet_id, sheet_id, section_d_start_row, new_last_row,
                    sort_column_index=2, num_columns=11,
                )

        # Grouped by match_row -- a combined-wire match sends several
        # register rows to the same Section A row, and each needs to
        # land in ONE write with every contributing invoice number, not
        # separate single-cell writes overwriting each other.
        invoice_numbers_by_match_row: dict[int, list[str]] = {}
        for row, match_row, _status in section_a_backfills:
            if match_row is not None:
                invoice_numbers_by_match_row.setdefault(match_row, []).append(row.invoice_number)
        for match_row, invoice_numbers in invoice_numbers_by_match_row.items():
            client.update_values(
                spreadsheet_id, f"'{sheet_name}'!D{match_row}", [[", ".join(sorted(invoice_numbers))]]
            )

    return new_rows, updated_rows, section_a_backfills

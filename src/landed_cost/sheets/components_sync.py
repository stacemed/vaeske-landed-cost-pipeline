"""Wires components_register.py's pure grouping/extraction logic to a
SheetsClient: reads what's already in 1 TRANSACTIONS Section C, updates
an EXISTING invoice number's row in place, and backfills Section A's
Invoice # column once a payment is matched.

Unlike Freight/Overhead, this never inserts a new row -- per the real
messiness confirmed in components_register.py's own docstring (invoice
numbers that don't exactly match the filename, shared deposits funding
more than one final order), the project owner's own choice was to only
ever verify/supplement a register row a human already created, never to
guess a new one into existence. A filed document whose invoice number
doesn't exactly match an existing row is the caller's (the CLI script's)
responsibility to report -- this module only ever sees documents already
grouped under a matched existing invoice number (see
``components_register.build_components_register_rows``'s own
``existing_invoice_numbers`` parameter).

Section C lives in the same "1 TRANSACTIONS" tab as Section A -- just a
different row range -- so both are addressed with one sheet_name and two
separate start_row values.

Column M holds "Flag Reason" -- free space past Section C's original
A:L columns, created (and its header written) the first time this runs.
Column A's own Invoice # cell, and Section A's own Invoice # cell for a
matched row, are written as ``=HYPERLINK(...)`` formulas cross-linking
the two -- see freight_sync.py's docstring for why one direction is
always safe to compute once and the other is recomputed and rewritten
on every single apply run (the same reasoning applies here).

"Total Order $" (column D) is only ever overwritten when this run's own
extraction succeeded -- extraction failing (flagged, not blocked; see
components_register.py) leaves the sheet's existing value untouched
rather than blanking it. "Invoice Adjustments" (column E) is NEVER
computed by this module; it is always read back from the sheet and
written out unchanged, and the written "Total Order $" always adds that
preserved adjustments figure to the freshly extracted base order
amount -- matching the column's own header, "incl. exchng fees".
"""

from __future__ import annotations

from decimal import Decimal

from ..models.enums import Category
from .client import SheetsClient
from .components_register import ComponentRegisterRow
from .section_a_backfill import SectionATransaction, match_section_a_row, read_section_a_rows, review_reason
from .sync import _parse_cell_amount

__all__ = [
    "SectionATransaction",
    "match_section_a_row",
    "read_existing_c_register",
    "read_section_a_rows",
    "sync_components_register",
]

_NUM_COLUMNS = 13  # A:M, including the Flag Reason column this module adds


def read_existing_c_register(
    client: SheetsClient,
    spreadsheet_id: str,
    sheet_name: str,
    start_row: int,
    max_rows: int = 1000,
) -> dict[str, tuple[int, Decimal | None, Decimal | None]]:
    """Map each already-registered invoice number to its row number and
    its CURRENT "Total Order $"/"Invoice Adjustments" values -- needed
    so a caller can preserve Invoice Adjustments untouched, and Total
    Order $ when this run's own extraction fails, rather than blanking
    a real number. Stops at the first row with an empty Invoice #
    (column A), same boundary rule as Section D/E.
    """
    end_row = start_row + max_rows - 1
    values = client.get_values(spreadsheet_id, f"'{sheet_name}'!A{start_row}:E{end_row}")

    existing: dict[str, tuple[int, Decimal | None, Decimal | None]] = {}
    row_number = start_row
    for row in values:
        invoice_number = str(row[0]).strip() if row and row[0] else ""
        if not invoice_number:
            break
        total_order_amount = _parse_cell_amount(row[3]) if len(row) > 3 else None
        invoice_adjustments = _parse_cell_amount(row[4]) if len(row) > 4 else None
        existing[invoice_number] = (row_number, total_order_amount, invoice_adjustments)
        row_number += 1
    return existing


def _row_to_c_values(
    row: ComponentRegisterRow,
    sheet_id: int,
    section_a_match_row: int | None,
    total_order_amount: Decimal | None,
    invoice_adjustments: Decimal | None,
    flag_reason: str,
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
        row.balance_paid_date.strftime("%m/%d/%Y") if row.balance_paid_date else "",
        float(total_order_amount) if total_order_amount is not None else "",
        float(invoice_adjustments) if invoice_adjustments is not None else "",
        row.deposit_invoice_link,
        row.deposit_payment_link,
        row.balance_invoice_link,
        row.balance_payment_links[0],
        row.balance_payment_links[1],
        row.balance_payment_links[2],
        row.balance_payment_links[3],
        flag_reason,
    ]


def sync_components_register(
    client: SheetsClient,
    spreadsheet_id: str,
    sheet_name: str,
    section_c_start_row: int,
    section_a_start_row: int,
    register_rows: list[ComponentRegisterRow],
    apply: bool,
) -> tuple[
    list[tuple[int, ComponentRegisterRow]],
    list[tuple[ComponentRegisterRow, int | None, str]],
]:
    """Verify/update EXISTING Section C rows from freshly-built register
    rows, then backfill Section A's Invoice # for every row with a known
    Total Order $ (extracted or preserved) and Balance paid date.

    ``register_rows`` must only ever contain rows whose invoice number
    already has a row in the live sheet -- see
    ``components_register.build_components_register_rows``'s own
    ``existing_invoice_numbers`` parameter, which is what makes that
    guarantee true. A row whose invoice number isn't found here anyway
    (shouldn't happen given that contract, but checked rather than
    assumed) is skipped with no write and no Section A backfill attempt,
    not guessed into a new row.

    Returns ``(updated_rows, section_a_backfills)`` -- ``updated_rows``
    is ``(row_number, register_row)`` pairs and ``section_a_backfills``
    is ``(register_row, matched_row_or_None, status)`` for every row
    found in the existing register, whether or not ``apply`` actually
    ran (so a dry run can preview exactly what would happen).
    """
    existing = read_existing_c_register(client, spreadsheet_id, sheet_name, section_c_start_row)

    found_rows = [row for row in register_rows if row.invoice_number in existing]
    updated_rows = [(existing[row.invoice_number][0], row) for row in found_rows]

    # Read (never write) Section A even on a dry run, so the preview
    # shows exactly what --apply would do -- a caller shouldn't have to
    # apply first to find out.
    section_a_rows = read_section_a_rows(client, spreadsheet_id, sheet_name, section_a_start_row)

    section_a_backfills: list[tuple[ComponentRegisterRow, int | None, str]] = []
    total_order_amount_by_invoice: dict[str, Decimal | None] = {}
    for row in found_rows:
        _row_number, existing_total, existing_adjustments = existing[row.invoice_number]
        adjustments = existing_adjustments if existing_adjustments is not None else Decimal("0")
        total_order_amount = (
            row.total_order_amount + adjustments if row.total_order_amount is not None else existing_total
        )
        total_order_amount_by_invoice[row.invoice_number] = total_order_amount

        if total_order_amount is None or row.balance_paid_date is None:
            section_a_backfills.append((row, None, "skipped -- no amount/paid date to match on"))
            continue
        match_row, status = match_section_a_row(
            row.balance_paid_date, total_order_amount, section_a_rows, Category.COMPONENTS
        )
        section_a_backfills.append((row, match_row, status))

    match_by_invoice = {row.invoice_number: (match_row, status) for row, match_row, status in section_a_backfills}
    reason_by_invoice = {
        row.invoice_number: review_reason(
            row.flagged, row.flag_reason, match_by_invoice[row.invoice_number][1],
            row.invoice_number, section_a_rows,
        )
        for row in found_rows
    }

    # Relabels the technically-correct-but-alarming "no matching..."
    # status for an invoice already linked by an earlier run -- see
    # freight_sync.py's equivalent for the full real-world story.
    section_a_backfills = [
        (
            row,
            match_row,
            "already linked in Section A from a previous run -- nothing to do"
            if match_row is None and not status.startswith("skipped") and not reason_by_invoice[row.invoice_number]
            else status,
        )
        for row, match_row, status in section_a_backfills
    ]

    # match_by_invoice only finds matches among Section A rows a fresh
    # match_section_a_row pass can still see -- see freight_sync.py's
    # equivalent comment for the full reasoning. Falls back to Section
    # A's CURRENT state whenever this run found nothing new.
    already_linked_row_by_invoice: dict[str, int] = {
        r.invoice_number.strip(): r.row_number
        for r in section_a_rows
        if r.invoice_number and r.category == Category.COMPONENTS
    }
    section_a_link_row_by_invoice = {
        row.invoice_number: (
            match_by_invoice[row.invoice_number][0]
            if match_by_invoice[row.invoice_number][0] is not None
            else already_linked_row_by_invoice.get(row.invoice_number)
        )
        for row in found_rows
    }

    if apply:
        sheet_id = client.get_sheet_id(spreadsheet_id, sheet_name)

        for row_number, row in updated_rows:
            _row_number, _existing_total, existing_adjustments = existing[row.invoice_number]
            client.update_values(
                spreadsheet_id, f"'{sheet_name}'!A{row_number}:M{row_number}",
                [_row_to_c_values(
                    row, sheet_id, section_a_link_row_by_invoice[row.invoice_number],
                    total_order_amount_by_invoice[row.invoice_number], existing_adjustments,
                    reason_by_invoice[row.invoice_number],
                )],
            )

        client.update_values(
            spreadsheet_id, f"'{sheet_name}'!M{section_c_start_row - 1}", [["Flag Reason"]]
        )

        # Category-filtered -- see freight_sync.py's equivalent comment
        # for why: Section A holds Freight/Overhead rows too, sharing
        # the same Invoice # column, and without this filter a
        # Components run would "refresh" (downgrading back to plain
        # text) another category's already-correct link.
        linked_match_rows: dict[int, str] = {
            r.row_number: r.invoice_number
            for r in section_a_rows
            if r.invoice_number and r.category == Category.COMPONENTS
        }
        for row, match_row, _status in section_a_backfills:
            if match_row is not None:
                linked_match_rows[match_row] = row.invoice_number

        for match_row, invoice_number in linked_match_rows.items():
            target_row = existing.get(invoice_number, (None, None, None))[0]
            value = (
                f'=HYPERLINK("#gid={sheet_id}&range=A{target_row}", "{invoice_number}")'
                if target_row is not None else invoice_number
            )
            client.update_values(spreadsheet_id, f"'{sheet_name}'!D{match_row}", [[value]])

        row_flags = [
            (existing[row.invoice_number][0], bool(reason_by_invoice[row.invoice_number]))
            for row in found_rows
        ]
        client.format_row_flags(spreadsheet_id, sheet_id, row_flags, num_columns=_NUM_COLUMNS)

        # Real Drive file smart chips for Deposit invoice (F, index 5),
        # Deposit payment (G, index 6), Balance invoice (H, index 7),
        # and Balance payment 1-4 (I/J/K/L, index 8-11) -- see
        # freight_sync.py's equivalent for why this is a separate pass
        # after the bulk row write, and why a link with no known file
        # id is simply skipped rather than blanked.
        chip_cells = [
            (existing[row.invoice_number][0], column_index, file_ids)
            for row in found_rows
            for column_index, file_ids in (
                (5, row.deposit_invoice_file_ids),
                (6, row.deposit_payment_file_ids),
                (7, row.balance_invoice_file_ids),
                (8, list(row.balance_payment_file_ids[0])),
                (9, list(row.balance_payment_file_ids[1])),
                (10, list(row.balance_payment_file_ids[2])),
                (11, list(row.balance_payment_file_ids[3])),
            )
            if file_ids
        ]
        client.write_file_chip_cells(spreadsheet_id, sheet_id, chip_cells)

    return updated_rows, section_a_backfills

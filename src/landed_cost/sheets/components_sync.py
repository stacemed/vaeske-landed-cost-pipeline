"""Wires components_register.py's pure grouping/extraction logic to a
SheetsClient: reads what's already in 1 TRANSACTIONS Section C, upserts
register rows (updates an existing invoice number's row in place, inserts
genuinely new ones), and backfills Section A's Invoice # column once a
payment is matched.

Unlike the original v1 scope, this now DOES insert a new row -- but only
for an invoice number ``build_components_register_rows`` has already
determined is genuinely new (no existing row resembles it at all; see
that function's and ``_resembles_an_existing_invoice_number``'s
docstrings for the real split/drift ambiguity this rules out first). A
filed document whose invoice number merely resembles, without exactly
matching, an existing row never reaches this module at all -- it's the
caller's (the CLI script's) responsibility to report that one as
unmatched, same as before.

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
) -> tuple[dict[str, tuple[int, Decimal | None, Decimal | None]], int]:
    """Map each already-registered invoice number to its row number and
    its CURRENT "Total Order $"/"Invoice Adjustments" values -- needed
    so a caller can preserve Invoice Adjustments untouched, and Total
    Order $ when this run's own extraction fails, rather than blanking
    a real number. Also returns the first EMPTY row right after the
    last existing one -- where a brand-new row gets inserted. Stops at
    the first row with an empty Invoice # (column A), same boundary
    rule as Section D/E.
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
    return existing, row_number


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
    list[ComponentRegisterRow],
    list[tuple[int, ComponentRegisterRow]],
    list[tuple[ComponentRegisterRow, int | None, str]],
]:
    """Upsert Section C from freshly-built register rows (updates an
    existing invoice number's row in place, inserts a genuinely new one),
    then backfill Section A's Invoice # for every row with a known Total
    Order $ (extracted or preserved) and Balance paid date.

    ``register_rows`` is split into ``new_rows``/``updated_rows`` purely
    by whether its invoice number already has a row in the live sheet --
    the harder question of whether an invoice number is safe to treat as
    "genuinely new" at all (rather than an ambiguous near-miss of an
    existing row, never auto-inserted) is already resolved by the
    caller's own ``components_register.build_components_register_rows``
    call; see that function's docstring.

    Returns ``(new_rows, updated_rows, section_a_backfills)`` --
    ``updated_rows`` is ``(row_number, register_row)`` pairs and
    ``section_a_backfills`` is ``(register_row, matched_row_or_None,
    status)`` for every row in ``register_rows``, whether or not
    ``apply`` actually ran (so a dry run can preview exactly what would
    happen).
    """
    existing, first_empty_row = read_existing_c_register(
        client, spreadsheet_id, sheet_name, section_c_start_row
    )

    new_rows: list[ComponentRegisterRow] = []
    updated_rows: list[tuple[int, ComponentRegisterRow]] = []
    for row in register_rows:
        if row.invoice_number in existing:
            updated_rows.append((existing[row.invoice_number][0], row))
        else:
            new_rows.append(row)

    # Unlike freight_sync.py/overhead_sync.py's equivalent (which backs
    # up one row and relies on an opt-in --sort pass to fix the
    # resulting visual reorder), Components has no --sort -- so this
    # inserts directly at the first empty row, after every existing row,
    # with nothing already in the sheet shifting out of place.
    insert_at = first_empty_row

    # Read (never write) Section A even on a dry run, so the preview
    # shows exactly what --apply would do -- a caller shouldn't have to
    # apply first to find out.
    section_a_rows = read_section_a_rows(client, spreadsheet_id, sheet_name, section_a_start_row)

    section_a_backfills: list[tuple[ComponentRegisterRow, int | None, str]] = []
    total_order_amount_by_invoice: dict[str, Decimal | None] = {}
    for row in register_rows:
        if row.invoice_number in existing:
            _row_number, existing_total, existing_adjustments = existing[row.invoice_number]
            adjustments = existing_adjustments if existing_adjustments is not None else Decimal("0")
            total_order_amount = (
                row.total_order_amount + adjustments if row.total_order_amount is not None else existing_total
            )
        else:
            # Brand-new row -- no existing "Invoice Adjustments" to add
            # back in yet (nothing filed/curated for it until now).
            total_order_amount = row.total_order_amount
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
        for row in register_rows
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
        for row in register_rows
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

        if new_rows:
            client.insert_rows(spreadsheet_id, sheet_id, insert_at, len(new_rows))
            last_row = insert_at + len(new_rows) - 1
            values = [
                _row_to_c_values(
                    row, sheet_id, section_a_link_row_by_invoice[row.invoice_number],
                    total_order_amount_by_invoice[row.invoice_number],
                    None,  # brand new -- no existing "Invoice Adjustments" to carry forward
                    reason_by_invoice[row.invoice_number],
                )
                for row in new_rows
            ]
            client.update_values(spreadsheet_id, f"'{sheet_name}'!A{insert_at}:M{last_row}", values)

        client.update_values(
            spreadsheet_id, f"'{sheet_name}'!M{section_c_start_row - 1}", [["Flag Reason"]]
        )

        # Re-read Section C's CURRENT row positions -- a brand-new row's
        # insertion point (and every existing row at or below it) may
        # have shifted; see freight_sync.sync_freight_register's
        # docstring for why every Section A -> register link (not just
        # new matches) is recomputed and rewritten from a fresh read on
        # every run, same reasoning applies here.
        final_register_map, _ = read_existing_c_register(
            client, spreadsheet_id, sheet_name, section_c_start_row
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
            target_row = final_register_map.get(invoice_number, (None, None, None))[0]
            value = (
                f'=HYPERLINK("#gid={sheet_id}&range=A{target_row}", "{invoice_number}")'
                if target_row is not None else invoice_number
            )
            client.update_values(spreadsheet_id, f"'{sheet_name}'!D{match_row}", [[value]])

        row_flags = [
            (final_register_map[row.invoice_number][0], bool(reason_by_invoice[row.invoice_number]))
            for row in register_rows
            if row.invoice_number in final_register_map
        ]
        client.format_row_flags(spreadsheet_id, sheet_id, row_flags, num_columns=_NUM_COLUMNS)

        # Real Drive file smart chips for Deposit invoice (F, index 5),
        # Deposit payment (G, index 6), Balance invoice (H, index 7),
        # and Balance payment 1-4 (I/J/K/L, index 8-11) -- see
        # freight_sync.py's equivalent for why this is a separate pass
        # after the bulk row write, and why a link with no known file
        # id is simply skipped rather than blanked.
        chip_cells = [
            (final_register_map[row.invoice_number][0], column_index, file_ids)
            for row in register_rows
            if row.invoice_number in final_register_map
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

    return new_rows, updated_rows, section_a_backfills

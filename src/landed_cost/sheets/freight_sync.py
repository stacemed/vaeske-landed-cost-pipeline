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

Column L holds "Flag Reason" (see ``review_reason``) -- free space past
Section D's original A:K columns, created (and its header written) the
first time this runs. Column A's own Invoice # cell, and Section A's own
Invoice # cell for a matched row, are written as ``=HYPERLINK(...)``
formulas cross-linking the two -- see ``sync_freight_register``'s
docstring for why one direction is always safe to compute once, and the
other is recomputed and rewritten on every single apply run.
"""

from __future__ import annotations

from decimal import Decimal

from ..models.enums import Category
from .client import SheetsClient
from .freight_register import FreightRegisterRow
from .section_a_backfill import SectionATransaction, match_section_a_row, read_section_a_rows, review_reason

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


def _row_to_d_values(
    row: FreightRegisterRow, sheet_id: int, section_a_match_row: int | None, flag_reason: str
) -> list[object]:
    # Section A rows never shift position once matched (Section A only
    # ever grows via insert-at-last-row, which preserves every earlier
    # row's number) -- so this link is safe to compute once, here, and
    # never needs revisiting on a later run.
    invoice_number_cell = (
        f'=HYPERLINK("#gid={sheet_id}&range=D{section_a_match_row}", "{row.invoice_number}")'
        if section_a_match_row is not None
        else row.invoice_number
    )
    return [
        invoice_number_cell,
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
        flag_reason,
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
    tries the COMBINED total of every OTHER still-unmatched register row
    sharing its exact Paid date -- confirmed against real data that
    several Freight invoices routinely get paid together in one wire
    (both region-suffixed invoices sharing a base number, e.g. $2,321.58
    + $6,517.08 = $8,838.66 matching one real Section A row exactly; and
    entirely separate invoice numbers that just happened to be paid
    together). Matches only within a cent of the combined sum (same
    rounding tolerance as the single-invoice match -- see
    section_a_backfill.match_section_a_row; never guesses which subset
    of same-day invoices belong together beyond that), and writes ONE
    comma-joined Invoice # value listing every contributing invoice, not
    a last-write-wins overwrite from separate single-cell writes.

    Resolved in two passes -- every row's own single-invoice match is
    tried first, and only THEN is the combined-total pass run using the
    rows that are still unmatched. A real bug found doing this in one
    pass (2026-09-24): a same-day sibling that already matched its OWN
    dedicated Section A row (e.g. JG20240108E, individually matched)
    still got folded into another sibling's combined-total attempt
    (JG20240115E-CA/-US, a genuinely separate wire that only coincided
    on the same calendar date), inflating the sum past what any real
    Section A row held and leaving both unmatched.

    ``sort``, only meaningful together with ``apply`` and only when there
    are new rows to insert, sorts the whole Section D range by Paid date
    (ascending) after writing -- same opt-in native-sort behavior as
    Section A's/Section E's sync functions. Passes ``num_columns=12`` to
    cover Section D's full A:L range (see below).

    Every apply run also cross-links each matched pair of cells and
    marks rows needing review:

    - Column A (Invoice #) of every register row written this run
      becomes ``=HYPERLINK(..., invoice_number)`` targeting its matched
      Section A row, when one was found. Safe to compute once per row
      (see ``_row_to_d_values``'s docstring) -- Section A rows never
      move.
    - Column D (Invoice #) of EVERY Section A row currently linked to
      one or more of this run's invoices -- not just newly-matched
      ones -- is rewritten as ``=HYPERLINK(..., label)`` targeting the
      first (sorted) contributing invoice's CURRENT row in Section D.
      "Current" matters: ``--sort`` (or a manual sort done by hand in
      the Sheets UI between runs) can move a register row, which would
      leave a previously-written link pointing at the wrong row --
      rewriting every link fresh, from a read taken after this run's
      own insert/sort, means any staleness introduced since the last
      run is corrected every time this script runs. (The Sheets UI
      link itself has no way to notice a move on its own, so a link is
      only ever as fresh as the last sync.)
    - Column L (Flag Reason) gets ``review_reason``'s result for every
      row -- either the row's own extraction-level flag, or a genuine
      Section A backfill problem (never a "skipped, nothing filed yet"
      or an already-matched-in-a-previous-run false positive -- see
      ``review_reason``'s docstring). The row's whole A:L range is then
      colored light red (flagged) or cleared to white (clean) via
      ``client.format_row_flags``, so a problem is visible without
      re-running the script to see the terminal output.

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

    # Pass 1: every row's own single-invoice match.
    single_match_results: dict[str, tuple[int | None, str]] = {}
    for row in register_rows:
        if row.freight_amount is None or row.bundling_amount is None or row.paid_date is None:
            single_match_results[row.invoice_number] = (None, "skipped -- no amount/paid date to match on")
            continue
        own_amount = row.freight_amount + row.bundling_amount
        single_match_results[row.invoice_number] = match_section_a_row(
            row.paid_date, own_amount, section_a_rows, Category.FREIGHT_BUNDLING_PACKAGING
        )

    # Pass 2: for rows still unmatched, try the combined total of every
    # OTHER still-unmatched row sharing the same Paid date -- excluding
    # any sibling that already matched its own dedicated Section A row
    # in pass 1, which would inflate the sum past any real wire total
    # (see the docstring above for the real case this fixes).
    unmatched_rows = [
        row for row in register_rows
        if row.freight_amount is not None and row.bundling_amount is not None and row.paid_date is not None
        and single_match_results[row.invoice_number][0] is None
    ]
    unmatched_by_paid_date: dict[object, list[FreightRegisterRow]] = {}
    for row in unmatched_rows:
        unmatched_by_paid_date.setdefault(row.paid_date, []).append(row)

    section_a_backfills: list[tuple[FreightRegisterRow, int | None, str]] = []
    for row in register_rows:
        match_row, status = single_match_results[row.invoice_number]
        if match_row is None:
            siblings = unmatched_by_paid_date.get(row.paid_date, [])
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
                spreadsheet_id, f"'{sheet_name}'!A{row_number}:L{row_number}",
                [_row_to_d_values(row, sheet_id, match_row, reason_by_invoice[row.invoice_number])],
            )

        if new_rows:
            client.insert_rows(spreadsheet_id, sheet_id, insert_at, len(new_rows))
            last_row = insert_at + len(new_rows) - 1
            values = [
                _row_to_d_values(
                    r, sheet_id, match_by_invoice[r.invoice_number][0], reason_by_invoice[r.invoice_number]
                )
                for r in new_rows
            ]
            client.update_values(spreadsheet_id, f"'{sheet_name}'!A{insert_at}:L{last_row}", values)

            if sort:
                # Sort the WHOLE section, not just the new rows -- same
                # reasoning as sync_section_a/sync_overhead_register.
                new_last_row = first_empty_row + len(new_rows) - 1
                client.sort_range(
                    spreadsheet_id, sheet_id, section_d_start_row, new_last_row,
                    sort_column_index=2, num_columns=12,
                )

        client.update_values(
            spreadsheet_id, f"'{sheet_name}'!L{section_d_start_row - 1}", [["Flag Reason"]]
        )

        # Re-read the register's CURRENT row positions -- the update/
        # insert/sort above may have moved rows, so any Section A ->
        # register link (and this run's own highlight) must target
        # where each invoice number actually sits NOW.
        final_register_map, _ = read_existing_d_register(
            client, spreadsheet_id, sheet_name, section_d_start_row
        )

        # Every FREIGHT Section A row currently linked to one or more of
        # this run's invoices, whether that link is brand new this run
        # or was written by an earlier one -- see sync_freight_register's
        # docstring for why ALL of them get their link target
        # recomputed and rewritten every run, not just new matches.
        # Category-filtered: Section A holds Overhead/Components rows
        # too, sharing the same Invoice # column -- without this filter,
        # a Freight run would "refresh" (and in the process, downgrade
        # back to plain text, since it can't find that invoice number in
        # ITS OWN register) another category's already-correct link.
        combined_by_match_row: dict[int, list[str]] = {
            r.row_number: sorted(t.strip() for t in r.invoice_number.split(","))
            for r in section_a_rows
            if r.invoice_number and r.category == Category.FREIGHT_BUNDLING_PACKAGING
        }
        for row, match_row, _status in section_a_backfills:
            if match_row is not None:
                existing = combined_by_match_row.get(match_row, [])
                if row.invoice_number not in existing:
                    combined_by_match_row[match_row] = sorted(existing + [row.invoice_number])

        for match_row, invoice_numbers in combined_by_match_row.items():
            first_invoice = invoice_numbers[0]
            target_row = final_register_map.get(first_invoice)
            label = ", ".join(invoice_numbers)
            value = (
                f'=HYPERLINK("#gid={sheet_id}&range=A{target_row}", "{label}")'
                if target_row is not None else label
            )
            client.update_values(spreadsheet_id, f"'{sheet_name}'!D{match_row}", [[value]])

        row_flags = [
            (final_register_map[row.invoice_number], bool(reason_by_invoice[row.invoice_number]))
            for row in register_rows
            if row.invoice_number in final_register_map
        ]
        client.format_row_flags(spreadsheet_id, sheet_id, row_flags, num_columns=12)

    return new_rows, updated_rows, section_a_backfills

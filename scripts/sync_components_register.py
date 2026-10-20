#!/usr/bin/env python3
"""Sync the filed Components documents into 1 TRANSACTIONS Section C
(COMPONENT INVOICE REGISTER), then backfill Section A's Invoice #
column for every payment that matches.

Reads BOTH real Components folders and combines their filed documents --
confirmed against the live Drive layout (2026-10-20) that 2024 orders
and 2025 orders are filed in two separate folders (the second one, a
different owner's "...- Paid in 2025" folder, holds everything the
register's 2025 rows actually reference). Pass both folder IDs.

Unlike Freight/Overhead, this NEVER inserts a new row -- Components
invoice numbers follow no consistent format across vendors (see
components_register.py's own docstring for the real messiness: drifted
filename suffixes, a single deposit funding two split sub-orders whose
register invoice numbers don't exactly match any filename), so per the
project owner's own choice, a document is only ever matched to an
EXISTING register row by an exact (case-insensitive) invoice-number
match. A filed document that doesn't exactly match any existing row is
reported below as unmatched -- never silently dropped, never guessed
into a new row. Add that order's row to the sheet by hand once; every
later run then keeps it updated automatically.

"Total Order $" is extracted from whichever filed invoice states it
most reliably (see components_register.py for the known label patterns
per vendor), cross-checked against any payment confirmation's own
stated amount, and flagged -- never guessed -- when extraction fails;
the sheet's existing value is left untouched rather than blanked.
"Invoice Adjustments" is NEVER computed here at all -- always read from
the sheet and preserved exactly, added into the freshly extracted base
total to produce "Total Order $ (incl. exchng fees)".

Section C's row is found by searching column A for its own
"COMPONENT INVOICE REGISTER" title, not a hardcoded row number, same
reasoning as sync_freight_register.py/sync_overhead_register.py.
--section-c-start-row is an emergency override; you shouldn't need it.
Either way, the resolved row is verified against the sheet (must read
"Invoice #") before anything is written.

Every --apply run also cross-links the register to Section A: each
invoice's own Invoice # cell becomes a clickable link to its matched
Section A row, and vice versa (self-healing -- a link that goes stale
because a row moved gets corrected the next time this runs). A row
needing review gets a reason written into the new "Flag Reason" column
(M) and its whole row highlighted light red; a clean row's highlight is
cleared the same way.

Deposit invoice/Deposit payment/Balance invoice/Balance payment 1-4 are
written as real Drive file smart chips -- see sync_freight_register.py's
equivalent note for how and why.

Without --apply this only prints what it *would* write; nothing on the
sheet changes.

Usage:
    python3 scripts/sync_components_register.py <components_folder_id> <components_2025_folder_id> \\
        <spreadsheet_id> --credentials token.json
    python3 scripts/sync_components_register.py <components_folder_id> <components_2025_folder_id> \\
        <spreadsheet_id> --credentials token.json --apply

See docs/DRIVE_INGESTION.md for how to get a spreadsheet ID and a
credentials file authorized for the Drive + Sheets scopes.
"""

from __future__ import annotations

import argparse
import sys

from landed_cost.drive.google_client import GoogleDriveClient
from landed_cost.drive.pdf_text import extract_text_with_ocr_fallback
from landed_cost.models.documents import SourceDocument
from landed_cost.sheets.components_register import build_components_register_rows
from landed_cost.sheets.components_sync import read_existing_c_register, sync_components_register
from landed_cost.sheets.google_sheets_client import GoogleSheetsClient
from landed_cost.sheets.section_headers import (
    SECTION_C_TITLE_PATTERN,
    find_section_data_start_row,
    verify_column_header,
)


def _read_components_documents(
    drive_client: GoogleDriveClient, folder_ids: list[str]
) -> tuple[list[tuple[SourceDocument, str]], dict[str, str]]:
    documents: list[tuple[SourceDocument, str]] = []
    file_ids: dict[str, str] = {}
    for folder_id in folder_ids:
        for child in drive_client.list_children(folder_id):
            if child.is_folder:
                continue
            try:
                doc = SourceDocument.from_filename(child.name)
            except ValueError as exc:
                print(f"  ! skipping {child.name!r} -- doesn't match the filing convention: {exc}",
                      file=sys.stderr)
                continue
            print(f"Reading {child.name}...")
            data = drive_client.download_file(child.id)
            text, used_ocr = extract_text_with_ocr_fallback(data)
            if used_ocr:
                print(f"  (used OCR -- {child.name} has no real text layer)")
            documents.append((doc, text))
            file_ids[child.name] = child.id
    return documents, file_ids


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("components_folder_id", help="Drive folder ID of 'Invoices - Components'")
    parser.add_argument(
        "components_2025_folder_id",
        help="Drive folder ID of 'Invoices - Components- Paid in 2025' (or wherever newer orders are filed)",
    )
    parser.add_argument("spreadsheet_id", help="Google Sheets spreadsheet ID (from its URL)")
    parser.add_argument(
        "--credentials",
        required=True,
        help="Path to an OAuth authorized-user JSON file with the Drive + Sheets scopes "
        "(see docs/DRIVE_INGESTION.md)",
    )
    parser.add_argument(
        "--sheet-name",
        default="1 TRANSACTIONS",
        help="Sheet tab name (default: '1 TRANSACTIONS')",
    )
    parser.add_argument(
        "--section-c-start-row",
        type=int,
        default=None,
        help="Row number of Section C's FIRST DATA row. Normally left unset -- the script "
        "finds it by searching for the 'COMPONENT INVOICE REGISTER' section title, since its "
        "row number shifts over time. Only pass this to override that search.",
    )
    parser.add_argument(
        "--section-a-start-row",
        type=int,
        default=6,
        help="Row number of Section A's FIRST DATA row, for the Invoice # backfill (default: 6 "
        "-- stable, since nothing is ever inserted above Section A). Verified against the "
        "sheet (must read 'Category') before anything is written.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write to the sheet. Without this, only prints what it would write.",
    )
    args = parser.parse_args()

    drive_client = GoogleDriveClient.from_authorized_user_file(args.credentials)
    documents, file_ids = _read_components_documents(
        drive_client, [args.components_folder_id, args.components_2025_folder_id]
    )
    if not documents:
        print("No filed documents found (or none matched the filing convention).", file=sys.stderr)
        return 1

    sheets_client = GoogleSheetsClient.from_authorized_user_file(args.credentials)

    if args.section_c_start_row is not None:
        section_c_start_row = args.section_c_start_row
    else:
        try:
            section_c_start_row = find_section_data_start_row(
                sheets_client, args.spreadsheet_id, args.sheet_name, SECTION_C_TITLE_PATTERN
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(f"Found Section C at row {section_c_start_row} (searched for its "
              f"'COMPONENT INVOICE REGISTER' title).")

    try:
        verify_column_header(
            sheets_client, args.spreadsheet_id, args.sheet_name,
            section_c_start_row - 1, "A", "Invoice #",
        )
        verify_column_header(
            sheets_client, args.spreadsheet_id, args.sheet_name,
            args.section_a_start_row - 1, "A", "Category",
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    existing = read_existing_c_register(
        sheets_client, args.spreadsheet_id, args.sheet_name, section_c_start_row
    )
    register_rows, unmatched = build_components_register_rows(
        documents, existing_invoice_numbers=set(existing.keys()), file_ids=file_ids,
    )

    updated_rows, backfills = sync_components_register(
        sheets_client,
        args.spreadsheet_id,
        args.sheet_name,
        section_c_start_row,
        args.section_a_start_row,
        register_rows,
        apply=args.apply,
    )

    print(f"\n{len(register_rows)} existing invoice(s) matched from {len(documents)} filed document(s).")

    if unmatched:
        print(f"\n{len(unmatched)} filed document(s) didn't exactly match any existing Section C "
              f"Invoice # -- add the row by hand, then re-run:")
        for doc in sorted(unmatched, key=lambda d: d.raw_filename):
            print(f"  ! {doc.raw_filename} (invoice number read as {doc.invoice_number!r})")

    print(f"\n{len(updated_rows)} existing row(s){' to update' if not args.apply else ' updated'}:")
    flagged_count = 0
    for row_number, row in updated_rows:
        marker = "  ! " if row.flagged else "    "
        print(f"{marker}row {row_number}: {row.invoice_number:<28} | {row.balance_paid_date} | "
              f"{row.total_order_amount}")
        if row.flagged:
            flagged_count += 1
            print(f"      -> {row.flag_reason}")

    matched = [b for b in backfills if b[1] is not None]
    already_linked = [b for b in backfills if b[1] is None and b[2].startswith("already linked")]
    unmatched_backfills = [b for b in backfills if b[1] is None and not b[2].startswith("already linked")]
    print(f"\nSection A Invoice # backfill: {len(matched)} matched"
          f"{' and written' if args.apply else ' (would write)'}, "
          f"{len(already_linked)} already linked from a previous run, "
          f"{len(unmatched_backfills)} not matched:")
    for row, match_row, _status in matched:
        print(f"    {row.invoice_number:<28} -> row {match_row}")
    for row, _match_row, status in unmatched_backfills:
        print(f"  ! {row.invoice_number:<28} -> {status}")

    if flagged_count:
        print(f"\n{flagged_count} row(s) are flagged (extraction problem, refund document, or an "
              f"unclassified filed document) -- review and fill in by hand.")

    if not args.apply and updated_rows:
        print("\nDry run only -- pass --apply to actually write these changes.")

    return 1 if (flagged_count or unmatched) else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Sync the filed "Invoices - Overhead" documents into 1 TRANSACTIONS
Section E (OVERHEAD INVOICE REGISTER), then backfill Section A's Invoice #
column for every payment that matches.

Every filed file in the folder is read (non-recursive -- only the files
directly in it, not subfolders), grouped by invoice number, and turned
into one register row per invoice, per
landed_cost.sheets.overhead_register.build_overhead_register_rows. A file
whose name doesn't match the standardized filing convention is skipped
with a warning rather than crashing the whole run -- it never blocks
processing every other file.

An existing invoice number's row is fully overwritten (not patched) each
run, since a register row is always rebuilt from every currently-filed
document -- this is what correctly picks up e.g. a payment confirmation
that gets filed after its invoice was already registered on its own. A
brand-new invoice number gets a freshly inserted row.

Amount extraction is automated and trusted by default here (unlike
Components' planned Section C), since a Wise payment confirmation's text
is a fixed, machine-generated template -- see overhead_register.py's
docstring. When it still fails for a given invoice, that row is written
with a blank Overhead $ and flagged; fill it in by hand.

Without --apply this only prints what it *would* write; nothing on the
sheet changes.

Usage:
    python3 scripts/sync_overhead_register.py <overhead_folder_id> <spreadsheet_id> \\
        --credentials token.json
    python3 scripts/sync_overhead_register.py <overhead_folder_id> <spreadsheet_id> \\
        --credentials token.json --apply

See docs/DRIVE_INGESTION.md for how to get a spreadsheet ID and a
credentials file authorized for the Drive + Sheets scopes.
"""

from __future__ import annotations

import argparse
import sys

from landed_cost.drive.google_client import GoogleDriveClient
from landed_cost.drive.pdf_text import extract_text_with_ocr_fallback
from landed_cost.models.documents import SourceDocument
from landed_cost.sheets.google_sheets_client import GoogleSheetsClient
from landed_cost.sheets.overhead_register import build_overhead_register_rows
from landed_cost.sheets.overhead_sync import sync_overhead_register


def _read_overhead_documents(
    drive_client: GoogleDriveClient, folder_id: str
) -> list[tuple[SourceDocument, str]]:
    documents: list[tuple[SourceDocument, str]] = []
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
    return documents


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("overhead_folder_id", help="Drive folder ID of 'Invoices - Overhead'")
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
        "--section-e-start-row",
        type=int,
        default=100,
        help="Row number of Section E's FIRST DATA row, one below its header (default: 100, "
        "matching the live 2024 workbook -- check yours before relying on the default)",
    )
    parser.add_argument(
        "--section-a-start-row",
        type=int,
        default=6,
        help="Row number of Section A's FIRST DATA row, for the Invoice # backfill (default: 6)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write to the sheet. Without this, only prints what it would write.",
    )
    parser.add_argument(
        "--sort",
        action="store_true",
        help="After writing, sort the whole Section E range by Paid date (ascending). Only "
        "takes effect together with --apply, and only when new rows were inserted -- an "
        "in-place update of an existing row never changes its position. Opt-in, not "
        "automatic, same as --sort on sync_qbo_transactions.py.",
    )
    args = parser.parse_args()

    drive_client = GoogleDriveClient.from_authorized_user_file(args.credentials)
    documents = _read_overhead_documents(drive_client, args.overhead_folder_id)
    if not documents:
        print("No filed documents found (or none matched the filing convention).", file=sys.stderr)
        return 1

    register_rows = build_overhead_register_rows(documents)

    sheets_client = GoogleSheetsClient.from_authorized_user_file(args.credentials)
    new_rows, updated_rows, backfills = sync_overhead_register(
        sheets_client,
        args.spreadsheet_id,
        args.sheet_name,
        args.section_e_start_row,
        args.section_a_start_row,
        register_rows,
        apply=args.apply,
        sort=args.sort,
    )

    print(f"\n{len(register_rows)} invoice(s) built from {len(documents)} filed document(s).")
    print(f"{len(new_rows)} new row(s){' to write' if not args.apply else ' written'}:")
    flagged_count = 0
    for row in new_rows:
        marker = "  ! " if row.flagged else "    "
        print(f"{marker}{row.invoice_number:<28} | {row.paid_date} | {row.amount}")
        if row.flagged:
            flagged_count += 1
            print(f"      -> {row.flag_reason}")

    print(f"\n{len(updated_rows)} existing row(s){' to update' if not args.apply else ' updated'} "
          f"(re-filed/updated documents):")
    for row_number, row in updated_rows:
        marker = "  ! " if row.flagged else "    "
        print(f"{marker}row {row_number}: {row.invoice_number:<28} | {row.paid_date} | {row.amount}")
        if row.flagged:
            flagged_count += 1
            print(f"      -> {row.flag_reason}")

    matched = [b for b in backfills if b[1] is not None]
    unmatched = [b for b in backfills if b[1] is None]
    print(f"\nSection A Invoice # backfill: {len(matched)} matched"
          f"{' and written' if args.apply else ' (would write)'}, {len(unmatched)} not matched:")
    for row, match_row, status in matched:
        print(f"    {row.invoice_number:<28} -> row {match_row}")
    for row, _match_row, status in unmatched:
        print(f"  ! {row.invoice_number:<28} -> {status}")

    if flagged_count:
        print(f"\n{flagged_count} row(s) have a blank Overhead $ -- fill these in by hand.")

    if args.apply and args.sort and new_rows:
        print(f"\nSorted the whole Section E range (starting at row "
              f"{args.section_e_start_row}) by Paid date.")

    if not args.apply and (new_rows or updated_rows):
        print("\nDry run only -- pass --apply to actually write these changes.")

    return 1 if flagged_count else 0


if __name__ == "__main__":
    sys.exit(main())

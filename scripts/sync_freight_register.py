#!/usr/bin/env python3
"""Sync the filed "Invoices - Freight-Bundling" documents into 1
TRANSACTIONS Section D (FREIGHT INVOICE REGISTER), then backfill Section
A's Invoice # column for every payment that matches.

Every filed file in the folder is read (non-recursive -- only the files
directly in it, not subfolders), grouped by invoice number, and turned
into one register row per invoice, per
landed_cost.sheets.freight_register.build_freight_register_rows. A file
whose name doesn't match the standardized filing convention is skipped
with a warning rather than crashing the whole run -- it never blocks
processing every other file.

An existing invoice number's row is fully overwritten (not patched) each
run, since a register row is always rebuilt from every currently-filed
document. A brand-new invoice number gets a freshly inserted row. A
region-suffixed invoice number (e.g. JG20240115E-CA) keeps its own row
using its own stated Freight $/Bundling $ -- no summing -- but shares its
Paid date with every other invoice paying off the same base number, per
freight_register.py's module docstring.

Section D's row is found by searching column A for its own "FREIGHT
INVOICE REGISTER" title, not a hardcoded row number -- same reasoning
(and the same real incident, 2026-09-17) as sync_overhead_register.py.
--section-d-start-row is an emergency override; you shouldn't need it.
Either way, the resolved row is verified against the sheet (must read
"Invoice #") before anything is written.

Freight $/Bundling $ extraction is automated and trusted by default here
(unlike Components' planned Section C), since a Shenzhen Linkhub invoice's
text is a fixed, machine-generated template -- see freight_register.py's
docstring for both the older two-subtotal template and the newer
line-item-sum fallback it also supports. When it still fails for a given
invoice, that row is written with blank amounts and flagged; fill it in
by hand.

The Section A backfill also recognizes combined wires -- several Freight
invoices paid together in one wire, a real and common pattern -- by
trying the combined total of every register row sharing an exact Paid
date when no single invoice matches on its own. A combined match writes
one comma-joined Invoice # listing every contributing invoice, and shows
"(combined wire)" in this script's output.

Pass --prep-sheet-folder-id to also fill in the "Prep sheet link" column
(the Drive folder holding "Prep Instructions for John Grattan FBABEE
<YYYY-MM MON>" files) -- filled only on an unambiguous single match,
flagged otherwise. Omit it to skip that lookup entirely and leave "Prep
sheet link" blank on every row (the "Prep sheet" month label is always
filled in either way, since it's computed, not looked up).

Without --apply this only prints what it *would* write; nothing on the
sheet changes.

Usage:
    python3 scripts/sync_freight_register.py <freight_folder_id> <spreadsheet_id> \\
        --credentials token.json
    python3 scripts/sync_freight_register.py <freight_folder_id> <spreadsheet_id> \\
        --credentials token.json --prep-sheet-folder-id <prep_folder_id> --apply

See docs/DRIVE_INGESTION.md for how to get a spreadsheet ID and a
credentials file authorized for the Drive + Sheets scopes.
"""

from __future__ import annotations

import argparse
import sys

from landed_cost.drive.google_client import GoogleDriveClient
from landed_cost.drive.pdf_text import extract_text_with_ocr_fallback
from landed_cost.drive.prep_sheets import find_prep_sheet_link
from landed_cost.models.documents import SourceDocument
from landed_cost.sheets.freight_register import FreightRegisterRow, build_freight_register_rows
from landed_cost.sheets.freight_sync import sync_freight_register
from landed_cost.sheets.google_sheets_client import GoogleSheetsClient
from landed_cost.sheets.section_headers import (
    SECTION_D_TITLE_PATTERN,
    find_section_data_start_row,
    verify_column_header,
)


def _read_freight_documents(
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


def _resolve_prep_sheet_links(
    drive_client: GoogleDriveClient, prep_sheet_folder_id: str, rows: list[FreightRegisterRow]
) -> list[FreightRegisterRow]:
    resolved: list[FreightRegisterRow] = []
    for row in rows:
        if not row.prep_sheet_label:
            resolved.append(row)
            continue
        link, status = find_prep_sheet_link(drive_client, prep_sheet_folder_id, row.prep_sheet_label)
        if link:
            resolved.append(row.model_copy(update={"prep_sheet_link": link}))
        else:
            reason = f"prep sheet: {status}"
            combined = f"{row.flag_reason}; {reason}" if row.flag_reason else reason
            resolved.append(row.model_copy(update={"flagged": True, "flag_reason": combined}))
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("freight_folder_id", help="Drive folder ID of 'Invoices - Freight-Bundling'")
    parser.add_argument("spreadsheet_id", help="Google Sheets spreadsheet ID (from its URL)")
    parser.add_argument(
        "--credentials",
        required=True,
        help="Path to an OAuth authorized-user JSON file with the Drive + Sheets scopes "
        "(see docs/DRIVE_INGESTION.md)",
    )
    parser.add_argument(
        "--prep-sheet-folder-id",
        default=None,
        help="Drive folder ID holding the 'Prep Instructions for John Grattan FBABEE ...' files. "
        "Omit to skip filling in 'Prep sheet link' entirely (the 'Prep sheet' month label is "
        "always filled in regardless, since it's computed from the Paid date).",
    )
    parser.add_argument(
        "--sheet-name",
        default="1 TRANSACTIONS",
        help="Sheet tab name (default: '1 TRANSACTIONS')",
    )
    parser.add_argument(
        "--section-d-start-row",
        type=int,
        default=None,
        help="Row number of Section D's FIRST DATA row. Normally left unset -- the script "
        "finds it by searching for the 'FREIGHT INVOICE REGISTER' section title, since its "
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
    parser.add_argument(
        "--sort",
        action="store_true",
        help="After writing, sort the whole Section D range by Paid date (ascending). Only "
        "takes effect together with --apply, and only when new rows were inserted -- an "
        "in-place update of an existing row never changes its position. Opt-in, not "
        "automatic, same as --sort on sync_qbo_transactions.py / sync_overhead_register.py.",
    )
    args = parser.parse_args()

    drive_client = GoogleDriveClient.from_authorized_user_file(args.credentials)
    documents = _read_freight_documents(drive_client, args.freight_folder_id)
    if not documents:
        print("No filed documents found (or none matched the filing convention).", file=sys.stderr)
        return 1

    register_rows = build_freight_register_rows(documents)

    if args.prep_sheet_folder_id:
        register_rows = _resolve_prep_sheet_links(drive_client, args.prep_sheet_folder_id, register_rows)
    else:
        print("No --prep-sheet-folder-id given -- 'Prep sheet link' will be left blank on every row.")

    sheets_client = GoogleSheetsClient.from_authorized_user_file(args.credentials)

    if args.section_d_start_row is not None:
        section_d_start_row = args.section_d_start_row
    else:
        try:
            section_d_start_row = find_section_data_start_row(
                sheets_client, args.spreadsheet_id, args.sheet_name, SECTION_D_TITLE_PATTERN
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(f"Found Section D at row {section_d_start_row} (searched for its "
              f"'FREIGHT INVOICE REGISTER' title).")

    try:
        verify_column_header(
            sheets_client, args.spreadsheet_id, args.sheet_name,
            section_d_start_row - 1, "A", "Invoice #",
        )
        verify_column_header(
            sheets_client, args.spreadsheet_id, args.sheet_name,
            args.section_a_start_row - 1, "A", "Category",
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    new_rows, updated_rows, backfills = sync_freight_register(
        sheets_client,
        args.spreadsheet_id,
        args.sheet_name,
        section_d_start_row,
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
        print(f"{marker}{row.invoice_number:<24} | {row.paid_date} | freight {row.freight_amount} | bundling {row.bundling_amount}")
        if row.flagged:
            flagged_count += 1
            print(f"      -> {row.flag_reason}")

    print(f"\n{len(updated_rows)} existing row(s){' to update' if not args.apply else ' updated'} "
          f"(re-filed/updated documents):")
    for row_number, row in updated_rows:
        marker = "  ! " if row.flagged else "    "
        print(f"{marker}row {row_number}: {row.invoice_number:<24} | {row.paid_date} | freight {row.freight_amount} | bundling {row.bundling_amount}")
        if row.flagged:
            flagged_count += 1
            print(f"      -> {row.flag_reason}")

    matched = [b for b in backfills if b[1] is not None]
    unmatched = [b for b in backfills if b[1] is None]
    print(f"\nSection A Invoice # backfill: {len(matched)} matched"
          f"{' and written' if args.apply else ' (would write)'}, {len(unmatched)} not matched:")
    for row, match_row, status in matched:
        note = " (combined wire)" if "combined wire" in status else ""
        print(f"    {row.invoice_number:<24} -> row {match_row}{note}")
    for row, _match_row, status in unmatched:
        print(f"  ! {row.invoice_number:<24} -> {status}")

    if flagged_count:
        print(f"\n{flagged_count} row(s) are flagged (blank amounts, a payment-amount mismatch, "
              f"or an unresolved Prep sheet link) -- review and fill in by hand.")

    if args.apply and args.sort and new_rows:
        print(f"\nSorted the whole Section D range (starting at row "
              f"{section_d_start_row}) by Paid date.")

    if not args.apply and (new_rows or updated_rows):
        print("\nDry run only -- pass --apply to actually write these changes.")

    return 1 if flagged_count else 0


if __name__ == "__main__":
    sys.exit(main())

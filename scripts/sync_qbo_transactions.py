#!/usr/bin/env python3
"""Sync QBO "Account QuickReport" CSV(s) into 1 TRANSACTIONS Section A.

The fully mechanical slice of docs/QBO_EXTRACTION_SOP.md: Section A is
always literally the QBO ledger, and its category is determined by
vendor pattern alone -- no invoice reading needed. This does NOT do
everything that SOP covers -- Sections C/D/E (the invoice registers)
still need the invoice PDFs read and matched by hand/LLM; see the SOP.

Without --apply this only prints what it *would* write; nothing on the
sheet changes. Every new row is printed, including any with a blank
Category -- an unrecognized vendor is never guessed into a category,
so check for blank-Category rows in the dry-run output before applying.

The CSV can come from a local file, or from every .csv file sitting in
a Drive folder (e.g. drop each new QBO export there instead of copying
it to your machine -- mirrors the Inbox pattern in
landed_cost.drive.inbox). Read-only on Drive either way: files are
downloaded, never moved or deleted, since the (date, amount) dedup
already makes re-processing the same export a no-op.

Usage:
    python3 scripts/sync_qbo_transactions.py --qbo-csv qbo_export.csv <spreadsheet_id> \\
        --credentials token.json
    python3 scripts/sync_qbo_transactions.py --qbo-folder-id <drive_folder_id> <spreadsheet_id> \\
        --credentials token.json --apply

See docs/DRIVE_INGESTION.md for how to get a spreadsheet ID and a
credentials file authorized for the Sheets scope (scripts/get_token.py
requests it automatically -- regenerate token.json if yours predates
this script).
"""

from __future__ import annotations

import argparse
import sys

from landed_cost.drive.google_client import GoogleDriveClient
from landed_cost.sheets.google_sheets_client import GoogleSheetsClient
from landed_cost.sheets.qbo import merge_qbo_csv_texts
from landed_cost.sheets.sync import sync_section_a


def _read_local_csv(path: str) -> str:
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


def _read_csvs_from_drive_folder(credentials_path: str, folder_id: str) -> list[str]:
    client = GoogleDriveClient.from_authorized_user_file(credentials_path)
    csv_files = [
        child for child in client.list_children(folder_id)
        if not child.is_folder and child.name.lower().endswith(".csv")
    ]
    if not csv_files:
        print(f"No .csv files found in Drive folder {folder_id!r}.", file=sys.stderr)
    texts = []
    for f in csv_files:
        print(f"Reading {f.name} from Drive...")
        texts.append(client.download_file(f.id).decode("utf-8-sig"))
    return texts


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--qbo-csv", help="Path to a local QBO Account QuickReport CSV export")
    source.add_argument(
        "--qbo-folder-id",
        help="Drive folder ID to read every .csv file from instead of a local file "
        "(nothing is moved or deleted -- safe to leave files there across runs)",
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
        "--start-row",
        type=int,
        default=6,
        help="Row number of Section A's FIRST DATA row, i.e. one below the header (default: 6, "
        "matching every real 1 TRANSACTIONS layout seen so far -- check yours before relying on the default)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write new rows to the sheet. Without this, only prints what it would write.",
    )
    parser.add_argument(
        "--sort",
        action="store_true",
        help="After writing, sort the whole Section A range by Date (ascending). Only takes "
        "effect together with --apply. Opt-in, not automatic -- new rows land just above the "
        "previous last row rather than strictly at the bottom (see docs/QBO_EXTRACTION_SOP.md), "
        "so pass this if you want the sheet re-sorted chronologically after every run.",
    )
    args = parser.parse_args()

    if args.qbo_csv:
        texts = [_read_local_csv(args.qbo_csv)]
    else:
        texts = _read_csvs_from_drive_folder(args.credentials, args.qbo_folder_id)

    transactions = merge_qbo_csv_texts(texts)
    if not transactions:
        print("No transactions found.", file=sys.stderr)
        return 1

    client = GoogleSheetsClient.from_authorized_user_file(args.credentials)
    new_rows, skipped, first_write_row = sync_section_a(
        client,
        args.spreadsheet_id,
        args.sheet_name,
        args.start_row,
        transactions,
        apply=args.apply,
        sort=args.sort,
    )

    print(f"Parsed {len(transactions)} QBO transactions.")
    print(f"{len(skipped)} already present in the sheet (same date + amount), skipped.")
    print(f"{len(new_rows)} new row(s){' to write' if not args.apply else ' written'}, "
          f"starting at row {first_write_row} (Invoice # left blank -- filled in during "
          f"invoice reconciliation, see docs/QBO_EXTRACTION_SOP.md Step 2):\n")

    flagged_count = 0
    for row in new_rows:
        marker = "  ! " if row.flagged else "    "
        category = row.category.value if row.category is not None else "(blank)"
        print(f"{marker}{row.date} | {category:<32} | {row.payee:<28} | {row.amount}")
        if row.flagged:
            flagged_count += 1
            print(f"      -> {row.flag_reason}")

    if flagged_count:
        print(f"\n{flagged_count} row(s) have a blank Category -- fill these in by hand "
              f"before trusting 8 CONTROL's totals.")

    if args.apply and args.sort and new_rows:
        print(f"\nSorted the whole Section A range (rows {args.start_row}-{first_write_row + len(new_rows) - 1}) by Date.")

    if not args.apply and new_rows:
        print("\nDry run only -- pass --apply to actually write these rows.")

    return 1 if flagged_count else 0


if __name__ == "__main__":
    sys.exit(main())

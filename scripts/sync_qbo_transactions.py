#!/usr/bin/env python3
"""Sync a QBO "Account QuickReport" CSV into 1 TRANSACTIONS Section A.

The fully mechanical slice of docs/QBO_EXTRACTION_SOP.md: Section A is
always literally the QBO ledger, and its category is determined by
vendor pattern alone -- no invoice reading needed. This does NOT do
everything that SOP covers -- Sections C/D/E (the invoice registers)
still need the invoice PDFs read and matched by hand/LLM; see the SOP.

Without --apply this only prints what it *would* write; nothing on the
sheet changes. Every new row is printed, including any with a blank
Category -- an unrecognized vendor is never guessed into a category,
so check for blank-Category rows in the dry-run output before applying.

Usage:
    python scripts/sync_qbo_transactions.py qbo_export.csv <spreadsheet_id> \\
        --credentials token.json
    python scripts/sync_qbo_transactions.py qbo_export.csv <spreadsheet_id> \\
        --credentials token.json --apply

See docs/DRIVE_INGESTION.md for how to get a spreadsheet ID and a
credentials file authorized for the Sheets scope (scripts/get_token.py
requests it automatically -- regenerate token.json if yours predates
this script).
"""

from __future__ import annotations

import argparse
import sys

from landed_cost.sheets.google_sheets_client import GoogleSheetsClient
from landed_cost.sheets.qbo import parse_qbo_quickreport_csv
from landed_cost.sheets.sync import sync_section_a


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("qbo_csv", help="Path to the QBO Account QuickReport CSV export")
    parser.add_argument("spreadsheet_id", help="Google Sheets spreadsheet ID (from its URL)")
    parser.add_argument(
        "--credentials",
        required=True,
        help="Path to an OAuth authorized-user JSON file with the Sheets scope (see docs/DRIVE_INGESTION.md)",
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
    args = parser.parse_args()

    with open(args.qbo_csv, encoding="utf-8-sig") as f:
        text = f.read()
    transactions = parse_qbo_quickreport_csv(text)
    if not transactions:
        print("No transactions found in this CSV.", file=sys.stderr)
        return 1

    client = GoogleSheetsClient.from_authorized_user_file(args.credentials)
    new_rows, skipped, first_write_row = sync_section_a(
        client,
        args.spreadsheet_id,
        args.sheet_name,
        args.start_row,
        transactions,
        apply=args.apply,
    )

    print(f"Parsed {len(transactions)} QBO transactions.")
    print(f"{len(skipped)} already present in the sheet (same date + amount), skipped.")
    print(f"{len(new_rows)} new row(s){' to write' if not args.apply else ' written'}, "
          f"starting at row {first_write_row}:\n")

    flagged_count = 0
    for row in new_rows:
        marker = "  ! " if row.flagged else "    "
        category = row.category.value if row.category is not None else "(blank)"
        print(f"{marker}{row.date} | {category:<32} | {row.payee:<28} | "
              f"{row.invoice_number or '(no ref)':<12} | {row.amount}")
        if row.flagged:
            flagged_count += 1
            print(f"      -> {row.flag_reason}")

    if flagged_count:
        print(f"\n{flagged_count} row(s) have a blank Category -- fill these in by hand "
              f"before trusting 8 CONTROL's totals.")

    if not args.apply and new_rows:
        print("\nDry run only -- pass --apply to actually write these rows.")

    return 1 if flagged_count else 0


if __name__ == "__main__":
    sys.exit(main())

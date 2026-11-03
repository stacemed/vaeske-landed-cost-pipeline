#!/usr/bin/env python3
"""Strip 1 TRANSACTIONS Sections A/C/D/E down to a single year's rows
(or, with --template, down to no data rows at all) -- the first pass of
splitting the live "ALL YEARS" workbook into one spreadsheet per year.

Real context (2026-11-03): the live workbook has been accumulating
every year's data in one ever-growing sheet since the business started
(confirmed by pulling every row's real date: Section A 2024-2026,
Components 2024-2025, Freight 2024-2026, Overhead 2023-2026) -- not
something any one session's backfill introduced. That's what made every
hardcoded-range bug found this session possible in the first place. The
project owner's own choice is to split into one spreadsheet per year
going forward; a separate 2025 file already exists and is untouched by
this.

THIS SCRIPT NEVER TOUCHES THE LIVE/SOURCE SPREADSHEET. It only operates
on a spreadsheet ID you give it -- make a Drive copy of the source file
yourself first ("Make a copy" in the Sheets UI, once per target: one for
a blank template, one per year), then run this against each copy's own
ID. That keeps this script's blast radius to "a file you already,
deliberately duplicated," never the original.

Scope: Sections A/C/D/E within "1 TRANSACTIONS" only (the registers this
project's other scripts already build and understand). The downstream
tabs (2 FREIGHT, 3 COMPONENTS, 4 BUNDLING, 5 OVERHEAD, 6 UNIT COST, 7
YEAR-END) need a separate follow-up pass -- some of them (2 FREIGHT's
static invoice register, several hardcoded cross-tab ranges) need actual
formula fixes, not just a data split, and are deliberately out of scope
here.

Four real Components rows (INV-24Q4RR12C26C-CL, INV-24USQ4RR12C26C,
INV-US3rdR24-03, INV-USR2312-01) have no date in either column at all --
see year_split.py's FORCE_YEAR_BY_INVOICE_NUMBER for why, and why
they're bucketed as 2024 by the project owner's own explicit call.

Without --apply this only prints what it *would* delete; nothing on the
spreadsheet changes.

Usage:
    python3 scripts/split_sheet_by_year.py <spreadsheet_id> --credentials token.json --year 2024
    python3 scripts/split_sheet_by_year.py <spreadsheet_id> --credentials token.json --year 2024 --apply
    python3 scripts/split_sheet_by_year.py <spreadsheet_id> --credentials token.json --template --apply
"""

from __future__ import annotations

import argparse
import sys

from landed_cost.sheets.google_sheets_client import GoogleSheetsClient
from landed_cost.sheets.year_split import apply_year_split, plan_year_split


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "spreadsheet_id", help="Spreadsheet ID of a Drive COPY you already made -- never the live file"
    )
    parser.add_argument("--credentials", required=True, help="Path to an OAuth authorized-user JSON file")
    parser.add_argument(
        "--sheet-name", default="1 TRANSACTIONS", help="Sheet tab name (default: '1 TRANSACTIONS')"
    )
    year_group = parser.add_mutually_exclusive_group(required=True)
    year_group.add_argument("--year", type=int, help="Keep only this year's rows, delete everything else")
    year_group.add_argument("--template", action="store_true", help="Delete every data row (template mode)")
    parser.add_argument(
        "--apply", action="store_true", help="Actually delete rows. Without this, only prints the plan."
    )
    args = parser.parse_args()

    keep_year = None if args.template else args.year

    client = GoogleSheetsClient.from_authorized_user_file(args.credentials)
    try:
        plan = plan_year_split(client, args.spreadsheet_id, args.sheet_name, keep_year)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    label = "template (strip all data)" if args.template else f"keep {args.year}"
    print(f"Plan for spreadsheet {args.spreadsheet_id!r}, {label}:\n")
    total_planned = 0
    for name in ("A", "C", "D", "E"):
        row_count, ranges = plan[name]
        deleted = sum(count for _start, count in ranges)
        total_planned += deleted
        print(f"  Section {name}: {row_count} data row(s), {deleted} to delete, {row_count - deleted} to keep")
        for start, count in ranges:
            print(f"      delete rows {start}-{start + count - 1} ({count} row(s))")

    if not args.apply:
        print("\nDry run only -- pass --apply to actually delete these rows.")
        return 0

    sheet_id = client.get_sheet_id(args.spreadsheet_id, args.sheet_name)
    total_deleted = apply_year_split(client, args.spreadsheet_id, sheet_id, plan)
    print(f"\nDeleted {total_deleted} row(s) across Sections A/C/D/E.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

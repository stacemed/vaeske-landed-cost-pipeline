"""Splits 1 TRANSACTIONS Sections A/C/D/E by year -- the logic behind
``scripts/split_sheet_by_year.py``.

Real context (2026-11-03): the live "ALL YEARS" workbook has been
accumulating every year's data in one ever-growing sheet since the
business started (Section A: 2024-2026; Components: 2024-2025; Freight:
2024-2026; Overhead: 2023-2026) -- not something this session's
Components backfill introduced, confirmed by pulling every row's real
date. That's what made every hardcoded-range bug this session found
possible in the first place. The project owner's own choice is to split
into one spreadsheet per year going forward (a separate, already-
existing 2025 file is untouched by this); this module handles the FIRST
pass -- Sections A/C/D/E within "1 TRANSACTIONS" only. The downstream
tabs (2 FREIGHT, 3 COMPONENTS, etc.) need a separate follow-up pass, not
handled here.

This module never writes anything itself -- it only reads (via a
SheetsClient) and computes which row numbers to delete. The actual
``delete_rows`` calls are the caller's (the CLI script's) job, which
also makes the "which rows get deleted" decision independently
inspectable/testable from the "how do we safely issue the deletes"
mechanics.
"""

from __future__ import annotations

from datetime import date as date_cls

from .client import SheetsClient
from .section_headers import (
    SECTION_C_TITLE_PATTERN,
    SECTION_D_TITLE_PATTERN,
    SECTION_E_TITLE_PATTERN,
    find_section_data_start_row,
    verify_column_header,
)
from .sync import _is_total_row, _parse_cell_date

# Stable -- nothing is ever inserted above Section A.
SECTION_A_START_ROW = 6

# A few real Components rows have no date in EITHER column at all
# (confirmed 2026-11-03): Section C's own "Invoice date" is only ever
# set from a deposit invoice document (see components_register.py), and
# these 4 orders never had one filed -- they're balance-only or
# refund-only. Every one is part of the 2024 backfill batch; the
# project owner confirmed bucketing them as 2024 rather than leaving
# them unclassified (which would otherwise drop them from every year's
# file, silently losing real data).
FORCE_YEAR_BY_INVOICE_NUMBER: dict[str, int] = {
    "INV-24Q4RR12C26C-CL": 2024,
    "INV-24USQ4RR12C26C": 2024,
    "INV-US3rdR24-03": 2024,
    "INV-USR2312-01": 2024,
}


def effective_year(
    invoice_number: str, primary_date: date_cls | None, fallback_date: date_cls | None = None
) -> int | None:
    """The year a register row belongs to -- an explicit override (see
    ``FORCE_YEAR_BY_INVOICE_NUMBER``) if there is one, else the primary
    date column (e.g. Balance paid date), else the fallback (e.g.
    Invoice date). ``None`` when nothing resolves a year at all -- a
    caller must treat that as "can't safely place this row in any
    single year's file" rather than guess.
    """
    if invoice_number in FORCE_YEAR_BY_INVOICE_NUMBER:
        return FORCE_YEAR_BY_INVOICE_NUMBER[invoice_number]
    resolved = primary_date or fallback_date
    return resolved.year if resolved else None


def rows_to_delete(dated_rows: list[tuple[int, int | None]], keep_year: int | None) -> list[int]:
    """``dated_rows`` is ``(row_number, year_or_None)`` pairs for every
    data row in one section, already resolved via ``effective_year``.

    Returns the row numbers to delete. ``keep_year=None`` is template
    mode -- every data row is stripped, regardless of year. Otherwise,
    every row whose year doesn't match ``keep_year`` is deleted,
    INCLUDING a row with no resolvable year at all (an unclassifiable
    row can't safely go in any single year's file, so it's dropped from
    all of them rather than silently kept in whichever file happens to
    run the split first).
    """
    if keep_year is None:
        return [row_number for row_number, _year in dated_rows]
    return [row_number for row_number, year in dated_rows if year != keep_year]


def group_into_contiguous_ranges(row_numbers: list[int]) -> list[tuple[int, int]]:
    """Group row numbers into contiguous ``(start_row, count)`` ranges,
    merging adjacent rows into one range -- fewer, larger
    ``delete_rows`` calls instead of one per row.

    Input order doesn't matter; the result is sorted ascending by
    ``start_row``. A caller deleting them must go through the result in
    REVERSE (highest start_row first) so an earlier delete's row-number
    shift never lands on top of a later one still being computed
    against the original numbering -- see ``SheetsClient.delete_rows``.
    """
    if not row_numbers:
        return []
    ordered = sorted(row_numbers)
    ranges: list[tuple[int, int]] = []
    range_start = previous = ordered[0]
    for row_number in ordered[1:]:
        if row_number == previous + 1:
            previous = row_number
            continue
        ranges.append((range_start, previous - range_start + 1))
        range_start = previous = row_number
    ranges.append((range_start, previous - range_start + 1))
    return ranges


def _column_letter(index: int) -> str:
    # Single letters only (A-Z) -- every section in this workbook stays
    # well within column M, so there's no real case needing AA+.
    return chr(ord("A") + index)


def read_section_a_dates(
    client: SheetsClient, spreadsheet_id: str, sheet_name: str, start_row: int, max_rows: int = 1000
) -> list[tuple[int, date_cls | None]]:
    """``(row_number, date)`` for every Section A data row, in sheet
    order. Stops at the first row with an empty Date column (column B)
    -- same boundary as ``sync.read_existing_section_a``, which this
    duplicates rather than reuses: that function discards row numbers
    (it only needs a flat list for dedup), which is exactly what a
    splitter needs to keep.
    """
    end_row = start_row + max_rows - 1
    values = client.get_values(spreadsheet_id, f"'{sheet_name}'!A{start_row}:B{end_row}")
    rows: list[tuple[int, date_cls | None]] = []
    row_number = start_row
    for row in values:
        parsed_date = _parse_cell_date(row[1]) if len(row) > 1 else None
        if parsed_date is None:
            break
        rows.append((row_number, parsed_date))
        row_number += 1
    return rows


def read_register_dates(
    client: SheetsClient,
    spreadsheet_id: str,
    sheet_name: str,
    start_row: int,
    primary_date_col: int,
    fallback_date_col: int | None = None,
    max_rows: int = 1000,
) -> list[tuple[int, int | None]]:
    """``(row_number, effective_year)`` for every data row in a
    Section C/D/E-style register (Invoice # always column A -- index
    0). Stops at a blank Invoice # or the section's own trailing TOTAL
    label, same boundary rule as ``read_existing_c/d/e_register``.

    ``primary_date_col``/``fallback_date_col`` are 0-indexed within the
    row (e.g. Section C: Balance paid date (2) primary, Invoice date
    (1) fallback; Section D/E: Paid date (2) primary, Invoice date (1)
    fallback).
    """
    end_row = start_row + max_rows - 1
    last_col = max(primary_date_col, fallback_date_col or 0)
    values = client.get_values(
        spreadsheet_id, f"'{sheet_name}'!A{start_row}:{_column_letter(last_col)}{end_row}"
    )
    rows: list[tuple[int, int | None]] = []
    row_number = start_row
    for row in values:
        invoice_number = str(row[0]).strip() if row and row[0] else ""
        if not invoice_number or _is_total_row(invoice_number):
            break
        primary = _parse_cell_date(row[primary_date_col]) if len(row) > primary_date_col else None
        fallback = (
            _parse_cell_date(row[fallback_date_col])
            if fallback_date_col is not None and len(row) > fallback_date_col
            else None
        )
        year = effective_year(invoice_number, primary, fallback)
        rows.append((row_number, year))
        row_number += 1
    return rows


SplitPlan = dict[str, tuple[int, list[tuple[int, int]]]]

_REGISTER_SECTIONS = (
    ("C", SECTION_C_TITLE_PATTERN),
    ("D", SECTION_D_TITLE_PATTERN),
    ("E", SECTION_E_TITLE_PATTERN),
)


def plan_year_split(
    client: SheetsClient, spreadsheet_id: str, sheet_name: str, keep_year: int | None
) -> SplitPlan:
    """Read Sections A/C/D/E from ONE consistent snapshot (nothing is
    deleted by this call) and compute each section's delete plan.

    Returns ``{section_name: (section_row_count, delete_ranges)}`` --
    ``delete_ranges`` is already merged into contiguous ``(start_row,
    count)`` pairs (see ``group_into_contiguous_ranges``), ascending by
    start_row. ``keep_year=None`` is template mode: every data row in
    every section is planned for deletion.
    """
    verify_column_header(client, spreadsheet_id, sheet_name, SECTION_A_START_ROW - 1, "A", "Category")
    a_dates = read_section_a_dates(client, spreadsheet_id, sheet_name, SECTION_A_START_ROW)
    a_deletes = rows_to_delete([(r, d.year) for r, d in a_dates], keep_year)
    plan: SplitPlan = {"A": (len(a_dates), group_into_contiguous_ranges(a_deletes))}

    for name, pattern in _REGISTER_SECTIONS:
        start_row = find_section_data_start_row(client, spreadsheet_id, sheet_name, pattern)
        verify_column_header(client, spreadsheet_id, sheet_name, start_row - 1, "A", "Invoice #")
        dated_rows = read_register_dates(
            client, spreadsheet_id, sheet_name, start_row, primary_date_col=2, fallback_date_col=1
        )
        deletes = rows_to_delete(dated_rows, keep_year)
        plan[name] = (len(dated_rows), group_into_contiguous_ranges(deletes))

    return plan


def apply_year_split(client: SheetsClient, spreadsheet_id: str, sheet_id: int, plan: SplitPlan) -> int:
    """Issue the ``delete_rows`` calls for a plan from ``plan_year_split``
    and return the total number of rows deleted.

    Processes sections from the BOTTOM of the sheet (E) up to the TOP
    (A), and each section's own ranges highest-start_row-first -- a
    delete only ever shifts rows BELOW it, so working this way means
    every later delete still targets the row numbers from the single
    snapshot read ``plan_year_split`` took, never a number that's
    already gone stale from an earlier delete in this same run.
    """
    total_deleted = 0
    for name in ("E", "D", "C", "A"):
        _row_count, ranges = plan[name]
        for start_row, count in sorted(ranges, reverse=True):
            client.delete_rows(spreadsheet_id, sheet_id, start_row, count)
            total_deleted += count
    return total_deleted

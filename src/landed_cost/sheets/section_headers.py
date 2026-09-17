"""Locates a 1 TRANSACTIONS section's data by its own title row in column
A, instead of trusting a fixed row number passed in from the CLI.

Real incident, 2026-09-17: sync_overhead_register.py's --section-e-start-row
defaulted to 100, which matched Section E's position when the workbook was
first inspected. By the time it was actually run, Section A had grown
(every QBO sync inserts rows, pushing everything below it down), so row
100 no longer pointed at Section E's header -- it pointed at empty space
that used to be inside Section A. The script had no way to know its
target row was stale, so it silently wrote a run's worth of Section E
rows into the wrong place instead of failing loudly.

A hardcoded row number can *only* go stale silently. Finding a section by
searching for its own title text removes the whole failure mode: either
the title is found (and the row returned is *always* current, no matter
how much has shifted above it since), or it isn't and this raises instead
of guessing.
"""

from __future__ import annotations

import re

from .client import SheetsClient

# Matches "E · OVERHEAD INVOICE REGISTER" (and would match a future
# "D · FREIGHT INVOICE REGISTER" / "C · COMPONENT INVOICE REGISTER" the
# same way) without depending on the exact bullet character or spacing.
SECTION_E_TITLE_PATTERN = re.compile(r"OVERHEAD\s+INVOICE\s+REGISTER", re.IGNORECASE)


def find_section_data_start_row(
    client: SheetsClient,
    spreadsheet_id: str,
    sheet_name: str,
    title_pattern: re.Pattern[str],
    max_rows: int = 2000,
) -> int:
    """Search column A top-to-bottom for the row matching ``title_pattern``
    (a section's own title row) and return that section's first DATA row.

    Every section in this workbook follows the same shape: the title row
    itself, one column-header row directly below it ("Invoice #",
    "Invoice date", ...), then data -- so the result is ``title_row + 2``.

    Raises ``ValueError`` rather than returning anything if no row
    matches -- a caller should never fall back to a guessed row number.
    """
    values = client.get_values(spreadsheet_id, f"'{sheet_name}'!A1:A{max_rows}")
    for i, row in enumerate(values):
        cell = str(row[0]).strip() if row and row[0] else ""
        if title_pattern.search(cell):
            return i + 1 + 2  # i is 0-indexed; +1 for the 1-indexed title row, +2 skips it and the column-header row
    raise ValueError(
        f"could not find a section title row matching {title_pattern.pattern!r} in "
        f"{sheet_name!r} column A (searched rows 1-{max_rows}) -- refusing to guess "
        f"its location. Check --sheet-name, or that the section header text hasn't "
        f"been reworded."
    )


def verify_column_header(
    client: SheetsClient,
    spreadsheet_id: str,
    sheet_name: str,
    header_row: int,
    column: str,
    expected_substring: str,
) -> None:
    """Sanity-check that ``column`` on ``header_row`` actually contains
    ``expected_substring`` before anything gets written.

    The last line of defense against a start row that's wrong for any
    reason (a bad --section-*-start-row override, a workbook restructure,
    a bug in this module itself) -- refuses to write into a row that
    doesn't look like the header it's supposed to be, rather than
    silently trusting the number.
    """
    values = client.get_values(
        spreadsheet_id, f"'{sheet_name}'!{column}{header_row}:{column}{header_row}"
    )
    actual = str(values[0][0]).strip() if values and values[0] else ""
    if expected_substring.lower() not in actual.lower():
        raise ValueError(
            f"expected {column}{header_row} in {sheet_name!r} to contain "
            f"{expected_substring!r}, found {actual!r} instead -- refusing to "
            f"write, the target row doesn't look right"
        )

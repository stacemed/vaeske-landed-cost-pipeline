"""Shared in-memory SheetsClient test double. Not a test file itself
(no ``test_`` prefix, so pytest won't try to collect it) -- imported by
whichever test modules need a fake Sheets backend.
"""

from __future__ import annotations

import re

from landed_cost.sheets.sync import _parse_cell_date


class FakeSheetsClient:
    """In-memory Sheets stand-in. Stores a single sheet's cells as
    {row_number: [col_a, col_b, ...]} (0-indexed within the list, 1-
    indexed row numbers matching A1 notation), so tests can assert on
    exactly what a real ``GoogleSheetsClient`` would have written.

    Column-aware: ``get_values``/``update_values`` only touch the exact
    columns named in the A1 range, merging into (not replacing) a
    stored row -- a real ``values.update`` on ``D6:D6`` never disturbs
    columns A-C or E-F, and this fake needs to match that or a test
    could pass while the real client would silently corrupt a row.
    """

    def __init__(self, rows: dict[int, list[object]]):
        self._rows = dict(rows)
        self.updates: list[tuple[str, list[list[object]]]] = []
        self.inserts: list[tuple[int, int]] = []
        self.sorts: list[tuple[int, int, int, bool]] = []

    def get_values(self, spreadsheet_id: str, a1_range: str) -> list[list[object]]:
        start_row, end_row, start_col, end_col = _parse_a1_range(a1_range)
        values = []
        for row_number in range(start_row, end_row + 1):
            if row_number not in self._rows:
                break
            full_row = self._rows[row_number]
            values.append(full_row[start_col : end_col + 1])
        return values

    def update_values(self, spreadsheet_id: str, a1_range: str, values: list[list[object]]) -> None:
        start_row, _end_row, start_col, _end_col = _parse_a1_range(a1_range)
        for i, row_values in enumerate(values):
            row_number = start_row + i
            existing = list(self._rows.get(row_number, []))
            needed_len = start_col + len(row_values)
            while len(existing) < needed_len:
                existing.append("")
            for j, v in enumerate(row_values):
                existing[start_col + j] = v
            self._rows[row_number] = existing
        self.updates.append((a1_range, values))

    def get_sheet_id(self, spreadsheet_id: str, sheet_name: str) -> int:
        return 12345  # tests don't care about the real GID

    def insert_rows(self, spreadsheet_id: str, sheet_id: int, start_row: int, num_rows: int) -> None:
        self.inserts.append((start_row, num_rows))
        # Shift every row at/after start_row down by num_rows -- highest
        # row number first so nothing gets clobbered mid-shift.
        for row_number in sorted((r for r in self._rows if r >= start_row), reverse=True):
            self._rows[row_number + num_rows] = self._rows.pop(row_number)

    def sort_range(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        start_row: int,
        end_row: int,
        sort_column_index: int,
        ascending: bool = True,
    ) -> None:
        self.sorts.append((start_row, end_row, sort_column_index, ascending))
        rows_in_range = [self._rows[r] for r in range(start_row, end_row + 1) if r in self._rows]
        rows_in_range.sort(
            key=lambda row: _parse_cell_date(row[sort_column_index]) if len(row) > sort_column_index else None,
            reverse=not ascending,
        )
        for i, row in enumerate(rows_in_range):
            self._rows[start_row + i] = row


_CELL_RE = re.compile(r"([A-Z]+)(\d+)")


def _col_letters_to_index(letters: str) -> int:
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index - 1  # 0-indexed


def _parse_a1_range(a1_range: str) -> tuple[int, int, int, int]:
    # e.g. "'1 TRANSACTIONS'!A6:E1005" -> (6, 1005, 0, 4); "D6:D6" -> (6, 6, 3, 3)
    # A single cell with no colon ("D6") is also valid A1 notation.
    cell_part = a1_range.split("!")[-1]
    start_cell, _, end_cell = cell_part.partition(":")
    end_cell = end_cell or start_cell
    start_match, end_match = _CELL_RE.match(start_cell), _CELL_RE.match(end_cell)
    start_col = _col_letters_to_index(start_match.group(1))
    start_row = int(start_match.group(2))
    end_col = _col_letters_to_index(end_match.group(1))
    end_row = int(end_match.group(2))
    return start_row, end_row, start_col, end_col

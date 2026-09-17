"""The minimal Sheets surface the QBO sync needs -- read a range, write a
range. Deliberately narrow, same reasoning as ``landed_cost.drive.client``:
a real Sheets API client and an in-memory fake used in tests can both
satisfy ``SheetsClient`` without either depending on the other.
"""

from __future__ import annotations

from typing import Protocol


class SheetsClient(Protocol):
    def get_values(self, spreadsheet_id: str, a1_range: str) -> list[list[object]]:
        """Return the unformatted cell values in ``a1_range``, row by
        row -- numbers as ``int``/``float``, not a display-formatted
        string (a real implementation should use
        ``valueRenderOption=UNFORMATTED_VALUE``). Short rows (trailing
        blank cells) are not padded -- callers index defensively.
        """
        ...

    def update_values(self, spreadsheet_id: str, a1_range: str, values: list[list[object]]) -> None:
        """Overwrite ``a1_range`` with ``values``, row by row. The range
        must already be sized to fit ``values`` -- this never inserts
        rows or shifts anything below it. Only ever call this on a
        range you know is safe to overwrite (e.g. one ``insert_rows``
        just made room for) -- see its docstring for why a plain
        overwrite on its own is not safe for Section A.
        """
        ...

    def get_sheet_id(self, spreadsheet_id: str, sheet_name: str) -> int:
        """Return the sheet tab's internal numeric ID (GID) for its
        title -- structural operations like ``insert_rows`` address a
        tab by this ID, not its name.
        """
        ...

    def insert_rows(self, spreadsheet_id: str, sheet_id: int, start_row: int, num_rows: int) -> None:
        """Insert ``num_rows`` blank rows starting at ``start_row``
        (1-indexed), shifting that row and everything below it down.

        This is what makes writing new Section A rows safe: Section A
        sits above other sections (B, C, D, E...) in the same sheet
        with only a couple of blank buffer rows between them.
        ``update_values`` alone would overwrite whatever happens to
        already be sitting in the target range once there are more new
        rows than that buffer -- a real bug found in practice (a
        4-transaction sync would have overwritten the "B · BY CATEGORY"
        section header). Inserting first means new rows are always
        genuinely blank before anything gets written into them, no
        matter how many there are.

        Also carries cell formatting forward from the row directly
        above the insertion point (a real implementation should pass
        ``inheritFromBefore=True``), so new rows automatically match
        the existing sheet's font/color/number formatting instead of
        coming in blank -- the same behavior as using "Insert row
        above" in the Sheets UI by hand.
        """
        ...

    def sort_range(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        start_row: int,
        end_row: int,
        sort_column_index: int,
        ascending: bool = True,
        num_columns: int = 5,
    ) -> None:
        """Sort rows ``start_row..end_row`` (1-indexed, inclusive) by
        the given 0-indexed column within that row (0 = column A).

        ``num_columns`` bounds the sorted range to columns A through
        however many that section actually has -- default 5 (A:E)
        matches Section A; a section with a different column count
        (e.g. Section E's 6, A:F) must pass its own, or a native sort
        would silently leave that section's last column behind while
        every other column moves with the sort.

        Uses the Sheets API's native sort-range operation (the same
        one "Data > Sort range" runs in the UI), not a read-then-
        rewrite of plain values -- that matters because a native sort
        carries each row's cell formatting along with it as rows move,
        while writing sorted values back into a fixed range would
        leave formatting stuck at its old row position, mismatched
        with whatever data now sits there.
        """
        ...

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
        rows or shifts anything below it.
        """
        ...

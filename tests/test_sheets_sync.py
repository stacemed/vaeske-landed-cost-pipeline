from datetime import date
from decimal import Decimal

from landed_cost.models import Category
from landed_cost.sheets.qbo import QboTransaction
from landed_cost.sheets.sync import read_existing_section_a, sync_section_a


class FakeSheetsClient:
    """In-memory Sheets stand-in. Stores a single sheet's cells as
    {row_number: [col_a, col_b, ...]}, keyed by 1-indexed row number
    matching A1 notation, so tests can assert on exactly what a real
    ``GoogleSheetsClient`` would have written.
    """

    def __init__(self, rows: dict[int, list[object]]):
        self._rows = dict(rows)
        self.updates: list[tuple[str, list[list[object]]]] = []
        self.inserts: list[tuple[int, int]] = []

    def get_values(self, spreadsheet_id: str, a1_range: str) -> list[list[object]]:
        start_row, end_row = _parse_row_range(a1_range)
        values = []
        for row_number in range(start_row, end_row + 1):
            if row_number not in self._rows:
                break
            values.append(self._rows[row_number])
        return values

    def update_values(self, spreadsheet_id: str, a1_range: str, values: list[list[object]]) -> None:
        start_row, _ = _parse_row_range(a1_range)
        for i, row in enumerate(values):
            self._rows[start_row + i] = row
        self.updates.append((a1_range, values))

    def get_sheet_id(self, spreadsheet_id: str, sheet_name: str) -> int:
        return 12345  # tests don't care about the real GID

    def insert_rows(self, spreadsheet_id: str, sheet_id: int, start_row: int, num_rows: int) -> None:
        self.inserts.append((start_row, num_rows))
        # Shift every row at/after start_row down by num_rows -- highest
        # row number first so nothing gets clobbered mid-shift.
        for row_number in sorted((r for r in self._rows if r >= start_row), reverse=True):
            self._rows[row_number + num_rows] = self._rows.pop(row_number)


def _parse_row_range(a1_range: str) -> tuple[int, int]:
    # e.g. "'1 TRANSACTIONS'!A6:E1005" -> (6, 1005)
    cells = a1_range.split("!")[-1].split(":")
    start_row = int("".join(c for c in cells[0] if c.isdigit()))
    end_row = int("".join(c for c in cells[1] if c.isdigit()))
    return start_row, end_row


def test_read_existing_section_a_stops_at_first_blank_date():
    client = FakeSheetsClient({
        6: ["Freight / bundling / packaging", "2024-01-16", "FBA Bee", "TRN7207", 990.04],
        7: ["Components", "2024-01-08", "Shenzhen Minzhi BYJ Trading Co", "TRN2548", 16948.60],
        8: ["", "", "", "", ""],  # blank separator before the next section
    })

    existing, first_empty_row = read_existing_section_a(client, "sheet1", "1 TRANSACTIONS", start_row=6)

    assert existing == [
        (date(2024, 1, 16), Decimal("990.04")),
        (date(2024, 1, 8), Decimal("16948.60")),
    ]
    assert first_empty_row == 8


def test_read_existing_section_a_handles_empty_section():
    client = FakeSheetsClient({})

    existing, first_empty_row = read_existing_section_a(client, "sheet1", "1 TRANSACTIONS", start_row=6)

    assert existing == []
    assert first_empty_row == 6


def test_sync_section_a_dry_run_does_not_write():
    client = FakeSheetsClient({})
    transactions = [
        QboTransaction(date=date(2024, 1, 16), name="", description="Shenzhen Linkhub Co Ltd", amount=Decimal("990.04")),
    ]

    new_rows, skipped, first_write_row = sync_section_a(
        client, "sheet1", "1 TRANSACTIONS", start_row=6, transactions=transactions, apply=False
    )

    assert len(new_rows) == 1
    assert new_rows[0].category is Category.FREIGHT_BUNDLING_PACKAGING
    assert first_write_row == 6
    assert client.updates == []  # nothing written


def test_sync_section_a_apply_writes_new_rows_after_existing_data():
    client = FakeSheetsClient({
        6: ["Freight / bundling / packaging", "2024-01-08", "FBA Bee", "TRN0001", 100.0],
    })
    transactions = [
        QboTransaction(date=date(2024, 1, 8), name="", description="Shenzhen Linkhub", amount=Decimal("100.00")),  # duplicate
        QboTransaction(date=date(2024, 1, 16), name="", description="Shenzhen Linkhub Co Ltd", amount=Decimal("990.04")),
    ]

    new_rows, skipped, first_write_row = sync_section_a(
        client, "sheet1", "1 TRANSACTIONS", start_row=6, transactions=transactions, apply=True
    )

    assert len(skipped) == 1
    assert len(new_rows) == 1
    assert first_write_row == 7
    assert client.inserts == [(7, 1)]  # inserted before writing, not overwritten in place
    assert client.updates == [
        ("'1 TRANSACTIONS'!A7:E7", [["Freight / bundling / packaging", "01/16/2024", "FBA Bee", "", 990.04]])
    ]
    # row was actually appended into the fake sheet's row 7
    assert client._rows[7][1] == "01/16/2024"


def test_sync_section_a_apply_inserts_rows_instead_of_overwriting_what_follows():
    # Real bug (2026-09-17): a plain overwrite of a fixed range only
    # avoided clobbering Section B by luck -- exactly as many new
    # transactions as there happened to be blank buffer rows. With
    # more new rows than buffer rows, a plain overwrite would have
    # written directly over "B · BY CATEGORY" and real Components data
    # below it. Inserting first must shift all of that down instead.
    client = FakeSheetsClient({
        6: ["Overhead", "2024-01-08", "Weimin Huang", "", 399.0],
        7: ["", "", "", "", ""],   # blank buffer row 1
        8: ["", "", "", "", ""],   # blank buffer row 2
        9: ["B · BY CATEGORY -- each ties to a sheet", "", "", "", ""],
        10: ["Category", "Txns", "Cash paid $", "Built up on", "Built-up total $"],
        11: ["Components", 14, 154936.36, "3 COMPONENTS", 154798.17],
    })
    transactions = [
        QboTransaction(date=date(2024, 1, 9), name="", description="Shenzhen Linkhub", amount=Decimal("100.00")),
        QboTransaction(date=date(2024, 1, 10), name="", description="Shenzhen Linkhub", amount=Decimal("200.00")),
        QboTransaction(date=date(2024, 1, 11), name="", description="Shenzhen Linkhub", amount=Decimal("300.00")),
        QboTransaction(date=date(2024, 1, 12), name="", description="Shenzhen Linkhub", amount=Decimal("400.00")),
    ]  # 4 new transactions -- more than the 2-row blank buffer

    new_rows, skipped, first_write_row = sync_section_a(
        client, "sheet1", "1 TRANSACTIONS", start_row=6, transactions=transactions, apply=True
    )

    assert len(new_rows) == 4
    assert first_write_row == 7
    assert client.inserts == [(7, 4)]
    # Section B's header and its data must be intact, shifted down by 4
    # (row 9 -> 13, row 11 -> 15) -- never overwritten.
    assert client._rows[13][0] == "B · BY CATEGORY -- each ties to a sheet"
    assert client._rows[15][0] == "Components"
    # the new transaction rows landed in the freshly-inserted space
    assert client._rows[7][1] == "01/09/2024"
    assert client._rows[10][1] == "01/12/2024"


def test_sync_section_a_flags_unclassified_vendor_but_still_writes_it():
    client = FakeSheetsClient({})
    transactions = [
        QboTransaction(date=date(2024, 7, 25), name="Aco Mexico", description="ACO MEX APTO T1 URBAN", amount=Decimal("5.86")),
    ]

    new_rows, skipped, first_write_row = sync_section_a(
        client, "sheet1", "1 TRANSACTIONS", start_row=6, transactions=transactions, apply=True
    )

    assert len(new_rows) == 1
    assert new_rows[0].category is None
    assert new_rows[0].flagged is True
    # still written -- a real QBO transaction is never silently dropped,
    # even when its category couldn't be determined
    assert client._rows[6][0] == ""

from datetime import date
from decimal import Decimal

from landed_cost.models import Category
from landed_cost.sheets.qbo import QboTransaction
from landed_cost.sheets.sync import read_existing_section_a, sync_section_a

from sheets_fakes import FakeSheetsClient


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


def test_sync_section_a_apply_inserts_at_the_last_existing_row_not_one_past_it():
    # Deliberate, not off-by-one: inserting AT the last existing data
    # row (pushing it down) falls within a formula's existing range
    # (e.g. SUM(E5:E6)), so Sheets auto-extends it. Inserting one row
    # past the end (the naive approach) never extends it -- confirmed
    # on a real run, a SUM(E5:E50) stayed frozen after new rows landed
    # right after row 50.
    client = FakeSheetsClient({
        6: ["Freight / bundling / packaging", "2024-01-08", "FBA Bee", "", 100.0],
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
    assert first_write_row == 6
    assert client.inserts == [(6, 1)]
    assert client.updates == [
        ("'1 TRANSACTIONS'!A6:E6", [["Freight / bundling / packaging", "01/16/2024", "FBA Bee", "", 990.04]])
    ]
    # new row landed at 6; the previously-last existing row got pushed to 7
    assert client._rows[6][1] == "01/16/2024"
    assert client._rows[7][1] == "2024-01-08"


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
    assert first_write_row == 6
    assert client.inserts == [(6, 4)]
    # Section B's header and its data must be intact, shifted down by 4
    # (row 9 -> 13, row 11 -> 15) -- never overwritten.
    assert client._rows[13][0] == "B · BY CATEGORY -- each ties to a sheet"
    assert client._rows[15][0] == "Components"
    # the new transaction rows landed in the freshly-inserted space,
    # and the previously-last existing row was pushed down intact
    assert client._rows[6][1] == "01/09/2024"
    assert client._rows[9][1] == "01/12/2024"
    assert client._rows[10][1] == "2024-01-08"


def test_sync_section_a_without_sort_leaves_new_row_out_of_chronological_order():
    # Documents the trade-off sort=True fixes: new rows land just above
    # the previous last row (see insert_at in sync_section_a), so a
    # later-dated new transaction ends up ABOVE an earlier existing one.
    client = FakeSheetsClient({
        6: ["Overhead", "2024-01-05", "Weimin Huang", "", 100.0],
    })
    transactions = [
        QboTransaction(date=date(2024, 3, 1), name="", description="Shenzhen Linkhub", amount=Decimal("50.00")),
    ]

    sync_section_a(
        client, "sheet1", "1 TRANSACTIONS", start_row=6, transactions=transactions, apply=True, sort=False
    )

    assert client.sorts == []
    assert client._rows[6][1] == "03/01/2024"  # newer transaction on top
    assert client._rows[7][1] == "2024-01-05"  # older one pushed below it


def test_sync_section_a_with_sort_restores_chronological_order():
    client = FakeSheetsClient({
        6: ["Overhead", "2024-01-05", "Weimin Huang", "", 100.0],
    })
    transactions = [
        QboTransaction(date=date(2024, 3, 1), name="", description="Shenzhen Linkhub", amount=Decimal("50.00")),
    ]

    sync_section_a(
        client, "sheet1", "1 TRANSACTIONS", start_row=6, transactions=transactions, apply=True, sort=True
    )

    assert client.sorts == [(6, 7, 1, True, 5)]  # column index 1 = Date, ascending, A:E
    assert client._rows[6][1] == "2024-01-05"  # earlier date now first
    assert client._rows[7][1] == "03/01/2024"  # later date now second


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

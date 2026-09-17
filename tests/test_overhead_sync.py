from datetime import date
from decimal import Decimal

from landed_cost.sheets.overhead_register import OverheadRegisterRow
from landed_cost.sheets.overhead_sync import (
    SectionATransaction,
    match_section_a_row,
    read_existing_e_register,
    read_section_a_rows,
    sync_overhead_register,
)
from landed_cost.models import Category

from sheets_fakes import FakeSheetsClient


def _row(invoice_number, invoice_date=None, paid_date=None, amount=None,
         invoice_link="", payment_link="", flagged=False, flag_reason=""):
    return OverheadRegisterRow(
        invoice_number=invoice_number, invoice_date=invoice_date, paid_date=paid_date,
        amount=amount, invoice_link=invoice_link, payment_link=payment_link,
        flagged=flagged, flag_reason=flag_reason,
    )


def test_read_existing_e_register_stops_at_blank_invoice_number_not_blank_date():
    # Real sheet fact: a monthly-retainer row can have NO Invoice date at
    # all and still be a legitimate, populated row -- using date-blank
    # as the stop condition (like Section A) would wrongly cut the
    # register short.
    client = FakeSheetsClient({
        100: ["Wise 1370922330", "", "01/10/2025", 399.0, "", "monthly.pdf"],
        101: ["INV-Inspection-250214", "02/15/2025", "02/14/2025", 88.88, "inv.pdf", "pconf.pdf"],
        102: ["", "", "", "", "", ""],
    })

    existing, first_empty_row = read_existing_e_register(client, "sheet1", "1 TRANSACTIONS", start_row=100)

    assert existing == {"Wise 1370922330": 100, "INV-Inspection-250214": 101}
    assert first_empty_row == 102


def test_read_section_a_rows_parses_category_and_invoice_number():
    client = FakeSheetsClient({
        6: ["Overhead", "2024-01-11", "Weimin Huang", "", 218.0],
        7: ["Freight / bundling / packaging", "2024-01-16", "FBA Bee", "JG20240108E", 990.04],
    })

    rows = read_section_a_rows(client, "sheet1", "1 TRANSACTIONS", start_row=6)

    assert rows == [
        SectionATransaction(row_number=6, category=Category.OVERHEAD, date=date(2024, 1, 11),
                             amount=Decimal("218.0"), invoice_number=""),
        SectionATransaction(row_number=7, category=Category.FREIGHT_BUNDLING_PACKAGING,
                             date=date(2024, 1, 16), amount=Decimal("990.04"),
                             invoice_number="JG20240108E"),
    ]


def test_match_section_a_row_matches_same_year_month_different_day():
    section_a = [
        SectionATransaction(row_number=6, category=Category.OVERHEAD, date=date(2024, 1, 11),
                             amount=Decimal("218.00"), invoice_number=""),
    ]

    match_row, status = match_section_a_row(date(2024, 1, 9), Decimal("218.00"), section_a, Category.OVERHEAD)

    assert match_row == 6
    assert status == "matched"


def test_match_section_a_row_never_overwrites_an_already_filled_invoice_number():
    section_a = [
        SectionATransaction(row_number=6, category=Category.OVERHEAD, date=date(2024, 1, 11),
                             amount=Decimal("218.00"), invoice_number="already-set"),
    ]

    match_row, status = match_section_a_row(date(2024, 1, 11), Decimal("218.00"), section_a, Category.OVERHEAD)

    assert match_row is None
    assert "no matching" in status


def test_match_section_a_row_flags_ambiguous_matches_instead_of_guessing():
    section_a = [
        SectionATransaction(row_number=6, category=Category.OVERHEAD, date=date(2024, 1, 5),
                             amount=Decimal("399.00"), invoice_number=""),
        SectionATransaction(row_number=7, category=Category.OVERHEAD, date=date(2024, 1, 28),
                             amount=Decimal("399.00"), invoice_number=""),
    ]

    match_row, status = match_section_a_row(date(2024, 1, 10), Decimal("399.00"), section_a, Category.OVERHEAD)

    assert match_row is None
    assert "ambiguous" in status


def test_sync_overhead_register_inserts_new_row_and_backfills_section_a():
    client = FakeSheetsClient({
        6: ["Overhead", "2024-01-11", "Weimin Huang", "", 218.0],  # Section A, blank Invoice #
        100: ["", "", "", "", "", ""],  # empty Section E
    })
    rows = [
        _row("Inspection-240112", invoice_date=date(2024, 1, 11), paid_date=date(2024, 1, 11),
             amount=Decimal("218.00"), invoice_link="inv.pdf", payment_link="pconf.pdf"),
    ]

    new_rows, updated_rows, backfills = sync_overhead_register(
        client, "sheet1", "1 TRANSACTIONS", section_e_start_row=100, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    assert len(new_rows) == 1
    assert updated_rows == []
    assert backfills == [(rows[0], 6, "matched")]
    # Section E row written
    assert client._rows[100][0] == "Inspection-240112"
    # Section A backfilled with the real invoice number
    assert client._rows[6][3] == "Inspection-240112"
    # nothing else in that Section A row was disturbed
    assert client._rows[6][0] == "Overhead"
    assert client._rows[6][4] == 218.0


def test_sync_overhead_register_updates_existing_row_in_place_without_inserting():
    client = FakeSheetsClient({
        100: ["Inspection-240112", "01/11/2024", "", "", "inv.pdf", ""],  # payment not yet filed
        101: ["B · BY CATEGORY", "", "", "", "", ""],  # next section -- must not move
    })
    rows = [
        _row("Inspection-240112", invoice_date=date(2024, 1, 11), paid_date=date(2024, 1, 11),
             amount=Decimal("218.00"), invoice_link="inv.pdf", payment_link="pconf.pdf"),
    ]

    new_rows, updated_rows, backfills = sync_overhead_register(
        client, "sheet1", "1 TRANSACTIONS", section_e_start_row=100, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    assert new_rows == []
    assert updated_rows == [(100, rows[0])]
    assert client.inserts == []  # no insert needed for an in-place update
    assert client._rows[100][5] == "pconf.pdf"  # Payment Link now filled in
    assert client._rows[101][0] == "B · BY CATEGORY"  # untouched, didn't shift


def test_sync_overhead_register_dry_run_previews_backfill_without_writing():
    client = FakeSheetsClient({
        6: ["Overhead", "2024-01-11", "Weimin Huang", "", 218.0],
        100: ["", "", "", "", "", ""],
    })
    rows = [
        _row("Inspection-240112", invoice_date=date(2024, 1, 11), paid_date=date(2024, 1, 11),
             amount=Decimal("218.00")),
    ]

    new_rows, updated_rows, backfills = sync_overhead_register(
        client, "sheet1", "1 TRANSACTIONS", section_e_start_row=100, section_a_start_row=6,
        register_rows=rows, apply=False,
    )

    assert backfills == [(rows[0], 6, "matched")]  # preview shows the match
    assert client.updates == []  # but nothing was actually written
    assert client.inserts == []

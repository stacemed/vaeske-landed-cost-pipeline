from datetime import date
from decimal import Decimal

from landed_cost.models import Category
from landed_cost.sheets.freight_register import FreightRegisterRow
from landed_cost.sheets.freight_sync import (
    read_existing_d_register,
    sync_freight_register,
)
from landed_cost.sheets.section_a_backfill import SectionATransaction, match_section_a_row

from sheets_fakes import FakeSheetsClient


def _row(invoice_number, invoice_date=None, paid_date=None, freight_amount=None,
         bundling_amount=None, invoice_link="", payment_link="", prep_sheet_label="",
         prep_sheet_link="", flagged=False, flag_reason=""):
    return FreightRegisterRow(
        invoice_number=invoice_number, invoice_date=invoice_date, paid_date=paid_date,
        freight_amount=freight_amount, bundling_amount=bundling_amount,
        invoice_link=invoice_link, payment_link=payment_link,
        prep_sheet_label=prep_sheet_label, prep_sheet_link=prep_sheet_link,
        flagged=flagged, flag_reason=flag_reason,
    )


def test_read_existing_d_register_stops_at_blank_invoice_number():
    client = FakeSheetsClient({
        170: ["JG20241225E", "12/26/2024", "01/02/2025", 11842.35, 673.03, "inv.pdf", "inv.pdf",
              "", "", "2025-01 JAN", "prep.xlsx"],
        171: ["", "", "", "", "", "", "", "", "", "", ""],
    })

    existing, first_empty_row = read_existing_d_register(client, "sheet1", "1 TRANSACTIONS", start_row=170)

    assert existing == {"JG20241225E": 170}
    assert first_empty_row == 171


def test_sync_freight_register_inserts_new_row_and_backfills_section_a_on_combined_total():
    # Section A's Freight/bundling row holds the FULL wire total, not
    # Freight $ alone -- $876.88 + $113.16 = $990.04, matching real data.
    client = FakeSheetsClient({
        6: ["Freight / bundling / packaging", "2024-01-16", "FBA Bee", "", 990.04],
        170: ["", "", "", "", "", "", "", "", "", "", ""],
    })
    rows = [
        _row("JG20240108E", invoice_date=date(2024, 1, 12), paid_date=date(2024, 1, 16),
             freight_amount=Decimal("876.88"), bundling_amount=Decimal("113.16"),
             invoice_link="inv.pdf", payment_link="pconf.pdf", prep_sheet_label="2024-01 JAN"),
    ]

    new_rows, updated_rows, backfills = sync_freight_register(
        client, "sheet1", "1 TRANSACTIONS", section_d_start_row=170, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    assert len(new_rows) == 1
    assert updated_rows == []
    assert backfills == [(rows[0], 6, "matched")]
    assert client._rows[170][0] == "JG20240108E"
    assert client._rows[170][3] == 876.88
    assert client._rows[170][4] == 113.16
    assert client._rows[170][7] == ""  # Balance invoice always blank
    assert client._rows[170][8] == ""  # Balance payment 1 always blank
    assert client._rows[170][9] == "2024-01 JAN"
    # Section A backfilled, nothing else in that row disturbed
    assert client._rows[6][3] == "JG20240108E"
    assert client._rows[6][0] == "Freight / bundling / packaging"
    assert client._rows[6][4] == 990.04


def test_sync_freight_register_updates_existing_row_in_place_without_inserting():
    client = FakeSheetsClient({
        170: ["JG20240108E", "01/12/2024", "", "876.88", "113.16", "inv.pdf", "",
              "", "", "2024-01 JAN", ""],
        171: ["E · OVERHEAD INVOICE REGISTER", "", "", "", "", "", "", "", "", "", ""],
    })
    rows = [
        _row("JG20240108E", invoice_date=date(2024, 1, 12), paid_date=date(2024, 1, 16),
             freight_amount=Decimal("876.88"), bundling_amount=Decimal("113.16"),
             invoice_link="inv.pdf", payment_link="pconf.pdf", prep_sheet_label="2024-01 JAN"),
    ]

    new_rows, updated_rows, backfills = sync_freight_register(
        client, "sheet1", "1 TRANSACTIONS", section_d_start_row=170, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    assert new_rows == []
    assert updated_rows == [(170, rows[0])]
    assert client.inserts == []
    assert client._rows[170][6] == "pconf.pdf"  # Deposit payment now filled in
    assert client._rows[171][0] == "E · OVERHEAD INVOICE REGISTER"  # untouched, didn't shift


def test_sync_freight_register_sort_sorts_whole_section_d_by_paid_date():
    client = FakeSheetsClient({
        170: ["JG20240102E", "01/02/2024", "01/02/2024", 100.0, 10.0, "", "", "", "", "", ""],
        171: ["", "", "", "", "", "", "", "", "", "", ""],
    })
    rows = [
        _row("JG20240102E", invoice_date=date(2024, 1, 2), paid_date=date(2024, 1, 2),
             freight_amount=Decimal("100.00"), bundling_amount=Decimal("10.00")),
        _row("JG20240301E", invoice_date=date(2024, 3, 1), paid_date=date(2024, 3, 1),
             freight_amount=Decimal("50.00"), bundling_amount=Decimal("5.00")),
    ]

    sync_freight_register(
        client, "sheet1", "1 TRANSACTIONS", section_d_start_row=170, section_a_start_row=6,
        register_rows=rows, apply=True, sort=True,
    )

    # column index 2 = Paid date, num_columns=11 -- Section D's full A:K range.
    assert client.sorts == [(170, 171, 2, True, 11)]


def test_sync_freight_register_backfill_skipped_when_amounts_missing():
    client = FakeSheetsClient({
        6: ["Freight / bundling / packaging", "2024-01-16", "FBA Bee", "", 990.04],
        170: ["", "", "", "", "", "", "", "", "", "", ""],
    })
    rows = [
        _row("JG20240108E", invoice_date=date(2024, 1, 12), paid_date=date(2024, 1, 16),
             freight_amount=None, bundling_amount=None, flagged=True,
             flag_reason="could not extract"),
    ]

    new_rows, updated_rows, backfills = sync_freight_register(
        client, "sheet1", "1 TRANSACTIONS", section_d_start_row=170, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    assert backfills == [(rows[0], None, "skipped -- no amount/paid date to match on")]


def test_sync_freight_register_dry_run_previews_backfill_without_writing():
    client = FakeSheetsClient({
        6: ["Freight / bundling / packaging", "2024-01-16", "FBA Bee", "", 990.04],
        170: ["", "", "", "", "", "", "", "", "", "", ""],
    })
    rows = [
        _row("JG20240108E", invoice_date=date(2024, 1, 12), paid_date=date(2024, 1, 16),
             freight_amount=Decimal("876.88"), bundling_amount=Decimal("113.16")),
    ]

    new_rows, updated_rows, backfills = sync_freight_register(
        client, "sheet1", "1 TRANSACTIONS", section_d_start_row=170, section_a_start_row=6,
        register_rows=rows, apply=False,
    )

    assert backfills == [(rows[0], 6, "matched")]
    assert client.updates == []
    assert client.inserts == []

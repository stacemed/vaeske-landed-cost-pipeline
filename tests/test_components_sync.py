from datetime import date
from decimal import Decimal

from landed_cost.models import Category
from landed_cost.sheets.components_register import ComponentRegisterRow
from landed_cost.sheets.components_sync import (
    read_existing_c_register,
    sync_components_register,
)

from sheets_fakes import FakeSheetsClient


def _row(invoice_number, invoice_date=None, balance_paid_date=None, total_order_amount=None,
         deposit_invoice_link="", deposit_invoice_file_ids=None,
         deposit_payment_link="", deposit_payment_file_ids=None,
         balance_invoice_link="", balance_invoice_file_ids=None,
         balance_payment_links=("", "", "", ""),
         balance_payment_file_ids=((), (), (), ()),
         flagged=False, flag_reason=""):
    return ComponentRegisterRow(
        invoice_number=invoice_number, invoice_date=invoice_date, balance_paid_date=balance_paid_date,
        total_order_amount=total_order_amount,
        deposit_invoice_link=deposit_invoice_link, deposit_invoice_file_ids=deposit_invoice_file_ids or [],
        deposit_payment_link=deposit_payment_link, deposit_payment_file_ids=deposit_payment_file_ids or [],
        balance_invoice_link=balance_invoice_link, balance_invoice_file_ids=balance_invoice_file_ids or [],
        balance_payment_links=balance_payment_links, balance_payment_file_ids=balance_payment_file_ids,
        flagged=flagged, flag_reason=flag_reason,
    )


def test_read_existing_c_register_parses_invoice_number_row_total_and_adjustments():
    client = FakeSheetsClient({
        169: ["INV-25Q1SLV26QTINNERBOX-01", "01/15/2025", "03/06/2025", 15182.0, 0.0, "", "", "", "", "", "", ""],
        170: ["", "", "", "", "", "", "", "", "", "", "", ""],
    })

    existing, first_empty_row = read_existing_c_register(client, "sheet1", "1 TRANSACTIONS", start_row=169)

    assert existing == {"INV-25Q1SLV26QTINNERBOX-01": (169, Decimal("15182.0"), Decimal("0.0"))}
    assert first_empty_row == 170


def test_sync_components_register_inserts_a_genuinely_new_invoice_number():
    # Real design change (2026-10-20): components_register.py's own
    # build_components_register_rows already rules out the known
    # split/drift ambiguity before a row ever reaches here, so an
    # invoice number not yet in the sheet is now safely auto-inserted --
    # same as Freight/Overhead.
    client = FakeSheetsClient({
        169: ["INV-26Q1PKG", "09/24/2025", "09/24/2025", 3830.0, "", "", "", "", "", "", "", ""],
        170: ["", "", "", "", "", "", "", "", "", "", "", ""],
    })
    rows = [_row("INV-SOMETHING-ELSE", total_order_amount=Decimal("100.00"))]

    new_rows, updated_rows, backfills = sync_components_register(
        client, "sheet1", "1 TRANSACTIONS", section_c_start_row=169, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    assert new_rows == rows
    assert updated_rows == []
    assert client._rows[170][0] == "INV-SOMETHING-ELSE"
    assert client._rows[170][3] == 100.0


def test_sync_components_register_updates_existing_row_and_backfills_section_a():
    client = FakeSheetsClient({
        6: ["Components", "2025-09-24", "WHSM", "", 3830.0],
        169: ["INV-26Q1PKG", "", "", "", "", "", "", "", "", "", "", ""],
    })
    rows = [
        _row("INV-26Q1PKG", invoice_date=date(2025, 9, 24), balance_paid_date=date(2025, 9, 24),
             total_order_amount=Decimal("3830.00"),
             deposit_invoice_link="2025-09-24_WHSM_Comp_INV-26Q1PKG_INV-paid.pdf",
             deposit_payment_link="2025-09-24_WHSM_Comp_INV-26Q1PKG_pconf1.pdf"),
    ]

    new_rows, updated_rows, backfills = sync_components_register(
        client, "sheet1", "1 TRANSACTIONS", section_c_start_row=169, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    assert new_rows == []
    assert updated_rows == [(169, rows[0])]
    assert backfills == [(rows[0], 6, "matched")]
    assert client._rows[169][0] == "INV-26Q1PKG"
    assert client._rows[169][3] == 3830.0  # Total Order $ -- no existing adjustments to add
    assert client._rows[6][3] == "INV-26Q1PKG"  # Section A backfilled


def test_sync_components_register_adds_preserved_adjustments_to_the_extracted_total():
    # Real design choice: Invoice Adjustments is never computed here --
    # it's read from the sheet and added to the freshly extracted base
    # total, matching the column D header's own "incl. exchng fees".
    client = FakeSheetsClient({
        6: ["Components", "2025-07-10", "WHSM", "", 27123.46],
        169: ["INV-25Q4RPC26S-B01", "", "", "", 94.60, "", "", "", "", "", "", ""],
    })
    rows = [
        _row("INV-25Q4RPC26S-B01", balance_paid_date=date(2025, 7, 10), total_order_amount=Decimal("27028.86")),
    ]

    sync_components_register(
        client, "sheet1", "1 TRANSACTIONS", section_c_start_row=169, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    assert client._rows[169][3] == 27123.46  # 27028.86 + 94.60
    assert client._rows[169][4] == 94.6  # Invoice Adjustments preserved exactly


def test_sync_components_register_preserves_existing_total_when_extraction_fails():
    client = FakeSheetsClient({
        169: ["INV-25Q4RPC26S-B01", "07/10/2025", "", 27123.46, 94.60, "", "", "", "", "", "", ""],
    })
    rows = [
        _row("INV-25Q4RPC26S-B01", total_order_amount=None, flagged=True,
             flag_reason="could not extract Total Order $ -- check by hand"),
    ]

    sync_components_register(
        client, "sheet1", "1 TRANSACTIONS", section_c_start_row=169, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    assert client._rows[169][3] == 27123.46  # untouched, not blanked
    assert client._rows[169][4] == 94.6  # untouched


def test_sync_components_register_cross_links_invoice_number_and_section_a_cell():
    client = FakeSheetsClient({
        6: ["Components", "2025-09-24", "WHSM", "", 3830.0],
        169: ["INV-26Q1PKG", "", "", "", "", "", "", "", "", "", "", ""],
    })
    rows = [
        _row("INV-26Q1PKG", balance_paid_date=date(2025, 9, 24), total_order_amount=Decimal("3830.00")),
    ]

    sync_components_register(
        client, "sheet1", "1 TRANSACTIONS", section_c_start_row=169, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    c_write = next(
        values[0][0] for a1_range, values in client.updates
        if a1_range == "'1 TRANSACTIONS'!A169:M169"
    )
    assert c_write == '=HYPERLINK("#gid=12345&range=D6", "INV-26Q1PKG")'
    a_write = [
        values[0][0] for a1_range, values in client.updates if a1_range == "'1 TRANSACTIONS'!D6"
    ][-1]
    assert a_write == '=HYPERLINK("#gid=12345&range=A169", "INV-26Q1PKG")'


def test_sync_components_register_does_not_reflag_an_invoice_matched_in_a_previous_run():
    client = FakeSheetsClient({
        6: ["Components", "2025-09-24", "WHSM", "INV-26Q1PKG", 3830.0],
        169: ["INV-26Q1PKG", "", "", 3830.0, "", "", "", "", "", "", "", ""],
    })
    rows = [
        _row("INV-26Q1PKG", balance_paid_date=date(2025, 9, 24), total_order_amount=Decimal("3830.00")),
    ]

    _new_rows, _updated_rows, backfills = sync_components_register(
        client, "sheet1", "1 TRANSACTIONS", section_c_start_row=169, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    assert client._rows[169][12] == ""
    assert backfills[0][2] == "already linked in Section A from a previous run -- nothing to do"
    row_flags, num_columns = client.row_flag_calls[-1]
    assert num_columns == 13
    assert (169, False) in row_flags


def test_sync_components_register_does_not_touch_a_link_on_a_different_category_row():
    client = FakeSheetsClient({
        6: ["Components", "2025-09-24", "WHSM", "", 3830.0],
        7: ["Freight / bundling / packaging", "2024-01-16", "FBA Bee", "JG20240108E", 990.04],
        169: ["INV-26Q1PKG", "", "", "", "", "", "", "", "", "", "", ""],
    })
    rows = [
        _row("INV-26Q1PKG", balance_paid_date=date(2025, 9, 24), total_order_amount=Decimal("3830.00")),
    ]

    sync_components_register(
        client, "sheet1", "1 TRANSACTIONS", section_c_start_row=169, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    assert client._rows[7][3] == "JG20240108E"
    assert not any(a1_range == "'1 TRANSACTIONS'!D7" for a1_range, _values in client.updates)


def test_sync_components_register_writes_flag_reason_and_highlights_flagged_rows():
    client = FakeSheetsClient({
        169: ["INV-26Q1PKG", "", "", "", "", "", "", "", "", "", "", ""],
    })
    rows = [
        _row("INV-26Q1PKG", total_order_amount=None, flagged=True,
             flag_reason="could not extract Total Order $ -- check by hand"),
    ]

    sync_components_register(
        client, "sheet1", "1 TRANSACTIONS", section_c_start_row=169, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    assert client._rows[169][12] == "could not extract Total Order $ -- check by hand"
    row_flags, num_columns = client.row_flag_calls[-1]
    assert num_columns == 13
    assert (169, True) in row_flags


def test_sync_components_register_writes_flag_reason_header():
    client = FakeSheetsClient({
        169: ["INV-26Q1PKG", "", "", "", "", "", "", "", "", "", "", ""],
    })
    rows = [_row("INV-26Q1PKG")]

    sync_components_register(
        client, "sheet1", "1 TRANSACTIONS", section_c_start_row=169, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    assert client._rows[168][12] == "Flag Reason"


def test_sync_components_register_writes_smart_chips_for_all_seven_file_columns():
    client = FakeSheetsClient({
        169: ["INV-26Q1RCS", "", "", "", "", "", "", "", "", "", "", ""],
    })
    rows = [
        _row(
            "INV-26Q1RCS",
            deposit_invoice_file_ids=["dep-inv-id"],
            deposit_payment_file_ids=["dep-pay-id"],
            balance_invoice_file_ids=["bal-inv-id"],
            balance_payment_file_ids=(["bal-pay-1"], ["bal-pay-2"], ["bal-pay-3"], ["bal-pay-4"]),
        ),
    ]

    sync_components_register(
        client, "sheet1", "1 TRANSACTIONS", section_c_start_row=169, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    cells = client.chip_writes[-1]
    assert (169, 5, ["dep-inv-id"]) in cells
    assert (169, 6, ["dep-pay-id"]) in cells
    assert (169, 7, ["bal-inv-id"]) in cells
    assert (169, 8, ["bal-pay-1"]) in cells
    assert (169, 9, ["bal-pay-2"]) in cells
    assert (169, 10, ["bal-pay-3"]) in cells
    assert (169, 11, ["bal-pay-4"]) in cells


def test_sync_components_register_dry_run_previews_backfill_without_writing():
    client = FakeSheetsClient({
        6: ["Components", "2025-09-24", "WHSM", "", 3830.0],
        169: ["INV-26Q1PKG", "", "", "", "", "", "", "", "", "", "", ""],
    })
    rows = [
        _row("INV-26Q1PKG", balance_paid_date=date(2025, 9, 24), total_order_amount=Decimal("3830.00")),
    ]

    new_rows, updated_rows, backfills = sync_components_register(
        client, "sheet1", "1 TRANSACTIONS", section_c_start_row=169, section_a_start_row=6,
        register_rows=rows, apply=False,
    )

    assert new_rows == []
    assert updated_rows == [(169, rows[0])]
    assert backfills == [(rows[0], 6, "matched")]
    assert client.updates == []
    assert client.chip_writes == []

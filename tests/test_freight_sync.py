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
         bundling_amount=None, invoice_link="", payment_link="", invoice_file_ids=None,
         payment_file_ids=None, prep_sheet_label="", prep_sheet_link="", flagged=False,
         flag_reason=""):
    return FreightRegisterRow(
        invoice_number=invoice_number, invoice_date=invoice_date, paid_date=paid_date,
        freight_amount=freight_amount, bundling_amount=bundling_amount,
        invoice_link=invoice_link, payment_link=payment_link,
        invoice_file_ids=invoice_file_ids or [], payment_file_ids=payment_file_ids or [],
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


def test_sync_freight_register_matches_combined_wire_and_writes_one_joined_invoice_number():
    # Real data (2026-09-22): two region-suffixed invoices paid in ONE
    # wire -- $2,321.58 (JG20240115E-CA) + $6,517.08 (JG20240115E-US) =
    # $8,838.66, matching one real Section A row exactly. Neither
    # invoice's own amount matches Section A by itself.
    client = FakeSheetsClient({
        6: ["Freight / bundling / packaging", "2024-01-16", "FBA Bee", "", 8838.66],
        170: ["", "", "", "", "", "", "", "", "", "", ""],
    })
    rows = [
        _row("JG20240115E-CA", invoice_date=date(2024, 1, 15), paid_date=date(2024, 1, 16),
             freight_amount=Decimal("2044.32"), bundling_amount=Decimal("277.26")),
        _row("JG20240115E-US", invoice_date=date(2024, 1, 15), paid_date=date(2024, 1, 16),
             freight_amount=Decimal("5659.54"), bundling_amount=Decimal("857.54")),
    ]

    new_rows, updated_rows, backfills = sync_freight_register(
        client, "sheet1", "1 TRANSACTIONS", section_d_start_row=170, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    assert [b[1] for b in backfills] == [6, 6]
    assert all("combined wire" in b[2] for b in backfills)
    # ONE write, both invoice numbers comma-joined -- not a last-write-
    # wins overwrite from two separate single-cell writes.
    assert client._rows[6][3] == "JG20240115E-CA, JG20240115E-US"
    assert client._rows[6][0] == "Freight / bundling / packaging"  # untouched
    assert client._rows[6][4] == 8838.66  # untouched


def test_sync_freight_register_excludes_an_already_matched_sibling_from_combined_total():
    # Real bug (2026-09-24): JG20240108E is paid the same calendar day
    # (2024-01-16) as the unrelated JG20240115E-CA/-US combined wire, but
    # via its own separate, dedicated Section A row. Folding its amount
    # into the OTHER pair's combined-total attempt inflated the sum past
    # what any real Section A row held, leaving all three unmatched.
    client = FakeSheetsClient({
        6: ["Freight / bundling / packaging", "2024-01-16", "FBA Bee", "", 990.04],
        7: ["Freight / bundling / packaging", "2024-01-16", "FBA Bee", "", 8838.66],
        170: ["", "", "", "", "", "", "", "", "", "", ""],
    })
    rows = [
        _row("JG20240108E", invoice_date=date(2024, 1, 12), paid_date=date(2024, 1, 16),
             freight_amount=Decimal("876.88"), bundling_amount=Decimal("113.16")),
        _row("JG20240115E-CA", invoice_date=date(2024, 1, 15), paid_date=date(2024, 1, 16),
             freight_amount=Decimal("2044.32"), bundling_amount=Decimal("277.26")),
        _row("JG20240115E-US", invoice_date=date(2024, 1, 15), paid_date=date(2024, 1, 16),
             freight_amount=Decimal("5659.54"), bundling_amount=Decimal("857.54")),
    ]

    new_rows, updated_rows, backfills = sync_freight_register(
        client, "sheet1", "1 TRANSACTIONS", section_d_start_row=170, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    by_number = {row.invoice_number: match_row for row, match_row, _status in backfills}
    assert by_number["JG20240108E"] == 6
    assert by_number["JG20240115E-CA"] == 7
    assert by_number["JG20240115E-US"] == 7
    assert client._rows[6][3] == "JG20240108E"
    assert client._rows[7][3] == "JG20240115E-CA, JG20240115E-US"


def test_sync_freight_register_does_not_guess_when_no_combined_match_exists():
    # Two same-day invoices whose combined total matches nothing in
    # Section A -- must stay unmatched, not guess at a partial/wrong sum.
    client = FakeSheetsClient({
        6: ["Freight / bundling / packaging", "2024-01-16", "FBA Bee", "", 12345.67],
        170: ["", "", "", "", "", "", "", "", "", "", ""],
    })
    rows = [
        _row("JG20240115E-CA", invoice_date=date(2024, 1, 15), paid_date=date(2024, 1, 16),
             freight_amount=Decimal("2044.32"), bundling_amount=Decimal("277.26")),
        _row("JG20240115E-US", invoice_date=date(2024, 1, 15), paid_date=date(2024, 1, 16),
             freight_amount=Decimal("5659.54"), bundling_amount=Decimal("857.54")),
    ]

    _, _, backfills = sync_freight_register(
        client, "sheet1", "1 TRANSACTIONS", section_d_start_row=170, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    assert [b[1] for b in backfills] == [None, None]
    assert client._rows[6][3] == ""


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

    # column index 2 = Paid date, num_columns=12 -- Section D's full A:L range.
    assert client.sorts == [(170, 171, 2, True, 12)]


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


def test_sync_freight_register_cross_links_invoice_number_and_section_a_cell():
    client = FakeSheetsClient({
        6: ["Freight / bundling / packaging", "2024-01-16", "FBA Bee", "", 990.04],
        170: ["", "", "", "", "", "", "", "", "", "", "", ""],
    })
    rows = [
        _row("JG20240108E", invoice_date=date(2024, 1, 12), paid_date=date(2024, 1, 16),
             freight_amount=Decimal("876.88"), bundling_amount=Decimal("113.16")),
    ]

    sync_freight_register(
        client, "sheet1", "1 TRANSACTIONS", section_d_start_row=170, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    # Column A of the register row is a HYPERLINK formula targeting its
    # matched Section A row -- not just plain text that happens to
    # evaluate to the same string (client._rows would look the same
    # either way, since the fake resolves a HYPERLINK cell to its label
    # on read, matching the real API's UNFORMATTED_VALUE behavior).
    d_write = next(
        values[0][0] for a1_range, values in client.updates
        if a1_range == "'1 TRANSACTIONS'!A170:L170"
    )
    assert d_write == '=HYPERLINK("#gid=12345&range=D6", "JG20240108E")'

    # And Section A's own Invoice # cell links back to the register row.
    a_write = [
        values[0][0] for a1_range, values in client.updates if a1_range == "'1 TRANSACTIONS'!D6"
    ][-1]
    assert a_write == '=HYPERLINK("#gid=12345&range=A170", "JG20240108E")'


def test_sync_freight_register_links_column_a_for_an_invoice_matched_in_a_previous_run():
    # Real bug (2026-09-28): match_by_invoice only finds a match among
    # Section A rows THIS run's own matching pass can still see -- once
    # matched, Section A's cell is no longer blank, so a LATER run
    # (where the row is merely re-verified, not newly matched) got
    # match_row=None and fell back to plain text forever after the
    # first successful match. Column A never got its link.
    client = FakeSheetsClient({
        6: ["Freight / bundling / packaging", "2024-01-16", "FBA Bee", "JG20240108E", 990.04],
        170: ["JG20240108E", "01/12/2024", "01/16/2024", 876.88, 113.16, "", "", "", "", "", "", ""],
    })
    rows = [
        _row("JG20240108E", invoice_date=date(2024, 1, 12), paid_date=date(2024, 1, 16),
             freight_amount=Decimal("876.88"), bundling_amount=Decimal("113.16")),
    ]

    sync_freight_register(
        client, "sheet1", "1 TRANSACTIONS", section_d_start_row=170, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    d_write = [
        values[0][0] for a1_range, values in client.updates
        if a1_range == "'1 TRANSACTIONS'!A170:L170"
    ][-1]
    assert d_write == '=HYPERLINK("#gid=12345&range=D6", "JG20240108E")'


def test_sync_freight_register_links_column_a_for_each_invoice_in_an_existing_combined_match():
    # Same bug, combined-wire case: all three invoices already share
    # Section A row 6 (comma-joined) from an earlier run -- each of
    # their own register rows must still link to it on a re-verify run.
    client = FakeSheetsClient({
        6: ["Freight / bundling / packaging", "2024-06-21", "FBA Bee",
            "JG20240531E, JG20240605E, JG20240614E", 12000.00],
        170: ["JG20240531E", "05/31/2024", "06/21/2024", 182.0, 140.0, "", "", "", "", "", "", ""],
        171: ["JG20240605E", "06/05/2024", "06/21/2024", 1144.36, 68.20, "", "", "", "", "", "", ""],
        172: ["JG20240614E", "06/14/2024", "06/21/2024", 10395.32, 669.96, "", "", "", "", "", "", ""],
    })
    rows = [
        _row("JG20240531E", invoice_date=date(2024, 5, 31), paid_date=date(2024, 6, 21),
             freight_amount=Decimal("182.00"), bundling_amount=Decimal("140.00")),
        _row("JG20240605E", invoice_date=date(2024, 6, 5), paid_date=date(2024, 6, 21),
             freight_amount=Decimal("1144.36"), bundling_amount=Decimal("68.20")),
        _row("JG20240614E", invoice_date=date(2024, 6, 14), paid_date=date(2024, 6, 21),
             freight_amount=Decimal("10395.32"), bundling_amount=Decimal("669.96")),
    ]

    sync_freight_register(
        client, "sheet1", "1 TRANSACTIONS", section_d_start_row=170, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    for row_number, invoice_number in [(170, "JG20240531E"), (171, "JG20240605E"), (172, "JG20240614E")]:
        write = [
            values[0][0] for a1_range, values in client.updates
            if a1_range == f"'1 TRANSACTIONS'!A{row_number}:L{row_number}"
        ][-1]
        assert write == f'=HYPERLINK("#gid=12345&range=D6", "{invoice_number}")'


def test_sync_freight_register_refreshes_a_stale_section_a_link_when_a_row_shifts():
    # Section A row 6 is ALREADY linked (from a previous run) to
    # JG20240301E, currently sitting at Section D row 170, via a link
    # that points at row 170. This run inserts a brand-new invoice
    # ahead of it, which (via the insert-at-last-row trick) pushes
    # JG20240301E down to row 171 -- the stale link must be rewritten
    # to point at 171, or clicking it would land on the wrong invoice.
    client = FakeSheetsClient({
        # Real reads never return formula source (see _evaluate_cell) --
        # a HYPERLINK cell written by an earlier run reads back as just
        # its label, "JG20240301E", exactly like plain text would.
        6: ["Freight / bundling / packaging", "2024-03-01", "FBA Bee", "JG20240301E", 500.00],
        170: ["JG20240301E", "02/25/2024", "03/01/2024", 450.0, 50.0, "", "", "", "", "", "", ""],
    })
    rows = [
        _row("JG20240102E", invoice_date=date(2024, 1, 2), paid_date=date(2024, 1, 2),
             freight_amount=Decimal("100.00"), bundling_amount=Decimal("10.00")),
        _row("JG20240301E", invoice_date=date(2024, 2, 25), paid_date=date(2024, 3, 1),
             freight_amount=Decimal("450.00"), bundling_amount=Decimal("50.00")),
    ]

    sync_freight_register(
        client, "sheet1", "1 TRANSACTIONS", section_d_start_row=170, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    assert client._rows[170][0] == "JG20240102E"
    assert client._rows[171][0] == "JG20240301E"
    d6_write = [
        values[0][0] for a1_range, values in client.updates if a1_range == "'1 TRANSACTIONS'!D6"
    ][-1]
    assert d6_write == '=HYPERLINK("#gid=12345&range=A171", "JG20240301E")'


def test_sync_freight_register_does_not_touch_a_link_on_a_different_category_row():
    # Section A row 7 is an OVERHEAD row (not Freight), already linked
    # by overhead_sync.py to an Overhead invoice. A Freight sync run
    # must never "refresh" it -- it can't find that invoice number in
    # ITS OWN register (Section D), so without the category filter it
    # would fall back to overwriting the existing link with plain text,
    # silently breaking a cross-link a completely different script
    # wrote correctly.
    client = FakeSheetsClient({
        6: ["Freight / bundling / packaging", "2024-01-16", "FBA Bee", "", 990.04],
        7: ["Overhead", "2024-01-11", "Weimin Huang", "Inspection-240112", 218.0],
        170: ["", "", "", "", "", "", "", "", "", "", "", ""],
    })
    rows = [
        _row("JG20240108E", invoice_date=date(2024, 1, 12), paid_date=date(2024, 1, 16),
             freight_amount=Decimal("876.88"), bundling_amount=Decimal("113.16")),
    ]

    sync_freight_register(
        client, "sheet1", "1 TRANSACTIONS", section_d_start_row=170, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    assert client._rows[7][3] == "Inspection-240112"
    assert not any(
        a1_range == "'1 TRANSACTIONS'!D7" for a1_range, _values in client.updates
    )


def test_sync_freight_register_writes_flag_reason_and_highlights_flagged_rows():
    client = FakeSheetsClient({
        170: ["", "", "", "", "", "", "", "", "", "", "", ""],
    })
    rows = [
        _row("JG20240108E", invoice_date=date(2024, 1, 12), paid_date=date(2024, 1, 16),
             freight_amount=None, bundling_amount=None, flagged=True,
             flag_reason="could not extract Freight $/Bundling $ -- fill in by hand"),
        # No paid_date -- backfill is "skipped", not a problem, so this
        # clean row's Flag Reason must stay blank.
        _row("JG20240301E", invoice_date=date(2024, 3, 1), paid_date=None,
             freight_amount=Decimal("50.00"), bundling_amount=Decimal("5.00")),
    ]

    sync_freight_register(
        client, "sheet1", "1 TRANSACTIONS", section_d_start_row=170, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    assert client._rows[170][11] == "could not extract Freight $/Bundling $ -- fill in by hand"
    assert client._rows[171][11] == ""
    row_flags, num_columns = client.row_flag_calls[-1]
    assert num_columns == 12
    assert (170, True) in row_flags
    assert (171, False) in row_flags


def test_sync_freight_register_does_not_reflag_an_invoice_matched_in_a_previous_run():
    # Section A row 6 was already matched to JG20240108E by an earlier
    # run. match_section_a_row's blank-Invoice#-only candidate filter
    # can no longer see it, which on its own looks identical to "no
    # matching Section A transaction found" -- without review_reason's
    # already-linked check, this would wrongly re-flag a perfectly
    # fine, already-matched row on every future run.
    client = FakeSheetsClient({
        6: ["Freight / bundling / packaging", "2024-01-16", "FBA Bee", "JG20240108E", 990.04],
        170: ["JG20240108E", "01/12/2024", "01/16/2024", 876.88, 113.16, "", "", "", "", "", "", ""],
    })
    rows = [
        _row("JG20240108E", invoice_date=date(2024, 1, 12), paid_date=date(2024, 1, 16),
             freight_amount=Decimal("876.88"), bundling_amount=Decimal("113.16")),
    ]

    _new_rows, _updated_rows, backfills = sync_freight_register(
        client, "sheet1", "1 TRANSACTIONS", section_d_start_row=170, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    assert client._rows[170][11] == ""
    row_flags, _num_columns = client.row_flag_calls[-1]
    assert (170, False) in row_flags
    # Real UX bug (2026-10-02): match_section_a_row's own status text
    # for this case ("no matching Section A transaction found (or it
    # already has an Invoice #)") is accurate but reads as an alarming
    # failure when printed -- a caller (the CLI script) needs a status
    # that's unambiguous on its own.
    assert backfills[0][2] == "already linked in Section A from a previous run -- nothing to do"


def test_sync_freight_register_writes_smart_chips_for_files_with_known_ids():
    client = FakeSheetsClient({
        170: ["", "", "", "", "", "", "", "", "", "", "", ""],
    })
    rows = [
        _row("JG20240108E", invoice_date=date(2024, 1, 12), paid_date=date(2024, 1, 16),
             freight_amount=Decimal("876.88"), bundling_amount=Decimal("113.16"),
             invoice_link="inv.pdf", payment_link="pconf.pdf",
             invoice_file_ids=["inv-drive-id"], payment_file_ids=["pconf-drive-id"]),
    ]

    sync_freight_register(
        client, "sheet1", "1 TRANSACTIONS", section_d_start_row=170, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    cells = client.chip_writes[-1]
    assert (170, 5, ["inv-drive-id"]) in cells  # F = Invoice Link
    assert (170, 6, ["pconf-drive-id"]) in cells  # G = Payment Link


def test_sync_freight_register_skips_chip_write_when_no_file_id_known():
    # No invoice_file_ids/payment_file_ids given -- the bulk row write
    # already put invoice_link/payment_link's plain filename text in
    # place, and there is no id to chip it with, so it must be left
    # exactly as the bulk write wrote it, not blanked.
    client = FakeSheetsClient({
        170: ["", "", "", "", "", "", "", "", "", "", "", ""],
    })
    rows = [
        _row("JG20240108E", invoice_date=date(2024, 1, 12), paid_date=date(2024, 1, 16),
             freight_amount=Decimal("876.88"), bundling_amount=Decimal("113.16"),
             invoice_link="inv.pdf", payment_link="pconf.pdf"),
    ]

    sync_freight_register(
        client, "sheet1", "1 TRANSACTIONS", section_d_start_row=170, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    assert client.chip_writes == [[]]
    assert client._rows[170][5] == "inv.pdf"
    assert client._rows[170][6] == "pconf.pdf"


def test_sync_freight_register_writes_flag_reason_header():
    client = FakeSheetsClient({
        170: ["", "", "", "", "", "", "", "", "", "", "", ""],
    })
    rows = [
        _row("JG20240108E", invoice_date=date(2024, 1, 12), paid_date=date(2024, 1, 16),
             freight_amount=Decimal("876.88"), bundling_amount=Decimal("113.16")),
    ]

    sync_freight_register(
        client, "sheet1", "1 TRANSACTIONS", section_d_start_row=170, section_a_start_row=6,
        register_rows=rows, apply=True,
    )

    assert client._rows[169][11] == "Flag Reason"


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

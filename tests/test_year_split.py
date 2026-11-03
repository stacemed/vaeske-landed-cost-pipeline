from datetime import date

from landed_cost.sheets.year_split import (
    apply_year_split,
    effective_year,
    group_into_contiguous_ranges,
    plan_year_split,
    read_register_dates,
    read_section_a_dates,
    rows_to_delete,
)

from sheets_fakes import FakeSheetsClient


def _layered_fixture() -> FakeSheetsClient:
    # Mirrors the real workbook's layout: Section A, then C, then D,
    # then E, stacked in the same tab -- a small multi-year slice of
    # each.
    return FakeSheetsClient({
        5: ["Category", "Date", "Payee"],
        6: ["Components", "2024-01-06", "WHSM"],
        7: ["Overhead", "2025-01-10", "Weimin Huang"],
        8: ["", "", ""],  # Section A ends here
        10: ["C · COMPONENT INVOICE REGISTER", "", ""],
        11: ["Invoice #", "Invoice date", "Balance paid date"],
        12: ["INV-24Q4SLV", "2024-10-12", "2024-10-12"],
        13: ["INV-26Q1PKG", "2025-09-24", "2025-09-24"],
        14: ["TOTAL COMPONENTS PAID 2025", "", ""],
        16: ["D · FREIGHT INVOICE REGISTER", "", ""],
        17: ["Invoice #", "Invoice date", "Paid date"],
        18: ["JG20240108E", "2024-01-12", "2024-01-16"],
        19: ["JG20260703E", "2026-07-09", "2026-07-10"],
        20: ["TOTAL FREIGHT PAID 2025", "", ""],
        22: ["E · OVERHEAD INVOICE REGISTER", "", ""],
        23: ["Invoice #", "Invoice date", "Paid date"],
        24: ["Inspection-240102", "2024-01-02", "2024-01-03"],
        25: ["Wise 1411132629", "2026-02-10", "2026-02-10"],
        26: ["TOTAL OVERHEAD PAID 2025", "", ""],
    })


def test_effective_year_uses_primary_date_first():
    assert effective_year("INV-1", date(2025, 3, 6), date(2025, 1, 15)) == 2025


def test_effective_year_falls_back_when_primary_is_blank():
    assert effective_year("INV-1", None, date(2024, 10, 12)) == 2024


def test_effective_year_none_when_nothing_resolves():
    assert effective_year("INV-1", None, None) is None


def test_effective_year_force_override_wins_over_any_date():
    # Real case (2026-11-03): these 4 Components rows have no date in
    # either column at all -- confirmed bucketed as 2024 by the project
    # owner's own call, not inferred from a date that doesn't exist.
    assert effective_year("INV-US3rdR24-03", None, None) == 2024
    assert effective_year("INV-US3rdR24-03", date(2025, 1, 1), date(2025, 1, 1)) == 2024


def test_rows_to_delete_template_mode_deletes_everything():
    dated_rows = [(169, 2024), (170, 2025), (171, None)]
    assert rows_to_delete(dated_rows, keep_year=None) == [169, 170, 171]


def test_rows_to_delete_keeps_only_the_matching_year():
    dated_rows = [(169, 2024), (170, 2025), (171, 2024), (172, 2026)]
    assert rows_to_delete(dated_rows, keep_year=2024) == [170, 172]


def test_rows_to_delete_drops_an_unresolvable_row_from_every_year():
    # A row with no resolvable year can't safely go in any single
    # year's file -- it's deleted regardless of which year is kept,
    # rather than ending up in whichever year happens to run first.
    dated_rows = [(169, 2024), (170, None)]
    assert rows_to_delete(dated_rows, keep_year=2024) == [170]
    assert rows_to_delete(dated_rows, keep_year=2025) == [169, 170]


def test_group_into_contiguous_ranges_merges_adjacent_rows():
    assert group_into_contiguous_ranges([176, 177, 178, 180, 181, 190]) == [
        (176, 3),
        (180, 2),
        (190, 1),
    ]


def test_group_into_contiguous_ranges_handles_unsorted_input():
    assert group_into_contiguous_ranges([181, 176, 180, 178, 177]) == [(176, 3), (180, 2)]


def test_group_into_contiguous_ranges_empty_list():
    assert group_into_contiguous_ranges([]) == []


def test_read_section_a_dates_stops_at_first_blank_date():
    client = FakeSheetsClient({
        6: ["Overhead", "2024-01-02", "Weimin Huang"],
        7: ["Components", "2024-01-08", "Shenzhen Minzhi BYJ Trading Co"],
        8: ["", "", ""],
    })

    rows = read_section_a_dates(client, "sheet1", "1 TRANSACTIONS", start_row=6)

    assert rows == [(6, date(2024, 1, 2)), (7, date(2024, 1, 8))]


def test_read_register_dates_resolves_primary_then_fallback_per_row():
    # Section C shape: Invoice #(A) Invoice date(B) Balance paid date(C).
    client = FakeSheetsClient({
        169: ["INV-25Q1SLV26QTINNERBOX-01", "2025-01-15", "2025-03-06"],
        170: ["INV-26Q1PKG", "2025-09-24", ""],  # no balance paid date -- falls back to invoice date
        171: ["TOTAL COMPONENTS PAID 2025", "", ""],
    })

    rows = read_register_dates(
        client, "sheet1", "1 TRANSACTIONS", start_row=169,
        primary_date_col=2, fallback_date_col=1,
    )

    assert rows == [(169, 2025), (170, 2025)]


def test_read_register_dates_applies_the_force_year_override():
    client = FakeSheetsClient({
        183: ["INV-US3rdR24-03", "", ""],
        184: ["TOTAL COMPONENTS PAID 2025", "", ""],
    })

    rows = read_register_dates(
        client, "sheet1", "1 TRANSACTIONS", start_row=183,
        primary_date_col=2, fallback_date_col=1,
    )

    assert rows == [(183, 2024)]


def test_plan_year_split_finds_every_section_and_classifies_each_row():
    client = _layered_fixture()

    plan = plan_year_split(client, "sheet1", "1 TRANSACTIONS", keep_year=2024)

    assert plan["A"] == (2, [(7, 1)])  # row 7 (2025 Overhead txn) deleted, row 6 (2024) kept
    assert plan["C"] == (2, [(13, 1)])  # INV-26Q1PKG (2025) deleted, INV-24Q4SLV (2024) kept
    assert plan["D"] == (2, [(19, 1)])  # JG20260703E (2026) deleted, JG20240108E (2024) kept
    assert plan["E"] == (2, [(25, 1)])  # Wise ...629 (2026) deleted, Inspection-240102 (2024) kept


def test_plan_year_split_template_mode_deletes_every_data_row():
    client = _layered_fixture()

    plan = plan_year_split(client, "sheet1", "1 TRANSACTIONS", keep_year=None)

    assert plan["A"] == (2, [(6, 2)])
    assert plan["C"] == (2, [(12, 2)])
    assert plan["D"] == (2, [(18, 2)])
    assert plan["E"] == (2, [(24, 2)])


def test_apply_year_split_deletes_bottom_to_top_leaving_only_the_kept_year():
    client = _layered_fixture()
    plan = plan_year_split(client, "sheet1", "1 TRANSACTIONS", keep_year=2024)

    total = apply_year_split(client, "sheet1", sheet_id=12345, plan=plan)

    assert total == 4
    # Every section's remaining data row is the 2024 one, and nothing
    # got corrupted by an earlier section's delete shifting a later
    # section's row numbers out from under it -- each section (and the
    # next section's own header) compacts up as its 2025/2026 row is
    # removed, cascading cleanly through C, D and E.
    assert client._rows[6][0] == "Components"  # Section A's 2024 row, untouched
    assert client._rows[11][0] == "INV-24Q4SLV"
    assert client._rows[12][0] == "TOTAL COMPONENTS PAID 2025"
    assert client._rows[16][0] == "JG20240108E"
    assert client._rows[17][0] == "TOTAL FREIGHT PAID 2025"
    assert client._rows[21][0] == "Inspection-240102"
    assert client._rows[22][0] == "TOTAL OVERHEAD PAID 2025"


def test_apply_year_split_template_mode_strips_every_section_to_just_its_header():
    client = _layered_fixture()
    plan = plan_year_split(client, "sheet1", "1 TRANSACTIONS", keep_year=None)

    total = apply_year_split(client, "sheet1", sheet_id=12345, plan=plan)

    assert total == 8
    assert client._rows[6][0] == ""  # Section A now blank where data used to be
    assert client._rows[10][0] == "TOTAL COMPONENTS PAID 2025"
    assert client._rows[14][0] == "TOTAL FREIGHT PAID 2025"
    assert client._rows[18][0] == "TOTAL OVERHEAD PAID 2025"

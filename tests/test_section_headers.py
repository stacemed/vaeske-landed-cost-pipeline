import pytest

from landed_cost.sheets.section_headers import (
    SECTION_E_TITLE_PATTERN,
    find_section_data_start_row,
    verify_column_header,
)

from sheets_fakes import FakeSheetsClient


def test_find_section_data_start_row_locates_section_e_by_its_own_title():
    client = FakeSheetsClient({
        98: ["E · OVERHEAD INVOICE REGISTER"],
        99: ["Invoice #"],
        100: ["Wise 1370922330"],
    })

    row = find_section_data_start_row(client, "sheet1", "1 TRANSACTIONS", SECTION_E_TITLE_PATTERN)

    assert row == 100


def test_find_section_data_start_row_finds_it_wherever_it_has_drifted_to():
    # The whole point: the title can be anywhere -- rows above it having
    # grown since the workbook was last inspected changes nothing.
    client = FakeSheetsClient({
        152: ["E · OVERHEAD INVOICE REGISTER"],
        153: ["Invoice #"],
        154: ["Wise 1370922330"],
    })

    row = find_section_data_start_row(client, "sheet1", "1 TRANSACTIONS", SECTION_E_TITLE_PATTERN)

    assert row == 154


def test_find_section_data_start_row_raises_rather_than_guessing():
    client = FakeSheetsClient({
        6: ["Overhead"],
        7: ["Freight / bundling / packaging"],
    })

    with pytest.raises(ValueError, match="could not find"):
        find_section_data_start_row(client, "sheet1", "1 TRANSACTIONS", SECTION_E_TITLE_PATTERN)


def test_verify_column_header_passes_when_header_matches():
    client = FakeSheetsClient({99: ["Invoice #"]})

    verify_column_header(client, "sheet1", "1 TRANSACTIONS", 99, "A", "Invoice #")  # no raise


def test_verify_column_header_raises_when_header_does_not_match():
    # This is the check that would have caught the real 2026-09-17
    # incident: row 99 there actually held Section A data, not a
    # Section E header, and this refuses to proceed instead of writing.
    client = FakeSheetsClient({99: ["Overhead"]})

    with pytest.raises(ValueError, match="expected A99"):
        verify_column_header(client, "sheet1", "1 TRANSACTIONS", 99, "A", "Invoice #")


def test_verify_column_header_raises_on_blank_cell():
    client = FakeSheetsClient({})

    with pytest.raises(ValueError, match="expected A99"):
        verify_column_header(client, "sheet1", "1 TRANSACTIONS", 99, "A", "Invoice #")

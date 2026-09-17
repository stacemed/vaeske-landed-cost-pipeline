from datetime import date
from decimal import Decimal

from landed_cost.models import Category
from landed_cost.sheets.qbo import (
    QboTransaction,
    build_section_a_row,
    classify_category,
    clean_payee,
    extract_reference,
    parse_qbo_quickreport_csv,
    plan_section_a_sync,
)

# Trimmed, anonymized shape of a real QBO "Account QuickReport" export --
# junk header rows, a distribution-account marker, a Beginning Balance
# row, real transactions, then footer rows with no transaction date.
SAMPLE_QBO_CSV = """Some Company LLC,,,,,,,,,,
Account QuickReport,,,,,,,,,,
"January-December, 2024",,,,,,,,,,

,Distribution account,Transaction date,Transaction type,Num,Name,Description,Account Name,Cleared,Amount,Balance
Inventory,,,,,,,,,,
,Beginning Balance,,,,,,,,,"1,000.00"
,Inventory,01/08/2024,Expense,,,WT FED#03158 COMMUNITY FEDERAL  /FTR/BNF=Shenzhen Minzhi BYJ Trading Company          SRF#    OWXXXXXXXX253119 TRN#XXXXXXXX2548  RFB#    OWXXXXXXXX253119,Inventory,Uncleared,"16,948.60","17,948.60"
,Inventory,01/16/2024,Expense,,,WT 240116-257207 BANK OF CHINA       /BNF=Shenzhen Linkhub Co Ltd                     SRF#    OWXXXXXXXX055551 TRN#XXXXXXXX7207  RFB#    OWXXXXXXXX055551,Inventory,Uncleared,990.04,"18,938.64"
,Inventory,05/11/2024,Expense,,,Sent WEIMIN HUANG,Inventory,Uncleared,142.26,"19,080.90"
,Inventory,03/08/2024,Expense,,Alibaba.com LLC,Alibaba.com,Inventory,Uncleared,"1,293.04","20,373.94"
,Inventory,07/25/2024,Expense,,Aco Mexico,ACO MEX APTO T1 URBAN,Inventory,Uncleared,5.86,"20,379.80"
Total for Inventory,,,,,,,,,"$20,379.80",
TOTAL,,,,,,,,,"$20,379.80",

" Wednesday, September 16, 2026 02:46 PM GMT+03:00",,,,,,,,,,
"""


def test_parse_qbo_quickreport_csv_finds_every_real_transaction():
    transactions = parse_qbo_quickreport_csv(SAMPLE_QBO_CSV)

    assert len(transactions) == 5
    assert transactions[0] == QboTransaction(
        date=date(2024, 1, 8),
        name="",
        description=(
            "WT FED#03158 COMMUNITY FEDERAL  /FTR/BNF=Shenzhen Minzhi BYJ Trading Company          "
            "SRF#    OWXXXXXXXX253119 TRN#XXXXXXXX2548  RFB#    OWXXXXXXXX253119"
        ),
        amount=Decimal("16948.60"),
    )


def test_parse_qbo_quickreport_csv_skips_beginning_balance_and_footer_rows():
    transactions = parse_qbo_quickreport_csv(SAMPLE_QBO_CSV)

    # Beginning Balance (no date), Total for Inventory / TOTAL (no date),
    # and the trailing timestamp line must never show up as transactions.
    assert all(t.amount != Decimal("1000.00") for t in transactions)
    assert sum(t.amount for t in transactions) == Decimal("19379.80")


def test_parse_qbo_quickreport_csv_raises_without_a_header_row():
    import pytest

    with pytest.raises(ValueError, match="Transaction date"):
        parse_qbo_quickreport_csv("just,some,random,csv\n1,2,3,4\n")


def test_classify_category_freight_vendor():
    assert classify_category("", "WT ... /BNF=Shenzhen Linkhub Co Ltd ...") is Category.FREIGHT_BUNDLING_PACKAGING


def test_classify_category_components_by_memo_vendor():
    assert classify_category("", "WT ... BNF=Shenzhen Minzhi BYJ Trading Company ...") is Category.COMPONENTS


def test_classify_category_components_by_alibaba_name():
    assert classify_category("Alibaba.com LLC", "Alibaba.com") is Category.COMPONENTS


def test_classify_category_overhead_personal_wire():
    assert classify_category("", "Sent WEIMIN HUANG") is Category.OVERHEAD


def test_classify_category_unrecognized_vendor_returns_none_not_a_guess():
    assert classify_category("Aco Mexico", "ACO MEX APTO T1 URBAN") is None


def test_clean_payee_matches_real_workbook_labels():
    assert clean_payee("", "", Category.FREIGHT_BUNDLING_PACKAGING) == "FBA Bee"
    assert clean_payee("", "", Category.OVERHEAD) == "Weimin Huang"
    assert clean_payee("", "", Category.COMPONENTS) == "Shenzhen Minzhi BYJ Trading Co"
    assert clean_payee("Alibaba.com LLC", "", Category.COMPONENTS) == "Shanghai Beone (Alibaba)"


def test_clean_payee_falls_back_to_raw_text_when_unclassified():
    assert clean_payee("Aco Mexico", "ACO MEX APTO T1 URBAN", None) == "Aco Mexico"


def test_extract_reference_pulls_trn_number():
    assert extract_reference("... TRN#XXXXXXXX2548 ...") == "TRNXXXXXXXX2548"


def test_extract_reference_blank_when_not_found():
    assert extract_reference("Sent WEIMIN HUANG") == ""


def test_build_section_a_row_flags_unclassified_vendor():
    txn = QboTransaction(date=date(2024, 7, 25), name="Aco Mexico", description="ACO MEX APTO T1 URBAN", amount=Decimal("5.86"))
    row = build_section_a_row(txn)

    assert row.category is None
    assert row.flagged is True
    assert "not recognized" in row.flag_reason


def test_build_section_a_row_not_flagged_for_recognized_vendor():
    txn = QboTransaction(date=date(2024, 1, 16), name="", description="... Shenzhen Linkhub Co Ltd ...", amount=Decimal("990.04"))
    row = build_section_a_row(txn)

    assert row.category is Category.FREIGHT_BUNDLING_PACKAGING
    assert row.flagged is False


def test_plan_section_a_sync_skips_existing_date_amount_pairs():
    transactions = [
        QboTransaction(date=date(2024, 1, 8), name="", description="Shenzhen Minzhi", amount=Decimal("100.00")),
        QboTransaction(date=date(2024, 1, 9), name="", description="Shenzhen Minzhi", amount=Decimal("200.00")),
    ]
    existing = [(date(2024, 1, 8), Decimal("100.00"))]

    new_rows, skipped = plan_section_a_sync(transactions, existing)

    assert len(new_rows) == 1
    assert new_rows[0].date == date(2024, 1, 9)
    assert len(skipped) == 1
    assert skipped[0].date == date(2024, 1, 8)


def test_plan_section_a_sync_all_new_when_sheet_is_empty():
    transactions = [
        QboTransaction(date=date(2024, 1, 8), name="", description="Shenzhen Minzhi", amount=Decimal("100.00")),
    ]

    new_rows, skipped = plan_section_a_sync(transactions, [])

    assert len(new_rows) == 1
    assert skipped == []

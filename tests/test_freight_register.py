from datetime import date
from decimal import Decimal

from landed_cost.models import SourceDocument
from landed_cost.sheets.freight_register import (
    base_invoice_number,
    build_freight_register_rows,
    extract_freight_and_bundling,
    extract_payment_amount,
)

# Real text confirmed against actual Shenzhen Linkhub / FBSL documents (2026-09-18).
INVOICE_TEXT = """John Grattan Invoice JG20240108E

INVOICE

Shenzhen Linkhub CO., LTD INVOICE \\# JG20240108E Add:Room 1801, Building 1, Wanting Building INVOICE DATE 12-Jan-2024

FREIGHT CHARGES

DDP Sea Freight LTL X002FQI1RH 55 34 63 11.9 23 2.71 274.0 452 US$1.94 per kgs US$876.88

SUB TOTAL US$876.88

ADDITIONAL CHARGES

Bundling 138 US$0.82 per piece US$113.16

SUB TOTAL US$113.16

THANK YOU FOR YOUR BUSINESS GRAND TOTAL US$990.04
"""

MULTI_REGION_INVOICE_TEXT = """John Grattan Invoice JG20240115E-CA+DE

INVOICE

Shenzhen Linkhub CO., LTD INVOICE \\# JG20240115E-CA+DE INVOICE DATE 15-Jan-2024

FREIGHT CHARGES

DDP Sea Freight LTL X0027XMJQ7 55 34 63 10.55 5 0.59 53.0 99 US$1.45 per kgs US$143.55

SUB TOTAL US$2,044.32

ADDITIONAL CHARGES

Bundling CA+DE 1 US$277.26 flat rate US$277.26

SUB TOTAL US$277.26

THANK YOU FOR YOUR BUSINESS GRAND TOTAL US$2,321.58
"""

WIRE_CONFIRMATION_TEXT = """Confirmation

You successfully submitted your wire on 01/16/2024 at 02:40 pm Pacific Time.

ToFBABee

China

From OPEX

Amount $990.04

Wire transfer fee $25.00

Total USD from account

$1,015.04

Message to recipient's bank

invoice JG20240108E

Status Pending
"""

REFUND_INVOICE_TEXT = """John Grattan Invoice JG20250612E-Refurn

INVOICE

Shenzhen Linkhub CO., LTD INVOICE \\# JG20250612E-Refurn INVOICE DATE 11-Jun-2025

FREIGHT CHARGES

SUB TOTAL US$2,861.85

THANK YOU FOR YOUR BUSINESS GRAND TOTAL US$2,861.85
"""


def _doc(filename: str) -> SourceDocument:
    return SourceDocument.from_filename(filename)


def test_extract_freight_and_bundling_from_real_invoice_text():
    assert extract_freight_and_bundling(INVOICE_TEXT) == (Decimal("876.88"), Decimal("113.16"))


def test_extract_freight_and_bundling_single_sub_total_treats_bundling_as_zero():
    assert extract_freight_and_bundling(REFUND_INVOICE_TEXT) == (Decimal("2861.85"), Decimal("0"))


def test_extract_freight_and_bundling_none_when_nothing_matches():
    assert extract_freight_and_bundling("no SUB TOTAL anywhere here") == (None, None)


def test_extract_payment_amount_from_real_wire_confirmation():
    assert extract_payment_amount(WIRE_CONFIRMATION_TEXT) == Decimal("990.04")


def test_base_invoice_number_strips_region_suffix():
    assert base_invoice_number("JG20240115E-CA") == "JG20240115E"
    assert base_invoice_number("JG20240422E-CA+DE") == "JG20240422E"
    assert base_invoice_number("JG20250612E-Refurn") == "JG20250612E"


def test_base_invoice_number_unchanged_when_already_bare():
    assert base_invoice_number("JG20240108E") == "JG20240108E"


def test_base_invoice_number_unchanged_when_pattern_does_not_match():
    assert base_invoice_number("Wise 1370922330") == "Wise 1370922330"


def test_build_freight_register_rows_pairs_invoice_and_payment():
    documents = [
        (_doc("2024-01-12_FBSL_Frei-Bund_JG20240108E_INV-paid.pdf"), INVOICE_TEXT),
        (_doc("2024-01-16_FBSL_Frei-Bund_JG20240108E_pconf.pdf"), WIRE_CONFIRMATION_TEXT),
    ]

    rows = build_freight_register_rows(documents)

    assert len(rows) == 1
    row = rows[0]
    assert row.invoice_number == "JG20240108E"
    assert row.invoice_date == date(2024, 1, 12)
    assert row.paid_date == date(2024, 1, 16)
    assert row.freight_amount == Decimal("876.88")
    assert row.bundling_amount == Decimal("113.16")
    assert row.invoice_link == "2024-01-12_FBSL_Frei-Bund_JG20240108E_INV-paid.pdf"
    assert row.payment_link == "2024-01-16_FBSL_Frei-Bund_JG20240108E_pconf.pdf"
    assert row.prep_sheet_label == "2024-01 JAN"
    assert row.flagged is False


def test_build_freight_register_rows_flags_payment_amount_mismatch():
    # Wire confirmation says $1.00 but the invoice's own Freight+Bundling
    # totals $990.04 -- a real discrepancy worth a human look.
    mismatched_wire_text = WIRE_CONFIRMATION_TEXT.replace("Amount $990.04", "Amount $1.00")
    documents = [
        (_doc("2024-01-12_FBSL_Frei-Bund_JG20240108E_INV-paid.pdf"), INVOICE_TEXT),
        (_doc("2024-01-16_FBSL_Frei-Bund_JG20240108E_pconf.pdf"), mismatched_wire_text),
    ]

    rows = build_freight_register_rows(documents)

    assert rows[0].flagged is True
    assert "wire fee or partial payment" in rows[0].flag_reason


def test_build_freight_register_rows_multi_region_invoices_share_base_payment():
    # Two region-suffixed invoices, ONE payment confirmation referencing
    # only the base number -- both invoices must get its Paid date, each
    # keeping its own stated Freight $/Bundling $ (no summing).
    documents = [
        (_doc("2024-01-15_FBSL_Frei-Bund_JG20240115E-CA_INV-paid.pdf"), MULTI_REGION_INVOICE_TEXT),
        (_doc("2024-01-15_FBSL_Frei-Bund_JG20240115E-US_INV-paid.pdf"), INVOICE_TEXT),
        (_doc("2024-01-16_FBSL_Frei-Bund_JG20240115E_pconf.pdf"), WIRE_CONFIRMATION_TEXT),
    ]

    rows = build_freight_register_rows(documents)

    assert len(rows) == 2
    by_number = {r.invoice_number: r for r in rows}
    assert by_number["JG20240115E-CA"].freight_amount == Decimal("2044.32")
    assert by_number["JG20240115E-US"].freight_amount == Decimal("876.88")
    assert by_number["JG20240115E-CA"].paid_date == date(2024, 1, 16)
    assert by_number["JG20240115E-US"].paid_date == date(2024, 1, 16)
    assert by_number["JG20240115E-CA"].payment_link == "2024-01-16_FBSL_Frei-Bund_JG20240115E_pconf.pdf"
    assert by_number["JG20240115E-US"].payment_link == "2024-01-16_FBSL_Frei-Bund_JG20240115E_pconf.pdf"


def test_build_freight_register_rows_refund_invoice_negates_amounts():
    documents = [
        (_doc("2025-06-11_FBSL_Frei-Bund_JG20250612E-Refurn_INV-refund.pdf"), REFUND_INVOICE_TEXT),
    ]

    rows = build_freight_register_rows(documents)

    assert len(rows) == 1
    assert rows[0].freight_amount == Decimal("-2861.85")
    assert rows[0].bundling_amount == Decimal("0")
    assert rows[0].payment_link == ""
    assert rows[0].flagged is False


def test_build_freight_register_rows_flags_when_extraction_fails():
    documents = [
        (_doc("2024-01-12_FBSL_Frei-Bund_JG20240108E_INV-paid.pdf"), "no recognizable total anywhere"),
    ]

    rows = build_freight_register_rows(documents)

    assert rows[0].freight_amount is None
    assert rows[0].flagged is True
    assert "could not extract" in rows[0].flag_reason


def test_build_freight_register_rows_groups_by_invoice_number_not_by_file():
    documents = [
        (_doc("2024-01-12_FBSL_Frei-Bund_JG20240108E_INV-paid.pdf"), INVOICE_TEXT),
        (_doc("2024-01-16_FBSL_Frei-Bund_JG20240108E_pconf.pdf"), WIRE_CONFIRMATION_TEXT),
        (_doc("2024-01-15_FBSL_Frei-Bund_JG20240115E-CA_INV-paid.pdf"), MULTI_REGION_INVOICE_TEXT),
    ]

    rows = build_freight_register_rows(documents)

    assert len(rows) == 2
    assert {r.invoice_number for r in rows} == {"JG20240108E", "JG20240115E-CA"}

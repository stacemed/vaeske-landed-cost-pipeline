from datetime import date
from decimal import Decimal

from landed_cost.models import SourceDocument
from landed_cost.sheets.overhead_register import (
    build_overhead_register_rows,
    extract_overhead_amount,
)

# Real text confirmed against actual 2024 Weimin Huang documents (2026-09-17).
WISE_PCONF_TEXT = """Transfer Invoice

Transfer confirmation

Transfer created January 11, 2024 12:47:17 GMT-05:00

Amount paid by BLACK OAK ESSENTIALS LLC 218.00 USD

Transfer amount 218.00 USD

Total to WEIMIN HUANG 218.00 USD

Sent to

Name WEIMIN HUANG

Reference inspection invoice 240112
"""

WH_INVOICE_TEXT = """From: Whymon Huang (WEIMIN HUANG)

Inspection Invoice

#INV-Inspection- 240112

Balance Due

$218.00
Invoice Date: 11 Jan-24
Total $218.00
"""


def _doc(filename: str) -> SourceDocument:
    return SourceDocument.from_filename(filename)


def test_extract_overhead_amount_prefers_wise_total_to_line():
    assert extract_overhead_amount(WISE_PCONF_TEXT) == Decimal("218.00")


def test_extract_overhead_amount_from_invoice_total_line():
    assert extract_overhead_amount(WH_INVOICE_TEXT) == Decimal("218.00")


def test_extract_overhead_amount_none_when_nothing_matches():
    assert extract_overhead_amount("no dollar figures here at all") is None


def test_build_overhead_register_rows_pairs_invoice_and_payment():
    documents = [
        (_doc("2024-01-11_WH_Over_Inspection-240112_INV-paid.pdf"), WH_INVOICE_TEXT),
        (_doc("2024-01-11_WH_Over_Inspection-240112_pconf.pdf"), WISE_PCONF_TEXT),
    ]

    rows = build_overhead_register_rows(documents)

    assert len(rows) == 1
    row = rows[0]
    assert row.invoice_number == "Inspection-240112"
    assert row.invoice_date == date(2024, 1, 11)
    assert row.paid_date == date(2024, 1, 11)
    assert row.amount == Decimal("218.00")  # from the pconf, preferred over the invoice
    assert row.invoice_link == "2024-01-11_WH_Over_Inspection-240112_INV-paid.pdf"
    assert row.payment_link == "2024-01-11_WH_Over_Inspection-240112_pconf.pdf"
    assert row.flagged is False


def test_build_overhead_register_rows_prefers_payment_confirmation_date_over_invoice_date():
    # Real pattern seen in 2024 data: pconf dated a day after the invoice.
    documents = [
        (_doc("2024-01-02_WH_Over_Inspection-240102_INV-paid.pdf"), "Total $200.00"),
        (_doc("2024-01-03_WH_Over_Inspection-240102_pconf.pdf"), "Total to WEIMIN HUANG 200.00 USD"),
    ]

    rows = build_overhead_register_rows(documents)

    assert rows[0].invoice_date == date(2024, 1, 2)
    assert rows[0].paid_date == date(2024, 1, 3)


def test_build_overhead_register_rows_payment_only_falls_back_gracefully():
    # Some real invoices have no separate invoice PDF, only a Wise pconf.
    documents = [
        (_doc("2024-10-09_WH_Over_Inspection-241009_pconf.pdf"), "Total to WEIMIN HUANG 168.00 USD"),
    ]

    rows = build_overhead_register_rows(documents)

    assert len(rows) == 1
    assert rows[0].invoice_date is None
    assert rows[0].paid_date == date(2024, 10, 9)
    assert rows[0].invoice_link == ""
    assert rows[0].payment_link == "2024-10-09_WH_Over_Inspection-241009_pconf.pdf"


def test_build_overhead_register_rows_flags_when_amount_extraction_fails():
    documents = [
        (_doc("2024-04-07_WH_Over_Support-240407_INV-paid.pdf"), "no recognizable total anywhere"),
    ]

    rows = build_overhead_register_rows(documents)

    assert rows[0].amount is None
    assert rows[0].flagged is True
    assert "could not extract" in rows[0].flag_reason


def test_build_overhead_register_rows_groups_by_invoice_number_not_by_file():
    documents = [
        (_doc("2024-01-11_WH_Over_Inspection-240112_INV-paid.pdf"), "Total $218.00"),
        (_doc("2024-01-11_WH_Over_Inspection-240112_pconf.pdf"), "Total to WEIMIN HUANG 218.00 USD"),
        (_doc("2024-10-09_WH_Over_Inspection-241009_pconf.pdf"), "Total to WEIMIN HUANG 168.00 USD"),
    ]

    rows = build_overhead_register_rows(documents)

    assert len(rows) == 2
    assert {r.invoice_number for r in rows} == {"Inspection-240112", "Inspection-241009"}

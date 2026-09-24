from datetime import date
from decimal import Decimal

from landed_cost.models import SourceDocument
from landed_cost.sheets.freight_register import (
    base_invoice_number,
    build_freight_register_rows,
    extract_freight_and_bundling,
    extract_invoice_total,
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

# Real text confirmed against an actual JG20240711E invoice (2026-09-22) --
# Linkhub's newer template, no per-section subtotal at all. Freight legs
# sum to $11,693.05 (including the "Remote area surcharge"), Bundling to
# $672.34; their sum is a cent off the invoice's own stated Subtotal
# ($12,365.38 vs $12,365.39), which is real per-line rounding noise on
# the vendor's own invoice, not an extraction error -- within tolerance.
NEW_TEMPLATE_INVOICE_TEXT = """John Grattan Invoice JG20240711E

INVOICE Shenzhen Linkhub CO., LTD

INVOICE No. JG20240711E US$12,365.38 INVOICE DATE 12-Jul-2024 DUE DATE 13-Jul-2024

BILL TO

John Grattan

ITEM DESCRIPTION RATE QUANTITY AMOUNT

DDP Sea Freight SPD LH01281197 Ship to BER8

20 CTNS | 224 KGS | 2.42 CBM $2.10 per kgs 404.26 $848.95

DDP Sea Freight LTL LH01281180 Ship to Vaeske C/O A&M Prep Services

155 CTNS | 1280.5 KGS | 16.02 CBM $1.16 per kgs 2670 $3,097.20

DDP Sea Freight SPD LH01281136 Ship to SCK8

22 CTNS | 251.9 KGS | 2.647 CBM $1.62 per kgs 441.8 $715.72

DDP Sea Freight LTL LH01281121 Ship to BWI4

77 CTNS | 618.2 KGS | 7.96 CBM $1.54 per kgs 1327 $2,043.58

DDP Sea Freight LTL LH01281113 Ship to LFT1

82 CTNS | 697.3 KGS | 8.48 CBM $1.69 per kgs 1413 $2,387.97

DDP Sea Freight LTL LH01281104 Ship to SLC2

61 CTNS | 469.5 KGS | 6.31 CBM $1.59 per kgs 1051 $1,671.09

DDP Sea Freight LTL LH01281093 Ship to YYZ3

15 CTNS | 142.5 KGS | 1.8 CBM $1.74 per kgs 259 $450.66

DDP Sea Freight LTL LH01281082 Ship to YOW3

10 CTNS | 117 KGS | 1.21 CBM $1.82 per kgs 202.13 $367.88

Bundling $0.62 per piece 1092 $672.34

Remote area surcharge Remote area Fee of SCK8 $5.00 22 $110.00

Subtotal $12,365.38

THANK YOU FOR YOUR BUSINESS TOTAL US$12,365.38
"""

# Real text confirmed against an actual JG20260119E invoice (2026-09-22) --
# same newer template, this time with packaging-material line items
# (Tape/Airbags/Polybags) instead of a surcharge. Sums exactly to the
# invoice's own Subtotal, no rounding noise this time.
NEW_TEMPLATE_INVOICE_TEXT_2 = """John Grattan Invoice JG20260119E

INVOICE Shenzhen Linkhub CO., LTD

INVOICE No. JG20260119E US$2,144.19 INVOICE DATE 19-Jan-2026 DUE DATE 21-Jan-2026

BILL TO

VAESKE

John Grattan

ITEM DESCRIPTION RATE QUANTITY AMOUNT

DDP Sea Freight SPD LH03034332 Ship to DTM1

17 CTNS | 188.9 KGS | 2.05 CBM $1.61 per kgs 351 $565.11

DDP Sea Freight LTL LH03034311 Ship to YOO1

30 CTNS | 292 KGS | 3.03 CBM $1.27 per kgs 519 $659.13

DDP Sea Freight LTL LH03034308 Ship to YHM1

8 CTNS | 93.6 KGS | 0.968 CBM $1.27 per kgs 165 $209.55

Tape Tape with VAESKE LOGO(100 rolls) $336.00 flat rate 1 $336.00

Airbags 10rolls $66.00 flat rate 1 $66.00

Polybags 2000pcs $150.00 flat rate 1 $150.00

Bundling 210units $158.40 flat rate 1 $158.40

Subtotal $2,144.19

TOTAL US$2,144.19
"""

# Real text confirmed against an actual JG20241104E invoice (2026-09-24)
# -- an UNRECOGNIZED line item ("Pickup Samples...") sits right after
# the real Bundling line, before Subtotal. Real bug this guards against:
# a naive "read up to the next RECOGNIZED keyword" approach swallowed
# this trailing line into the Bundling line's own segment and picked up
# its $16.00 instead of Bundling's real $1,184.86 -- silently wrong by
# over $1,000, not just a rounding gap.
NEW_TEMPLATE_TRAILING_UNRECOGNIZED_ITEM_TEXT = """John Grattan JG20241104E

INVOICE Shenzhen Linkhub CO., LTD

INVOICE No. JG20241104E US$14,991.20 INVOICE DATE 16-Oct-2024 DUE DATE 5-Nov-2024

ITEM DESCRIPTION RATE QUANTITY AMOUNT

DDP Sea Freight SPD LH01412045 Ship to BER8

10 CTNS | 119 KGS | 1.2 CBM $1.89 per kgs 203 $383.67

DDP Sea Freight LTL LH01412036 Ship to YHM1

27 CTNS | 306 KGS | 3.28 CBM $1.31 per kgs 547 $716.57

Bundling 1726units $1,184.86 flat rate 1 $1,184.86

Pickup Samples to testing company $16.00 flat rate 1 $16.00

Subtotal $2,301.10

THANK YOU FOR YOUR BUSINESS TOTAL US$2,301.10
"""

# Real text confirmed against an actual JG20260424E invoice (2026-09-24)
# -- uses "DDP Truck Freight" (not "DDP Sea Freight") for one leg, a
# real shipping-mode variant this extractor didn't originally recognize.
NEW_TEMPLATE_TRUCK_FREIGHT_TEXT = """John Grattan Invoice JG20260424E

INVOICE Shenzhen Linkhub CO., LTD

INVOICE No. JG20260424E US$4,663.47 INVOICE DATE 24-Apr-2026 DUE DATE 27-Apr-2026

ITEM DESCRIPTION RATE QUANTITY AMOUNT

DDP Truck Freight SPD LH2617400285 Ship to HAJ1

35 CTNS | 395 KGS | 4.25 CBM $2.43 per kgs 709 $1,722.87

DDP Sea Freight LTL LH2617400061 Ship to IUSF

111 CTNS | 1,120 KGS | 11.72 CBM $1.02 per kgs 1954 $1,993.08

DDP Sea Freight LTL LH2617400052 Ship to YEG1

25 CTNS | 204 KGS | 2.59 CBM $1.28 per kgs 432 $552.96

Bundling 538units $394.56 flat rate 1 $394.56

Subtotal $4,663.47

THANK YOU FOR YOUR BUSINESS TOTAL US$4,663.47
"""


def _doc(filename: str) -> SourceDocument:
    return SourceDocument.from_filename(filename)


def test_extract_freight_and_bundling_from_real_invoice_text():
    assert extract_freight_and_bundling(INVOICE_TEXT) == (Decimal("876.88"), Decimal("113.16"))


def test_extract_freight_and_bundling_single_sub_total_treats_bundling_as_zero():
    assert extract_freight_and_bundling(REFUND_INVOICE_TEXT) == (Decimal("2861.85"), Decimal("0"))


def test_extract_freight_and_bundling_none_when_nothing_matches():
    assert extract_freight_and_bundling("no SUB TOTAL anywhere here") == (None, None)


def test_extract_freight_and_bundling_new_template_sums_line_items_with_surcharge():
    freight, bundling = extract_freight_and_bundling(NEW_TEMPLATE_INVOICE_TEXT)

    # 8 freight legs + Remote area surcharge, all routed to Freight $.
    assert freight == Decimal("11693.05")
    assert bundling == Decimal("672.34")


def test_extract_freight_and_bundling_new_template_sums_packaging_materials():
    freight, bundling = extract_freight_and_bundling(NEW_TEMPLATE_INVOICE_TEXT_2)

    assert freight == Decimal("1433.79")
    # Tape + Airbags + Polybags + Bundling, all routed to Bundling $.
    assert bundling == Decimal("710.40")


def test_extract_freight_and_bundling_skips_unrecognized_trailing_line_item():
    # Real bug (2026-09-24): a naive "read to the next RECOGNIZED
    # keyword" approach absorbed the trailing "Pickup Samples...
    # $16.00" line into the preceding Bundling line's own segment and
    # picked up ITS amount instead -- Bundling came out as $16.00, not
    # the real $1,184.86. Chunking by paragraph must isolate Bundling's
    # own line and skip the unrecognized one entirely.
    freight, bundling = extract_freight_and_bundling(NEW_TEMPLATE_TRAILING_UNRECOGNIZED_ITEM_TEXT)

    assert freight == Decimal("1100.24")
    assert bundling == Decimal("1184.86")


def test_extract_freight_and_bundling_recognizes_truck_freight():
    # Real bug (2026-09-24): "DDP Truck Freight" wasn't a recognized
    # keyword, so that whole line item (a real $1,722.87 leg) was
    # invisible to extraction entirely.
    freight, bundling = extract_freight_and_bundling(NEW_TEMPLATE_TRUCK_FREIGHT_TEXT)

    assert freight == Decimal("4268.91")  # 1722.87 + 1993.08 + 552.96
    assert bundling == Decimal("394.56")


def test_build_freight_register_rows_flags_shortfall_from_unrecognized_line_item():
    # The $16 Pickup Samples line is skipped, so the extracted sum comes
    # up exactly $16 short of the invoice's own stated total -- flagged,
    # not silently accepted, so a human adds it in by hand.
    documents = [
        (_doc("2024-10-16_FBSL_Frei-Bund_JG20241104E_INV-paid.pdf"), NEW_TEMPLATE_TRAILING_UNRECOGNIZED_ITEM_TEXT),
    ]

    rows = build_freight_register_rows(documents)

    assert rows[0].freight_amount == Decimal("1100.24")
    assert rows[0].bundling_amount == Decimal("1184.86")
    assert rows[0].flagged is True
    assert "may not have been recognized" in rows[0].flag_reason


def test_extract_invoice_total_ignores_sub_total_lines_on_old_template():
    assert extract_invoice_total(INVOICE_TEXT) == Decimal("990.04")


def test_extract_invoice_total_from_new_template():
    assert extract_invoice_total(NEW_TEMPLATE_INVOICE_TEXT) == Decimal("12365.38")
    assert extract_invoice_total(NEW_TEMPLATE_INVOICE_TEXT_2) == Decimal("2144.19")


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


def test_build_freight_register_rows_new_template_extracts_via_line_items():
    documents = [
        (_doc("2024-07-12_FBSL_Frei-Bund_JG20240711E_INV-paid.pdf"), NEW_TEMPLATE_INVOICE_TEXT),
    ]

    rows = build_freight_register_rows(documents)

    assert len(rows) == 1
    assert rows[0].freight_amount == Decimal("11693.05")
    assert rows[0].bundling_amount == Decimal("672.34")
    # $12,365.39 (extracted sum) vs $12,365.38 (invoice's own stated
    # total) is a cent of real per-line rounding noise -- not flagged.
    assert rows[0].flagged is False


def test_build_freight_register_rows_flags_stated_total_mismatch():
    # Drop the "Remote area surcharge" line item -- the extracted sum
    # will fall $110 short of the invoice's own stated total, well
    # outside the real per-line rounding tolerance seen above.
    missing_line_item_text = NEW_TEMPLATE_INVOICE_TEXT.replace(
        "Remote area surcharge Remote area Fee of SCK8 $5.00 22 $110.00\n\n", ""
    )
    documents = [
        (_doc("2024-07-12_FBSL_Frei-Bund_JG20240711E_INV-paid.pdf"), missing_line_item_text),
    ]

    rows = build_freight_register_rows(documents)

    assert rows[0].flagged is True
    assert "may not have been recognized" in rows[0].flag_reason


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

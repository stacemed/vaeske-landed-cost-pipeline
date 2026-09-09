from datetime import date

from landed_cost.models import Category, DocumentType
from landed_cost.drive.extract import extract_from_text, propose_filename
from landed_cost.models import SourceDocument

# Fixture texts below mirror the structure of real documents found in the
# project's Drive folder (Linkhub freight invoices, Wells Fargo/Wise
# confirmations, Weimin Huang inspection invoices) -- trimmed to the
# lines the extractor actually keys on.

FREIGHT_INVOICE_TEXT = """
John Grattan Invoice JG20250421E

INVOICE Shenzhen Linkhub CO., LTD
Room 1801, Building 1, Wanting Building

INVOICE No. JG20250421E US$3,651.21 INVOICE DATE 21-Apr-2025 DUE DATE 23-Apr-2025

BILL TO
VAESKE

ITEM DESCRIPTION RATE QUANTITY AMOUNT
DDP Sea Freight LTL LH02160460 Ship to IUSL
Bundling 246units $186.44 flat rate 1 $186.44
Subtotal $3,651.21
THANK YOU FOR YOUR BUSINESS TOTAL US$3,651.21
"""

FREIGHT_WIRE_CONFIRMATION_TEXT = """
Wire Money - Confirmation | Wells Fargo

Confirmation

You submitted your wire on 04/22/2025 at 11:44 am Pacific Time.

TO FBABEE
China

ADDITIONAL INFORMATION

JG20250421E

MESSAGE TO RECIPIENT'S BANK

JG20250421E

STATUS PENDING
"""

FREIGHT_REFUND_TEXT = """
INVOICE Shenzhen Linkhub CO., LTD

INVOICE No. JG20250612E-Refurn US$-2,861.85 INVOICE DATE 11-Jun-2025

Discounts Over payment refund -$2,861.85 flat rate 1 -$2,861.85

Subtotal -$2,861.85
"""

OVERHEAD_INVOICE_TEXT = """
From: Whymon Huang (WEIMIN HUANG) Inspection Invoice

#INV-Inspection-250930

Balance Paid $118.00)

Bill To Vaeske

Invoice Date: 29-Sep-25 Attn: John Grattan Terms: Custom Due Date: 30-Sep-25

Subject: Transport fee Duration: 2 Man Day
"""

COMPONENTS_WIRE_TEXT = """
Transfer confirmation

Transfer created November 05, 2025 08:31:26 GMT-05:00

Your details
Name BLACK OAK ESSENTIALS LLC

Sent to

Name WEIMIN HUANG

Reference INV-26Q1RCS payment 2b
"""

COMPONENTS_WIRE_TRANSFER_TEXT = """
WT FED#03350 COMMUNITY FEDERAL /FTR/BNF=Shenzhen Minzhi BYJ Trading Company
Invoice # INV-25Q1SLV26QTINNERBOX-01 26 QT Inner Box order
"""

UNKNOWN_TEXT = "Some random receipt from a coffee shop, nothing to do with any vendor here."

# The four fixtures below are trimmed from real 2024 Drive files that
# exposed genuine bugs during the first real-world dry run (2026-09-05).

COMPONENTS_WHYMON_FEDWIRE_TEXT = """
Wire Money - Confirmation | Wells Fargo

Confirmation

You submitted your wire on 12/16/2024 at 11:08 am Pacific Time.

TO WHYMON FEDWIRE

United States

AMOUNT $19,817.37

MESSAGE TO RECIPIENT'S BANK

INV USQ4RR12C26C

STATUS PENDING
"""

COMPONENTS_WIRE_SUCCESSFULLY_SUBMITTED_TEXT = """
Confirmation

You successfully submitted your wire on 04/21/2024 at 08:57 pm Pacific Time.

To Whymon FedWire

United States

Amount $10,395.00

Message to recipient's bank

racks invoice US3RD24 03

Status Scheduled
"""

# A real Shenzhen Minzhi BYJ invoice has a line reading "Invoice ...
# Subject: TTL BALANCE payment ..." -- before the digit filter, "Subject"
# itself got captured as the "invoice number" since it's a capitalized
# word immediately following "Invoice".
COMPONENTS_SUBJECT_FALSE_POSITIVE_TEXT = """
Shenzhen Minzhi BYJ Trading Company

Invoice Subject: TTL BALANCE payment for Q4 2024 order US3rdR2401
"""

COMPONENTS_NO_DIGIT_CANDIDATE_TEXT = """
Shenzhen Minzhi BYJ Trading Company

Invoice Subject: no reference numbers anywhere in this memo
"""

FILENAME_STUB_TEXT = "INV-USR2312-01 YY 2nd Racks Balance 240106.xlsx"


def test_freight_invoice_extracts_confidently():
    extracted = extract_from_text(FREIGHT_INVOICE_TEXT)

    assert extracted.vendor_abbrev == "FBSL"
    assert extracted.category is Category.FREIGHT_BUNDLING_PACKAGING
    assert extracted.category_tag == "Frei-Bund"
    assert extracted.invoice_number == "JG20250421E"
    assert extracted.doc_date == date(2025, 4, 21)
    assert extracted.doc_type is DocumentType.PAID_INVOICE
    assert extracted.issues == ()
    assert extracted.is_ready_to_file is True


def test_freight_wire_confirmation_detected_as_payment_confirmation():
    extracted = extract_from_text(FREIGHT_WIRE_CONFIRMATION_TEXT)

    assert extracted.vendor_abbrev == "FBSL"
    assert extracted.invoice_number == "JG20250421E"
    assert extracted.doc_date == date(2025, 4, 22)
    assert extracted.doc_type is DocumentType.PAYMENT_CONFIRMATION
    assert extracted.is_ready_to_file is True


def test_freight_refund_detected_from_keywords():
    extracted = extract_from_text(FREIGHT_REFUND_TEXT)

    assert extracted.invoice_number == "JG20250612E-Refurn"
    assert extracted.doc_type is DocumentType.REFUND_INVOICE


def test_overhead_invoice_extracts_confidently():
    extracted = extract_from_text(OVERHEAD_INVOICE_TEXT)

    assert extracted.vendor_abbrev == "WH"
    assert extracted.category is Category.OVERHEAD
    assert extracted.category_tag == "Over"
    # "INV-" is dropped from the source text's "#INV-Inspection-250930" --
    # redundant next to the doc-type suffix (2026-09-08).
    assert extracted.invoice_number == "Inspection-250930"
    assert extracted.doc_date == date(2025, 9, 29)
    assert extracted.doc_type is DocumentType.PAID_INVOICE
    assert extracted.is_ready_to_file is True


def test_overhead_invoice_number_without_inv_prefix_in_source_text():
    text = """
    From: Whymon Huang (WEIMIN HUANG) Inspection Invoice

    #Inspection-241027

    Invoice Date: 27-Nov-24
    """
    extracted = extract_from_text(text)
    assert extracted.invoice_number == "Inspection-241027"


def test_components_never_ready_to_file_even_with_good_matches():
    extracted = extract_from_text(COMPONENTS_WIRE_TEXT)

    assert extracted.vendor_abbrev == "WHSM"
    assert extracted.category is Category.COMPONENTS
    assert extracted.invoice_number == "INV-26Q1RCS"
    assert extracted.doc_type is DocumentType.PAYMENT_CONFIRMATION
    # Always flagged, by design, regardless of how good the guess looks.
    assert extracted.is_ready_to_file is False
    assert any("no consistent format" in issue for issue in extracted.issues)


def test_components_extracts_from_wire_transfer_memo():
    extracted = extract_from_text(COMPONENTS_WIRE_TRANSFER_TEXT)

    assert extracted.category is Category.COMPONENTS
    assert extracted.invoice_number == "INV-25Q1SLV26QTINNERBOX-01"
    assert extracted.is_ready_to_file is False


def test_unknown_vendor_returns_no_fields_and_an_issue():
    extracted = extract_from_text(UNKNOWN_TEXT)

    assert extracted.vendor_abbrev is None
    assert extracted.category is None
    assert extracted.is_ready_to_file is False
    assert len(extracted.issues) == 1


def test_empty_text_is_handled_like_unknown_vendor():
    extracted = extract_from_text("")
    assert extracted.is_ready_to_file is False
    assert extracted.issues


def test_propose_filename_fills_in_all_fields_when_confident():
    extracted = extract_from_text(FREIGHT_INVOICE_TEXT)
    name = propose_filename(extracted, "pdf")

    assert name == "2025-04-21_FBSL_Frei-Bund_JG20250421E_INV-paid.pdf"
    # The generator and the parser must stay in sync with each other.
    parsed = SourceDocument.from_filename(name)
    assert parsed.invoice_number == "JG20250421E"
    assert parsed.doc_type is DocumentType.PAID_INVOICE


def test_propose_filename_uses_placeholders_for_missing_fields():
    extracted = extract_from_text(UNKNOWN_TEXT)
    name = propose_filename(extracted, "pdf")

    assert name == "UNKNOWN-DATE_UNKNOWN-VENDOR_UNKNOWN-CATEGORY_UNKNOWN-INVOICE_UNKNOWN-DOCTYPE.pdf"


def test_whymon_fedwire_wire_confirmation_recognized_as_components():
    # Real bug (2026-09-05): a domestic wire to Weimin Huang shows the
    # payee as "WHYMON FEDWIRE" -- never his name or company -- so this
    # never matched any vendor keyword at all before "whymon" was added.
    extracted = extract_from_text(COMPONENTS_WHYMON_FEDWIRE_TEXT)

    assert extracted.category is Category.COMPONENTS
    assert extracted.vendor_abbrev == "WHSM"
    assert extracted.doc_date == date(2024, 12, 16)
    assert extracted.doc_type is DocumentType.PAYMENT_CONFIRMATION


def test_wire_confirmation_tolerates_successfully_submitted_phrasing():
    # Real bug: an older Wells Fargo template reads "You successfully
    # submitted your wire on 04/21/2024" -- the extra word broke both the
    # doc-type keyword match and the date regex.
    extracted = extract_from_text(COMPONENTS_WIRE_SUCCESSFULLY_SUBMITTED_TEXT)

    assert extracted.category is Category.COMPONENTS
    assert extracted.doc_date == date(2024, 4, 21)
    assert extracted.doc_type is DocumentType.PAYMENT_CONFIRMATION


def test_invoice_number_extraction_skips_non_digit_false_positive():
    # Real bug: "Invoice Subject: ..." used to capture "Subject" itself as
    # the invoice number, since the old regex had no digit requirement.
    # It should skip that and find the later, real-looking candidate.
    extracted = extract_from_text(COMPONENTS_SUBJECT_FALSE_POSITIVE_TEXT)

    assert extracted.invoice_number == "US3rdR2401"


def test_invoice_number_extraction_gives_up_cleanly_with_no_digit_candidate():
    extracted = extract_from_text(COMPONENTS_NO_DIGIT_CANDIDATE_TEXT)

    assert extracted.invoice_number is None


def test_filename_stub_text_is_not_mistaken_for_real_content():
    # Real case: a few PDFs (apparently converted from an embedded .xlsx)
    # gave back only their own filename as "extracted text".
    extracted = extract_from_text(FILENAME_STUB_TEXT)

    assert extracted.is_ready_to_file is False
    assert extracted.vendor_abbrev is None


# Trimmed from real OCR output (2026-09-09) on scanned/photographed 2024
# invoices with no text layer -- confirmed via pypdf returning "" on the
# actual downloaded bytes, then real OCR text pulled to fix these bugs.

OVERHEAD_SUPPORT_TYPE_OCR_TEXT = """
From: Whymon Huana (WEIMIN HUANG)

Bill To

Vaeske

Attn: John Grattan

Subiect:

Facilitation & local touch base support

Invoice

#INV-Support- 240407

Balance Due

$399.00

Invoice Date: 7-Apr-24
Terms: Custom

Due Date: 11-Apr-24

WHYMON HUANG
"""

OVERHEAD_INSPECTION_OCR_WITH_STRAY_SPACE_TEXT = """
From: Whymon Huang (WEIMIN HUANG)

Subject:

Bunlde bulk order inspection of US& CA SHIPMENTS

Inspection Invoice

Signature

#INV-Inspection- 240301

Balance Due

$168.00

Invoice Date: 3-Mar-24
Terms: Custom

WHYMON HUANG
"""

COMPONENTS_OCR_WITH_MONTH_NAME_DATE_TEXT = """
Shenzhen Minzhi BYJ Trading Company INVOICE

To: Black Oak Essentials LLC
Attn: John Grattan

#INV-USR2312-01
Invoice Date: Jan 6, 2024

Order Reference: USR2312- 23DEC

Balance Due: US$7,656.60
"""


def test_overhead_recognizes_support_type_not_just_inspection():
    # Real bug: routing required the literal word "inspection" in the
    # text, so Weimin Huang's "Support" and "Facilitation" invoices never
    # got recognized as overhead at all.
    extracted = extract_from_text(OVERHEAD_SUPPORT_TYPE_OCR_TEXT)

    assert extracted.category is Category.OVERHEAD
    assert extracted.vendor_abbrev == "WH"
    assert extracted.invoice_number == "Support-240407"
    assert extracted.doc_date == date(2024, 4, 7)


def test_overhead_strips_ocr_inserted_space_in_reference():
    # OCR read "#INV-Inspection- 240301" with a stray space after the
    # hyphen -- the reference must still normalize to one clean token.
    extracted = extract_from_text(OVERHEAD_INSPECTION_OCR_WITH_STRAY_SPACE_TEXT)

    assert extracted.invoice_number == "Inspection-240301"
    assert extracted.doc_date == date(2024, 3, 3)


def test_components_still_wins_over_overhead_when_vendor_company_present():
    # Even though this text would match the overhead "#[INV-]<Type>-<ref>"
    # shape (#INV-USR2312-01), the Shenzhen Minzhi company name means
    # it's a components purchase invoice, not Weimin Huang's own.
    extracted = extract_from_text(COMPONENTS_OCR_WITH_MONTH_NAME_DATE_TEXT)

    assert extracted.category is Category.COMPONENTS
    assert extracted.doc_date == date(2024, 1, 6)
    assert extracted.is_ready_to_file is False


def test_month_name_date_format_parses():
    extracted = extract_from_text(COMPONENTS_OCR_WITH_MONTH_NAME_DATE_TEXT)
    assert extracted.doc_date == date(2024, 1, 6)


def test_weimin_mention_without_overhead_reference_falls_back_to_components():
    # A wire confirmation mentions "WHYMON" but never carries his
    # "#[INV-]<Type>-<ref>" invoice reference -- the safe direction is
    # components (never auto-files), not a mistaken overhead auto-file.
    extracted = extract_from_text(
        "You submitted your wire on 12/16/2024\n\nTO WHYMON FEDWIRE\n\n"
        "MESSAGE TO RECIPIENT'S BANK\n\nINV USQ4RR12C26C"
    )
    assert extracted.category is Category.COMPONENTS

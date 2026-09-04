from datetime import date

import pytest

from landed_cost.models import DocumentType, SourceDocument


@pytest.mark.parametrize(
    "filename,expected",
    [
        (
            "2025-01-15_WHSM_comp_INV-25Q1SLV26QTINNERBOX-01_INV-dep.pdf",
            dict(
                doc_date=date(2025, 1, 15),
                vendor_abbrev="WHSM",
                category_tag="comp",
                invoice_number="INV-25Q1SLV26QTINNERBOX-01",
                doc_type=DocumentType.DEPOSIT_INVOICE,
                extension="pdf",
            ),
        ),
        (
            "2024-12-26_FBSL_Frei-Bund_JG20241225E_INV-paid.pdf",
            dict(
                doc_date=date(2024, 12, 26),
                vendor_abbrev="FBSL",
                category_tag="Frei-Bund",
                invoice_number="JG20241225E",
                doc_type=DocumentType.PAID_INVOICE,
                extension="pdf",
            ),
        ),
        (
            "2025-06-11_FBSL_Frei-Bund_JG20250612E-Refurn_INV-refund.pdf",
            dict(
                doc_date=date(2025, 6, 11),
                vendor_abbrev="FBSL",
                category_tag="Frei-Bund",
                invoice_number="JG20250612E-Refurn",
                doc_type=DocumentType.REFUND_INVOICE,
                extension="pdf",
            ),
        ),
        (
            "2025-02-14_FBSL_Frei-Bund_JG20250214E_pconf.pdf",
            dict(
                doc_date=date(2025, 2, 14),
                vendor_abbrev="FBSL",
                category_tag="Frei-Bund",
                invoice_number="JG20250214E",
                doc_type=DocumentType.PAYMENT_CONFIRMATION,
                extension="pdf",
            ),
        ),
    ],
)
def test_parses_known_filenames(filename, expected):
    doc = SourceDocument.from_filename(filename)
    for field, value in expected.items():
        assert getattr(doc, field) == value


def test_category_tag_comparison_is_case_insensitive():
    lower = SourceDocument.from_filename(
        "2025-01-15_WHSM_comp_INV-1_INV-dep.pdf"
    )
    upper = SourceDocument.from_filename(
        "2025-06-05_WHSM_Comp_INV-2_INV-dep.pdf"
    )
    assert lower.category_tag_normalized == upper.category_tag_normalized == "comp"


def test_unrecognized_doc_type_falls_back_to_other():
    doc = SourceDocument.from_filename("2025-01-15_WHSM_comp_INV-1_mystery.pdf")
    assert doc.doc_type is DocumentType.OTHER


def test_accepts_full_path_and_keeps_only_the_basename():
    doc = SourceDocument.from_filename(
        "Drive/Vaeske/2025/2025-01-15_WHSM_comp_INV-1_INV-dep.pdf"
    )
    assert doc.raw_filename == "2025-01-15_WHSM_comp_INV-1_INV-dep.pdf"


@pytest.mark.parametrize(
    "filename",
    [
        "2025-01-15_WHSM_INV-1_INV-dep.pdf",  # missing a segment
        "not-a-date_WHSM_comp_INV-1_INV-dep.pdf",
        "2025-01-15_WHSM_comp_INV-1_INV-dep",  # no extension
        "2025-01-15_WHSM_comp_INV-1_a_b_INV-dep.pdf",  # too many segments
    ],
)
def test_malformed_filenames_are_flagged_not_guessed(filename):
    with pytest.raises(ValueError):
        SourceDocument.from_filename(filename)

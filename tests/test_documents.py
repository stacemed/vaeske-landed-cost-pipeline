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
    assert doc.doc_type_raw == "mystery"


@pytest.mark.parametrize(
    "suffix",
    ["pconf-bal", "pconf-bal2", "pconf-bal3", "pconf-bal4"],
)
def test_numbered_payment_confirmation_suffixes_still_classify(suffix):
    # Real convention (2026-09-15): a multi-payment invoice gets
    # pconf-bal for the first balance, pconf-bal2..bal4 for later ones
    # against the same order -- no number on the first.
    doc = SourceDocument.from_filename(
        f"2025-11-07_WHSM_Comp_INV-26Q1RCS_{suffix}.pdf"
    )
    assert doc.doc_type is DocumentType.PAYMENT_CONFIRMATION_BALANCE
    assert doc.doc_type_raw == suffix


@pytest.mark.parametrize(
    "suffix",
    ["INV-bal", "INV-bal2", "INV-bal3"],
)
def test_numbered_balance_invoice_suffixes_classify(suffix):
    doc = SourceDocument.from_filename(f"2025-11-07_WHSM_Comp_INV-26Q1RCS_{suffix}.pdf")
    assert doc.doc_type is DocumentType.BALANCE_INVOICE
    assert doc.doc_type_raw == suffix


@pytest.mark.parametrize(
    "suffix,expected",
    [
        ("INV-full", DocumentType.FULL_INVOICE),
        ("INV-unpaid", DocumentType.UNPAID_INVOICE),
        ("pconf-dep", DocumentType.PAYMENT_CONFIRMATION_DEPOSIT),
        ("pconf-full", DocumentType.PAYMENT_CONFIRMATION_FULL),
    ],
)
def test_components_specific_doc_types_classify(suffix, expected):
    # These only apply to Components -- Overhead/Freight-Bundling never
    # use them, but the parser must still recognize a real Components
    # filename using them.
    doc = SourceDocument.from_filename(f"2025-11-07_WHSM_Comp_INV-26Q1RCS_{suffix}.pdf")
    assert doc.doc_type is expected
    assert doc.doc_type_raw == suffix


@pytest.mark.parametrize(
    "suffix",
    ["INV-bal-paid", "INV-paid-bal", "inv-bal2-paid"],
)
def test_real_balance_invoice_suffix_variants_classify(suffix):
    # Real, already-filed Components filenames (2026-10-20) use these
    # one-off phrasings instead of the documented "INV-bal[N]" --
    # "INV-bal2-paid" already worked via the existing numbered-suffix
    # rule (digit right after "inv-bal"); "INV-bal-paid"/"INV-paid-bal"
    # needed an explicit alias since neither word order has a digit
    # immediately after "inv-bal" or "inv-paid".
    doc = SourceDocument.from_filename(f"2025-07-17_WHSM_Comp_INV-25Q4RPC26S-B02_{suffix}.pdf")
    assert doc.doc_type is DocumentType.BALANCE_INVOICE
    assert doc.doc_type_raw == suffix


@pytest.mark.parametrize("suffix", ["pconf-1", "pconf-2"])
def test_bare_numbered_pconf_classifies_as_balance_confirmation(suffix):
    # Real, already-filed Components filenames (2026-10-20): a balance
    # paid off across more than one wire gets pconf-1/pconf-2, with no
    # "-bal" qualifier at all -- the digit isn't immediately after
    # "pconf" (there's a hyphen), so the general numbered-suffix rule
    # doesn't fire; needed its own pattern.
    doc = SourceDocument.from_filename(f"2024-08-12_WHSM_Comp_INV-JUN24USQ4CRP_{suffix}.pdf")
    assert doc.doc_type is DocumentType.PAYMENT_CONFIRMATION_BALANCE
    assert doc.doc_type_raw == suffix


@pytest.mark.parametrize(
    "suffix,expected",
    [
        ("INV-pconf-dep", DocumentType.PAYMENT_CONFIRMATION_DEPOSIT),
        ("INV-pconf-bal1", DocumentType.PAYMENT_CONFIRMATION_BALANCE),
        ("INV-pconf-bal2", DocumentType.PAYMENT_CONFIRMATION_BALANCE),
    ],
)
def test_pconf_token_with_accidental_inv_prefix_classifies(suffix, expected):
    # Real, already-filed Components filenames (2026-10-20): a payment
    # confirmation's own token sometimes carries an accidental "INV-"
    # prefix meant for an invoice token instead -- "INV-pconf-dep",
    # "INV-pconf-bal1", "INV-pconf-bal2" (all three filed for the same
    # order, INV-25Q1SLV26QTINNERBOX-01). None of these start with a
    # recognized "pconf..." prefix as written, so they fell through to
    # OTHER before the "INV-" was stripped.
    doc = SourceDocument.from_filename(
        f"2025-03-06_WHSM_comp_INV-25Q1SLV26QTINNERBOX-01_{suffix}.pdf"
    )
    assert doc.doc_type is expected
    assert doc.doc_type_raw == suffix


def test_inv_paid_full_classifies_as_paid_invoice():
    # Real, already-filed Components filename (2026-10-20): a single
    # undivided order's one-shot invoice filed as "INV-paid-full" rather
    # than the plain "INV-paid" this module's docstring originally
    # assumed -- "INV-paid-full" falls through the ordinary "inv-paid"
    # prefix rule since the character right after "inv-paid" is "-", not
    # a digit.
    doc = SourceDocument.from_filename("2025-09-24_WHSM_Comp_INV-26Q1PKG_INV-paid-full.pdf")
    assert doc.doc_type is DocumentType.PAID_INVOICE
    assert doc.doc_type_raw == "INV-paid-full"


def test_inv_full_is_distinct_from_plain_inv_paid():
    # "INV-full" must not be swallowed by the "INV-paid" prefix -- they're
    # different DocumentType values with different meaning for Components
    # (a single, undivided payment vs. Overhead/Freight's blanket paid
    # assumption).
    full = SourceDocument.from_filename("2025-11-07_WHSM_Comp_INV-26Q1RCS_INV-full.pdf")
    paid = SourceDocument.from_filename("2025-11-07_WHSM_Comp_INV-26Q1RCS_INV-paid.pdf")
    assert full.doc_type is DocumentType.FULL_INVOICE
    assert paid.doc_type is DocumentType.PAID_INVOICE


def test_overhead_category_tag_from_real_filename():
    doc = SourceDocument.from_filename(
        "2025-09-29_WH_Over_Inspection-250930_INV-paid.pdf"
    )
    assert doc.vendor_abbrev == "WH"
    assert doc.category_tag == "Over"
    assert doc.doc_type is DocumentType.PAID_INVOICE


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

"""The Drive filename convention used throughout the workbook.

Every "Deposit invoice" / "Source" cell in 1 TRANSACTIONS, 2 FREIGHT and
3 COMPONENTS is a filename of the form::

    {date:YYYY-MM-DD}_{vendor_abbrev}_{category_tag}_{invoice_number}_{doc_type}.{ext}

e.g.::

    2025-01-15_WHSM_comp_INV-25Q1SLV26QTINNERBOX-01_INV-dep.pdf
    2024-12-26_FBSL_Frei-Bund_JG20241225E_INV-paid.pdf
    2025-06-11_FBSL_Frei-Bund_JG20250612E-Refurn_INV-refund.pdf
    2025-09-29_WH_Over_Inspection-250930_INV-paid.pdf
    2025-11-07_WHSM_Comp_INV-26Q1RCS_pconf-bal2.pdf

This is the join key between a file in Google Drive and a row in the cost
sheets. Component invoice numbers observed so far use hyphens, never
underscores, inside a single token -- the parser relies on that and will
raise ``ValueError`` rather than guess if a filename doesn't split into
exactly five underscore-delimited parts, so a non-conforming filename gets
flagged for a human instead of silently mis-parsed.

The doc-type token isn't always an exact match: a multi-payment invoice
carries a numbered suffix, e.g. ``pconf-bal1`` .. ``pconf-bal4`` for four
partial payment confirmations against one invoice. ``doc_type`` classifies
by prefix (so all four are still ``PAYMENT_CONFIRMATION``); ``doc_type_raw``
keeps the exact token so the distinction isn't lost.
"""

from __future__ import annotations

from datetime import date
from pathlib import PurePath

from pydantic import BaseModel, ConfigDict, field_validator

from .enums import DocumentType

_DOC_TYPE_PREFIXES = (
    ("inv-dep", DocumentType.DEPOSIT_INVOICE),
    ("inv-paid", DocumentType.PAID_INVOICE),
    ("inv-refund", DocumentType.REFUND_INVOICE),
    ("pconf", DocumentType.PAYMENT_CONFIRMATION),
)


def _classify_doc_type(token: str) -> DocumentType:
    lowered = token.lower()
    for prefix, doc_type in _DOC_TYPE_PREFIXES:
        if lowered == prefix or lowered.startswith(prefix + "-"):
            return doc_type
    return DocumentType.OTHER


class SourceDocument(BaseModel):
    """A parsed source-document filename."""

    model_config = ConfigDict(frozen=True)

    raw_filename: str
    doc_date: date
    vendor_abbrev: str
    category_tag: str
    invoice_number: str
    doc_type: DocumentType
    doc_type_raw: str
    extension: str

    @field_validator("vendor_abbrev", "category_tag", "invoice_number", "extension")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("must not be blank")
        return value

    @property
    def category_tag_normalized(self) -> str:
        """Case-insensitive form, since the workbook mixes 'comp'/'Comp'."""
        return self.category_tag.lower()

    @classmethod
    def from_filename(cls, filename: str) -> "SourceDocument":
        name = PurePath(filename).name
        parts = name.split("_")
        if len(parts) != 5:
            raise ValueError(
                f"expected 5 underscore-delimited parts "
                f"(date_vendor_category_invoice_doctype.ext), got {len(parts)}: {name!r}"
            )
        date_token, vendor_abbrev, category_tag, invoice_number, doctype_and_ext = parts

        try:
            doc_date = date.fromisoformat(date_token)
        except ValueError as exc:
            raise ValueError(f"could not parse date {date_token!r} in {name!r}") from exc

        if "." not in doctype_and_ext:
            raise ValueError(f"missing file extension in {name!r}")
        doctype_token, extension = doctype_and_ext.rsplit(".", 1)
        doc_type = _classify_doc_type(doctype_token)

        return cls(
            raw_filename=name,
            doc_date=doc_date,
            vendor_abbrev=vendor_abbrev,
            category_tag=category_tag,
            invoice_number=invoice_number,
            doc_type=doc_type,
            doc_type_raw=doctype_token,
            extension=extension,
        )

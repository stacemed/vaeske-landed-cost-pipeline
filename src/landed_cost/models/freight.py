"""2 FREIGHT -- the Shenzhen Linkhub DDP freight invoices and their
cube-based allocation across shipments and SKUs.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from .documents import SourceDocument
from .enums import Market


class FreightInvoiceRegister(BaseModel):
    """One row of 1 TRANSACTIONS section D / 2 FREIGHT section A.

    Some invoice numbers are refund/credit lines (e.g.
    'JG20250612E-Refurn') carrying a negative freight amount -- these are
    real invoices paid in 2025, not data errors, and must stay in the
    cash-basis total.
    """

    model_config = ConfigDict(frozen=True)

    invoice_number: str
    invoice_date: date
    paid_date: date
    freight_amount: Decimal
    bundling_packaging_amount: Decimal = Decimal(0)
    deposit_invoice: SourceDocument | None = None


class ShipmentAllocation(BaseModel):
    """One row of 2 FREIGHT section B: a single SKU within a single FBA
    shipment within a single freight invoice.

    ``shipment_freight`` is the total freight charge for this row's whole
    shipment (repeated on every row in the shipment, as in the workbook).
    The per-row allocated freight and $/unit are NOT stored here -- they
    depend on the other rows in the same shipment (this row's CBM share of
    the shipment's total CBM) and must be computed with
    ``allocate_shipment_freight`` over the full set of rows for a period,
    never hand-entered, or the allocation stops summing to the invoice
    total (8 CONTROL checks 1-2).
    """

    model_config = ConfigDict(frozen=True)

    invoice_number: str
    fba_shipment_id: str
    lh_ref: str
    destination: str
    market: Market
    sku: str
    units: Decimal
    cbm: Decimal
    shipment_freight: Decimal
    source: str = "packing list"


def allocate_shipment_freight(
    rows: list[ShipmentAllocation],
) -> list[Decimal]:
    """Allocate each shipment's freight across its rows by CBM share.

    Mirrors 2 FREIGHT section B columns J-N: rows are grouped by
    (invoice_number, fba_shipment_id); each row's allocated freight is
    ``shipment_freight * (row.cbm / sum(cbm for rows in the same shipment))``.
    Returns allocated-freight amounts in the same order as ``rows``.
    """
    shipment_cbm_totals: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for row in rows:
        shipment_cbm_totals[(row.invoice_number, row.fba_shipment_id)] += row.cbm

    allocated: list[Decimal] = []
    for row in rows:
        total_cbm = shipment_cbm_totals[(row.invoice_number, row.fba_shipment_id)]
        share = row.cbm / total_cbm if total_cbm else Decimal(0)
        allocated.append(row.shipment_freight * share)
    return allocated

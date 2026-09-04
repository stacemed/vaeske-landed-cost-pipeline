"""4 BUNDLING -- assembly labour and packing consumables billed alongside
freight on the same Linkhub invoices, but a distinct QBO cost category.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class BundlingRate(BaseModel):
    """One row of 4 BUNDLING section A: SKU -> $/unit rate.

    Set from the prep sheets -- a blue "input" cell in the workbook's own
    convention, not derived.
    """

    model_config = ConfigDict(frozen=True)

    sku: str
    rate_per_unit: Decimal


class BundlingAllocation(BaseModel):
    """One row of 4 BUNDLING section B.

    Mirrors a ShipmentAllocation row (same invoice/shipment/sku/units) with
    the matching BundlingRate applied. Kept as a distinct model rather than
    a field on ShipmentAllocation because bundling and freight are
    different QBO cost categories that happen to share source invoices.
    """

    model_config = ConfigDict(frozen=True)

    invoice_number: str
    fba_shipment_id: str
    sku: str
    units: Decimal
    rate_per_unit: Decimal

    @property
    def bundling_amount(self) -> Decimal:
        return self.units * self.rate_per_unit

"""6 UNIT COST section B -- the landed unit cost by SKU and market.

This and 7 YEAR-END are, per the workbook's own READ ME, the sheets with
the final derived numbers of most interest for taxes.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from .enums import FreightBasis, Market


class UnitCostLine(BaseModel):
    """One row of 6 UNIT COST section B.

    ``components_cost`` = BOM x ComponentPriceSummary.price_used, summed
    over the SKU's bill of materials. ``freight_cost`` is either the actual
    allocated freight for this SKU/market this period, or the market-rate
    CBM fallback if this SKU/market had no shipment -- ``freight_basis``
    records which, matching 6 UNIT COST column H.
    """

    model_config = ConfigDict(frozen=True)

    sku: str
    market: Market
    components_cost: Decimal
    bundling_cost: Decimal
    freight_cost: Decimal
    freight_basis: FreightBasis
    overhead_cost: Decimal

    @property
    def landed_cost_per_unit(self) -> Decimal:
        return (
            self.components_cost
            + self.bundling_cost
            + self.freight_cost
            + self.overhead_cost
        )

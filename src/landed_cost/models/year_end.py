"""7 YEAR-END -- year-end inventory valuation, the other sheet with final
tax-facing numbers.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from .enums import Market


class YearEndFinishedGoods(BaseModel):
    """One row of 7 YEAR-END section A.

    ``value`` = total_units * landed_cost_per_unit (from the matching
    UnitCostLine for this sku/market).
    """

    model_config = ConfigDict(frozen=True)

    sku: str
    market: Market
    fba_units: Decimal = Decimal(0)
    awd_units: Decimal = Decimal(0)
    threepl_units: Decimal = Decimal(0)
    landed_cost_per_unit: Decimal

    @property
    def total_units(self) -> Decimal:
        return self.fba_units + self.awd_units + self.threepl_units

    @property
    def value(self) -> Decimal:
        return self.total_units * self.landed_cost_per_unit


class YearEndComponentInventory(BaseModel):
    """One row of 7 YEAR-END section B.

    Valued at component cost only (ComponentPriceSummary.price_used) --
    freight/bundling/overhead don't apply to raw, unbuilt component stock.
    """

    model_config = ConfigDict(frozen=True)

    component: str
    code: str
    units_on_hand: Decimal
    unit_price: Decimal

    @property
    def value(self) -> Decimal:
        return self.units_on_hand * self.unit_price


class YearEndSummary(BaseModel):
    """7 YEAR-END section C -- the total, reconciled against what was last
    given to the accountant.
    """

    model_config = ConfigDict(frozen=True)

    finished_goods_total: Decimal
    china_components_total: Decimal
    previously_given_total: Decimal

    @property
    def total(self) -> Decimal:
        return self.finished_goods_total + self.china_components_total

    @property
    def difference_from_previously_given(self) -> Decimal:
        return self.total - self.previously_given_total

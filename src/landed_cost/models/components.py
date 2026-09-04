"""3 COMPONENTS -- component purchases and the weighted-average price they
feed into the bill of materials, plus the invoice-level register also shown
on 1 TRANSACTIONS section C.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from .documents import SourceDocument


class ComponentPurchaseLine(BaseModel):
    """One line of 3 COMPONENTS section A.

    ``line_total`` = quantity x unit_price. ``weighted_invoice_adjustment``
    spreads that invoice's total adjustment (exchange fees, credits) across
    its lines by value share: ``invoice_adjustment * (line_total /
    invoice_line_total)``. ``adjusted_unit_price`` = (line_total +
    weighted_invoice_adjustment) / quantity, falling back to the plain
    ``unit_price`` when there's no invoice number or zero quantity.
    ``year`` is the order year, used to split 2024 vs. 2025 in
    ComponentPriceSummary -- a component ordered in 2025 but not yet used
    in production shouldn't distort the cost of units already shipped.
    """

    model_config = ConfigDict(frozen=True)

    order_date: date
    invoice_number: str | None
    component: str
    quantity: Decimal
    unit_price: Decimal
    weighted_invoice_adjustment: Decimal = Decimal(0)
    verified: bool = False

    @property
    def line_total(self) -> Decimal:
        return self.quantity * self.unit_price

    @property
    def adjusted_unit_price(self) -> Decimal:
        if not self.invoice_number or self.quantity == 0:
            return self.unit_price
        return (self.line_total + self.weighted_invoice_adjustment) / self.quantity

    @property
    def adjusted_line_total(self) -> Decimal:
        return self.quantity * self.adjusted_unit_price

    @property
    def year(self) -> int:
        return self.order_date.year


class ComponentInvoiceRegister(BaseModel):
    """One row of 1 TRANSACTIONS section C / the invoice-level rollup that
    ComponentPurchaseLine.weighted_invoice_adjustment is derived from.
    """

    model_config = ConfigDict(frozen=True)

    invoice_number: str
    invoice_date: date
    balance_paid_date: date
    total_order_amount: Decimal
    invoice_adjustments: Decimal = Decimal(0)
    deposit_invoice: SourceDocument | None = None


class ComponentPriceSummary(BaseModel):
    """One row of 3 COMPONENTS section B -- the weighted-average price used
    in the bill of materials.

    ``price_used`` follows the workbook's rule (column I): use this year's
    weighted average if any of this component was bought this year,
    otherwise fall back to last year's weighted average.
    """

    model_config = ConfigDict(frozen=True)

    component: str
    current_year_qty: Decimal
    current_year_spend: Decimal
    prior_year_qty: Decimal
    prior_year_spend: Decimal

    @property
    def current_year_weighted_avg(self) -> Decimal | None:
        if self.current_year_qty == 0:
            return None
        return self.current_year_spend / self.current_year_qty

    @property
    def prior_year_weighted_avg(self) -> Decimal | None:
        if self.prior_year_qty == 0:
            return None
        return self.prior_year_spend / self.prior_year_qty

    @property
    def price_used(self) -> Decimal:
        current = self.current_year_weighted_avg
        if current is not None:
            return current
        prior = self.prior_year_weighted_avg
        if prior is not None:
            return prior
        raise ValueError(f"no purchases in either year for component {self.component!r}")

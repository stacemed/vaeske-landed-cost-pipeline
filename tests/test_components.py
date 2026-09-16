from datetime import date
from decimal import Decimal

import pytest

from landed_cost.models import ComponentPriceSummary, ComponentPurchaseLine


def test_price_used_prefers_current_year_weighted_average():
    # 3 COMPONENTS row 68 (Rack): real 2025 vs 2024 totals from the workbook.
    rack = ComponentPriceSummary(
        component="Rack",
        current_year_qty=Decimal(9500),
        current_year_spend=Decimal("45637.052"),
        prior_year_qty=Decimal(14000),
        prior_year_spend=Decimal(67850),
    )

    assert rack.current_year_weighted_avg.quantize(Decimal("0.00000001")) == Decimal(
        "4.80390021"
    )
    assert rack.price_used == rack.current_year_weighted_avg


def test_price_used_falls_back_to_prior_year_when_nothing_bought_this_year():
    summary = ComponentPriceSummary(
        component="Widget",
        current_year_qty=Decimal(0),
        current_year_spend=Decimal(0),
        prior_year_qty=Decimal(100),
        prior_year_spend=Decimal(250),
    )
    assert summary.current_year_weighted_avg is None
    assert summary.price_used == Decimal("2.5")


def test_price_used_raises_when_never_purchased():
    summary = ComponentPriceSummary(
        component="Ghost",
        current_year_qty=Decimal(0),
        current_year_spend=Decimal(0),
        prior_year_qty=Decimal(0),
        prior_year_spend=Decimal(0),
    )
    with pytest.raises(ValueError):
        summary.price_used


def test_purchase_line_without_invoice_number_uses_plain_unit_price():
    line = ComponentPurchaseLine(
        order_date=date(2024, 10, 9),
        invoice_number=None,
        component="12 QT Master Carton",
        quantity=Decimal(2500),
        unit_price=Decimal("1.55"),
    )
    assert line.line_total == Decimal("3875.00")
    assert line.adjusted_unit_price == Decimal("1.55")
    assert line.year == 2024


def test_purchase_line_spreads_weighted_invoice_adjustment():
    # 3 COMPONENTS row 67: INV-25Q4RPC26S-B01 line, $94.60 total invoice
    # adjustment spread across its lines by value share.
    line = ComponentPurchaseLine(
        order_date=date(2025, 6, 8),
        invoice_number="INV-25Q4RPC26S-B01",
        component="12 QT Container",
        quantity=Decimal(1000),
        unit_price=Decimal("4.105"),
        weighted_invoice_adjustment=Decimal("10.00"),
    )
    assert line.line_total == Decimal("4105.000")
    assert line.adjusted_line_total == line.line_total + Decimal("10.00")
    assert line.adjusted_unit_price == line.adjusted_line_total / line.quantity

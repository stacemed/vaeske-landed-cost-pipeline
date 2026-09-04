from decimal import Decimal

from landed_cost.models import FreightBasis, Market, UnitCostLine


def test_landed_cost_per_unit_sums_all_four_layers():
    # 6 UNIT COST row 19, real workbook values: SV-CLR-12a / US.
    line = UnitCostLine(
        sku="SV-CLR-12a",
        market=Market.US,
        components_cost=Decimal("11.5192975"),
        bundling_cost=Decimal("0.8981842818"),
        freight_cost=Decimal("3.827207095"),
        freight_basis=FreightBasis.ACTUAL,
        overhead_cost=Decimal("1.187699294"),
    )
    assert line.landed_cost_per_unit.quantize(Decimal("0.000001")) == Decimal(
        "17.432388"
    )


def test_market_rate_fallback_is_recorded_on_the_line():
    line = UnitCostLine(
        sku="SV-CLR-12a",
        market=Market.CA,
        components_cost=Decimal(10),
        bundling_cost=Decimal(1),
        freight_cost=Decimal(2),
        freight_basis=FreightBasis.MARKET_RATE,
        overhead_cost=Decimal(1),
    )
    assert line.freight_basis is FreightBasis.MARKET_RATE
    assert line.landed_cost_per_unit == Decimal(14)

from decimal import Decimal

from landed_cost.models import Market, YearEndComponentInventory, YearEndFinishedGoods, YearEndSummary


def test_finished_goods_value_matches_workbook_row_6():
    # 7 YEAR-END row 6, real workbook values: SV-CLR-12a / US.
    row = YearEndFinishedGoods(
        sku="SV-CLR-12a",
        market=Market.US,
        fba_units=Decimal(74),
        awd_units=Decimal(48),
        threepl_units=Decimal(0),
        landed_cost_per_unit=Decimal("17.43238818"),
    )
    assert row.total_units == Decimal(122)
    assert row.value.quantize(Decimal("0.01")) == Decimal("2126.75")


def test_component_inventory_value_is_component_cost_only():
    row = YearEndComponentInventory(
        component="Rack",
        code="RACK",
        units_on_hand=Decimal(5012),
        unit_price=Decimal("4.80390021"),
    )
    assert row.value.quantize(Decimal("0.01")) == (
        Decimal(5012) * Decimal("4.80390021")
    ).quantize(Decimal("0.01"))


def test_summary_difference_from_previously_given():
    # 7 YEAR-END section C, real workbook values.
    summary = YearEndSummary(
        finished_goods_total=Decimal("85210.83"),
        china_components_total=Decimal("96854.39"),
        previously_given_total=Decimal("162050.40"),
    )
    assert summary.total.quantize(Decimal("0.01")) == Decimal("182065.22")
    assert summary.difference_from_previously_given.quantize(
        Decimal("0.01")
    ) == Decimal("20014.82")

from decimal import Decimal

from landed_cost.models import OverheadAllocation
from landed_cost.models.overhead import allocate_overhead_pool, duplicate_skus

# 5 OVERHEAD section B, in full -- real workbook data.
_ROWS = [
    ("SV-CLR-12a", 498, "6.17", "591.4742483"),
    ("SV-CLRS-12a", 2010, "7.17", "2774.192206"),
    ("SV-CLS-12", 0, "5.17", "0"),
    ("SV-CLR-12-EU", 156, "6.17", "185.2810898"),
    ("SV-CLR-26", 430, "8.5", "703.5722721"),
    ("SV-CLRS-26", 1880, "9.5", "3437.975589"),
    ("SV-CLS-26", 1280, "5.5", "1355.170669"),
    ("SV-CLS-12-26", 578, "8.5", "945.7320308"),
    ("SV-CLRS-12-26", 548, "14.5", "1529.571894"),
    ("SV-CLRS-26-EU", 0, "9.5", "0"),
]
_POOL_TOTAL = Decimal("11522.97")


def test_allocate_overhead_pool_matches_workbook_totals():
    rows = [
        OverheadAllocation(
            sku=sku,
            units_shipped=Decimal(units),
            components_per_unit=Decimal(per_unit),
        )
        for sku, units, per_unit, _ in _ROWS
    ]

    totals = allocate_overhead_pool(_POOL_TOTAL, rows)

    for (sku, _, _, expected), total in zip(_ROWS, totals):
        assert total.quantize(Decimal("0.01")) == Decimal(expected).quantize(
            Decimal("0.01")
        ), sku

    # 8 CONTROL check 6: overhead absorbed must equal the pool.
    assert sum(totals).quantize(Decimal("0.01")) == _POOL_TOTAL


def test_empty_pool_allocates_nothing_without_dividing_by_zero():
    rows = [OverheadAllocation(sku="X", units_shipped=Decimal(0), components_per_unit=Decimal(1))]
    assert allocate_overhead_pool(Decimal(1000), rows) == [Decimal(0)]


def test_duplicate_skus_are_detected():
    rows = [
        OverheadAllocation(sku="A", units_shipped=Decimal(1), components_per_unit=Decimal(1)),
        OverheadAllocation(sku="A", units_shipped=Decimal(1), components_per_unit=Decimal(1)),
        OverheadAllocation(sku="B", units_shipped=Decimal(1), components_per_unit=Decimal(1)),
    ]
    assert duplicate_skus(rows) == ["A"]

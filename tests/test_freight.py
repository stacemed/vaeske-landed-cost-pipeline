from decimal import Decimal

from landed_cost.models import Market, ShipmentAllocation
from landed_cost.models.freight import allocate_shipment_freight


def _row(sku: str, units: str, cbm: str) -> ShipmentAllocation:
    return ShipmentAllocation(
        invoice_number="JG20241225E",
        fba_shipment_id="FBA18PNZV1DQ",
        lh_ref="LH01520380",
        destination="DEN2",
        market=Market.US,
        sku=sku,
        units=Decimal(units),
        cbm=Decimal(cbm),
        shipment_freight=Decimal("1201.2"),
    )


def test_allocate_shipment_freight_matches_workbook_shipment_fba18pnzv1dq():
    # 2 FREIGHT rows 19-22, real invoice JG20241225E / shipment FBA18PNZV1DQ.
    rows = [
        _row("SV-CLRS-12-26", "14", "0.709"),
        _row("SV-CLRS-26", "24", "1.215"),
        _row("SV-CLS-12-26", "2", "0.102"),
        _row("SV-CLS-26", "46", "2.329"),
    ]

    allocated = allocate_shipment_freight(rows)

    expected = [
        Decimal("195.56"),
        Decimal("335.12"),
        Decimal("28.13"),
        Decimal("642.39"),
    ]
    rounded = [amount.quantize(Decimal("0.01")) for amount in allocated]
    assert rounded == expected

    # Must sum back to the shipment's freight charge -- this is 8 CONTROL
    # check 1/2.
    assert sum(allocated).quantize(Decimal("0.01")) == Decimal("1201.20")


def test_allocation_splits_across_shipments_independently():
    shipment_a = ShipmentAllocation(
        invoice_number="INV-1",
        fba_shipment_id="SHIP-A",
        lh_ref="LH-A",
        destination="DEN2",
        market=Market.US,
        sku="SKU-A",
        units=Decimal(10),
        cbm=Decimal(1),
        shipment_freight=Decimal(100),
    )
    shipment_b = ShipmentAllocation(
        invoice_number="INV-1",
        fba_shipment_id="SHIP-B",
        lh_ref="LH-B",
        destination="FAT2",
        market=Market.US,
        sku="SKU-B",
        units=Decimal(10),
        cbm=Decimal(3),
        shipment_freight=Decimal(300),
    )

    allocated = allocate_shipment_freight([shipment_a, shipment_b])

    # Each is the sole row in its shipment, so it absorbs the full charge
    # regardless of the other shipment's amount.
    assert allocated == [Decimal(100), Decimal(300)]


def test_zero_total_cbm_does_not_divide_by_zero():
    row = ShipmentAllocation(
        invoice_number="INV-1",
        fba_shipment_id="SHIP-A",
        lh_ref="LH-A",
        destination="DEN2",
        market=Market.US,
        sku="SKU-A",
        units=Decimal(10),
        cbm=Decimal(0),
        shipment_freight=Decimal(100),
    )
    assert allocate_shipment_freight([row]) == [Decimal(0)]

from datetime import date
from decimal import Decimal

from landed_cost.models import (
    SKU,
    BundlingAllocation,
    BundlingRate,
    Category,
    ComponentReference,
    InventoryTransaction,
    Market,
    VendorReference,
)


def test_sku_bill_of_materials_can_be_fractional():
    # 6 UNIT COST row 10 (SV-CLR-26): shares half a 26 QT Master Carton.
    sku = SKU(
        code="SV-CLR-26",
        markets=(Market.US,),
        bill_of_materials={
            "Rack": Decimal(2),
            "26 QT Container": Decimal(1),
            "26 QT Master Carton": Decimal("0.5"),
        },
        cbm_per_unit=Decimal("0.050460"),
        components_per_unit=Decimal("8.5"),
    )
    assert sku.bill_of_materials["26 QT Master Carton"] == Decimal("0.5")
    assert Market.US in sku.markets


def test_vendor_reference_carries_filename_abbreviation():
    vendor = VendorReference(
        name="Weimin Huang/Shenzhen Minzhi",
        abbreviation="WHSM",
        category=Category.COMPONENTS,
    )
    assert vendor.abbreviation == "WHSM"


def test_component_reference_is_just_a_name():
    assert ComponentReference(name="Rack").name == "Rack"


def test_inventory_transaction_round_trips_a_real_row():
    # 1 TRANSACTIONS row 8.
    txn = InventoryTransaction(
        category=Category.COMPONENTS,
        paid_date=date(2025, 1, 15),
        payee="WT FED#03350 COMMUNITY FEDERAL /FTR/BNF=Shenzhen Mi",
        invoice_number="INV-25Q1SLV26QTINNERBOX-01",
        amount=Decimal("5849.60"),
    )
    assert txn.category is Category.COMPONENTS
    assert txn.amount == Decimal("5849.60")


def test_bundling_allocation_amount():
    rate = BundlingRate(sku="SV-CLR-26", rate_per_unit=Decimal("0.55"))
    allocation = BundlingAllocation(
        invoice_number="JG20241225E",
        fba_shipment_id="FBA18PM1Z13K",
        sku=rate.sku,
        units=Decimal(40),
        rate_per_unit=rate.rate_per_unit,
    )
    assert allocation.bundling_amount == Decimal("22.00")

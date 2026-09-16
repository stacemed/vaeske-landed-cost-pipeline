"""9 REFERENCES and the BOM grid on 6 UNIT COST section A -- master data.

These are the lookups everything else joins against: which components
exist, which vendor/abbreviation supplies what, and each SKU's bill of
materials, CBM, and overhead weighting.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from .enums import Category, Market


class ComponentReference(BaseModel):
    """A canonical component name, e.g. 'Rack', '26 QT Inner Box'."""

    model_config = ConfigDict(frozen=True)

    name: str


class VendorReference(BaseModel):
    """A vendor and the filename abbreviation it's tagged with.

    E.g. Weimin Huang / Shenzhen Minzhi -> 'WHSM'; FBA Bee / Shenzhen
    Linkhub -> 'FBSL'. ``category`` is the QBO category this vendor's spend
    normally lands in, used to sanity-check parsed SourceDocuments.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    abbreviation: str
    category: Category


class SKU(BaseModel):
    """A sellable SKU: markets, bill of materials, and allocation weights.

    ``bill_of_materials`` maps component name -> quantity per unit (may be
    fractional, e.g. 0.5 of a shared master carton). ``cbm_per_unit`` is the
    fallback freight-rate basis used when this SKU/market had no shipment
    in the period (6 UNIT COST column E, "market rate" case).
    ``components_per_unit`` is the weighted count used to allocate overhead
    (5 OVERHEAD section B) -- deliberately distinct from
    ``len(bill_of_materials)`` since it's a hand-set weighting, not a
    literal part count.
    """

    model_config = ConfigDict(frozen=True)

    code: str
    markets: tuple[Market, ...]
    bill_of_materials: dict[str, Decimal] = Field(default_factory=dict)
    cbm_per_unit: Decimal | None = None
    components_per_unit: Decimal | None = None

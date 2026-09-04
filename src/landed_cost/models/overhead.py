"""5 OVERHEAD -- Weimin Huang's inspection, coordination and the annual
production bonus, allocated across SKUs by weighted component count.

Component orders routed through him are excluded here -- those are
Category.COMPONENTS spend, even though he's the same payee.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class OverheadTransaction(BaseModel):
    """One row of 5 OVERHEAD section A."""

    model_config = ConfigDict(frozen=True)

    paid_date: date
    description: str
    invoice_reference: str
    amount: Decimal


class OverheadAllocation(BaseModel):
    """One row of 5 OVERHEAD section B, before the pool is divided.

    ``components_per_unit`` comes from SKU reference data, not a literal
    BOM line count -- it's a hand-set weighting reflecting how much
    coordination/inspection effort a SKU's assembly needs.
    """

    model_config = ConfigDict(frozen=True)

    sku: str
    units_shipped: Decimal
    components_per_unit: Decimal

    @property
    def weighted_units(self) -> Decimal:
        return self.units_shipped * self.components_per_unit


def allocate_overhead_pool(
    pool_total: Decimal,
    rows: list[OverheadAllocation],
) -> list[Decimal]:
    """Divide the overhead pool across SKUs by weighted-unit share.

    Mirrors 5 OVERHEAD section B columns E-F: each SKU's $/unit =
    ``pool_total / sum(weighted_units) * components_per_unit``, and its
    total = units_shipped * that $/unit. Returns total overhead $ per row,
    in the same order as ``rows``.
    """
    total_weighted_units = sum((row.weighted_units for row in rows), Decimal(0))
    if total_weighted_units == 0:
        return [Decimal(0) for _ in rows]

    totals: list[Decimal] = []
    for row in rows:
        per_unit = pool_total / total_weighted_units * row.components_per_unit
        totals.append(row.units_shipped * per_unit)
    return totals


def _group_key(row: OverheadAllocation) -> str:
    return row.sku


# Re-exported for callers that want to sanity-check grouping (e.g. no
# duplicate SKU rows before allocating).
def duplicate_skus(rows: list[OverheadAllocation]) -> list[str]:
    seen: dict[str, int] = defaultdict(int)
    for row in rows:
        seen[_group_key(row)] += 1
    return [sku for sku, count in seen.items() if count > 1]

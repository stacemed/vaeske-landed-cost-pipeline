"""1 TRANSACTIONS section A -- every 2025 QBO Inventory addition, cash basis."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from .enums import Category


class InventoryTransaction(BaseModel):
    """One row of 1 TRANSACTIONS section A.

    This is the control total every other sheet ties back to (8 CONTROL
    checks 7-10). ``paid_date`` is the cash-basis date -- the date the
    wire/card cleared, not the invoice date -- per the workbook's stated
    basis: every category ties directly to the QBO Inventory account with
    no bridging.
    """

    model_config = ConfigDict(frozen=True)

    category: Category
    paid_date: date
    payee: str
    invoice_number: str
    amount: Decimal

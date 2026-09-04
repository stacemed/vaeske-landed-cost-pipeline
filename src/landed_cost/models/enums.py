from enum import Enum


class Category(str, Enum):
    """The three QBO Inventory account categories from 1 TRANSACTIONS.

    Do not add a fourth without checking QBO's chart of accounts first --
    8 CONTROL reconciles against exactly these three.
    """

    COMPONENTS = "Components"
    FREIGHT_BUNDLING_PACKAGING = "Freight / bundling / packaging"
    OVERHEAD = "Overhead"


class Market(str, Enum):
    US = "US"
    CA = "CA"
    EU = "EU"


class DocumentType(str, Enum):
    """The doc-type suffix on a source-document filename, e.g. ``INV-dep``."""

    DEPOSIT_INVOICE = "INV-dep"
    PAID_INVOICE = "INV-paid"
    REFUND_INVOICE = "INV-refund"
    PAYMENT_CONFIRMATION = "pconf"
    OTHER = "other"


class FreightBasis(str, Enum):
    """How a UnitCostLine's freight-in figure was derived (6 UNIT COST col H)."""

    ACTUAL = "actual"
    MARKET_RATE = "market rate"


class CheckStatus(str, Enum):
    """8 CONTROL column F status, from the difference thresholds."""

    OK = "OK"
    REVIEW = "REVIEW"
    CHECK = "CHECK"

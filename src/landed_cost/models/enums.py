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
    """The doc-type suffix on a source-document filename, e.g. ``INV-dep``.

    Overhead and Freight-Bundling use a simple three-way split: an
    invoice is assumed paid unless its text says otherwise (``INV-paid``,
    ``INV-refund``) and a payment confirmation is always bare ``pconf``.

    Components tracks payment status per installment instead, since a
    single order is routinely split into a deposit and one or more
    balance payments: ``INV-dep`` / ``INV-bal`` / ``INV-full`` for
    the invoice itself, ``pconf-dep`` / ``pconf-bal`` / ``pconf-full``
    for its payment confirmation, and ``INV-unpaid`` for an invoice known
    to be outstanding (never guessed automatically -- the invoice
    document alone can't prove payment status either way, only a human
    checking against a separate payment confirmation or bank record
    can). A second or later balance payment against the same order gets
    a number appended directly (no separating hyphen): ``INV-bal2``,
    ``pconf-bal3`` -- the first balance stays unnumbered. Confirmed
    against the real convention 2026-09-15; ``FULL_INVOICE`` corrected
    from ``INV-paid-full`` to ``INV-full`` 2026-09-15 after the business
    owner used "INV-full" consistently while manually confirming real
    files -- the payment-confirmation counterpart stays ``pconf-full``.
    """

    DEPOSIT_INVOICE = "INV-dep"
    BALANCE_INVOICE = "INV-bal"
    FULL_INVOICE = "INV-full"
    UNPAID_INVOICE = "INV-unpaid"
    PAID_INVOICE = "INV-paid"
    REFUND_INVOICE = "INV-refund"
    PAYMENT_CONFIRMATION = "pconf"
    PAYMENT_CONFIRMATION_DEPOSIT = "pconf-dep"
    PAYMENT_CONFIRMATION_BALANCE = "pconf-bal"
    PAYMENT_CONFIRMATION_FULL = "pconf-full"
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

# Data model

This describes the Python data model in `src/landed_cost/models/` and how each
entity maps back to the workbook we're automating
(`2025 UNIT COST DERIVATION — VAESKE / JOHN GRATTAN`, currently a Google Sheet
exported to xlsx for the accountant).

The model exists to make the workbook's logic explicit and testable in code
*before* any Drive/Sheets/PDF integration is built. It intentionally mirrors
the workbook's own structure (same categories, same sheet-to-sheet
relationships) rather than redesigning the accounting — the workbook is the
system of record and the tax-facing artifact; Python is what keeps it fed.

## Why this shape

The workbook has one big organizing idea, stated on its `READ ME` tab:

> One sheet per cost input, each carrying its own source detail AND its own
> summary, so it stands alone and reconciles to the transactions sheet
> without reference to anything else.

So the data model has one module per cost input (`transactions`, `freight`,
`components`, `bundling`, `overhead`), plus the three sheets that consume
them (`reference` for the BOM/SKU master data, `unit_cost`, `year_end`), plus
`control` for the tie-out checks, plus `documents` for the Drive filename
convention that links every row back to a source PDF.

Money fields use `Decimal`, not `float` — this feeds tax figures, and
spreadsheet-style binary-float rounding has no place in it. Dates are
`datetime.date`. Everything is a `pydantic.BaseModel` so a parser (PDF
extractor, Sheets reader) gets validation for free and a clear error at the
row that's wrong, instead of a silently bad number downstream.

## Basis and conventions carried over from the workbook

- **Cash basis.** Every model that represents a transaction records the date
  it was *paid*, not invoiced — that's what ties to QuickBooks. Where the
  workbook also needs the invoice date (e.g. to compute payment terms or
  to know which production year a component belongs to), both dates are
  kept as separate fields.
- **Three top-level categories** (`Category` enum): `COMPONENTS`,
  `FREIGHT_BUNDLING_PACKAGING`, `OVERHEAD`. These are the exact QBO
  Inventory account categories from `1 TRANSACTIONS` section A — do not add
  a fourth without checking QBO's chart of accounts first, or the
  reconciliation in `8 CONTROL` breaks.
- **Freight is allocated by cube (CBM)**, not by value or unit count. Each
  shipment's freight charge is split across the SKUs in it in proportion to
  the volume (CBM) they occupied. See `ShipmentAllocation`.
- **Bundling is a flat per-SKU rate** set from the prep sheets (assembly
  labour + consumables billed alongside freight on the same Linkhub
  invoices, but tracked as a separate cost category).
- **Overhead is allocated by weighted component count per unit**
  (`components_per_unit` on `SKU`), not evenly per unit — a SKU built from
  more parts absorbs more of Weimin Huang's coordination/inspection cost.
- **Component cost uses a weighted-average price**, split 2024 vs. 2025 by
  the invoice's order date, so a component ordered in 2025 that hasn't been
  used in production yet doesn't distort the price of units actually
  shipped this year (built from older stock).

## Entities

### `documents.SourceDocument` (`documents.py`)

Parses the Drive filename convention visible throughout the workbook, e.g.:

```
2025-01-15_WHSM_comp_INV-25Q1SLV26QTINNERBOX-01_INV-dep.pdf
2024-12-26_FBSL_Frei-Bund_JG20241225E_INV-paid.pdf
2025-06-11_FBSL_Frei-Bund_JG20250612E-Refurn_INV-refund.pdf
```

Fields: `doc_date`, `vendor_abbrev` (e.g. `WHSM`, `FBSL` — see
`VendorReference`), `category_tag` (free text as written, e.g. `comp`,
`Comp`, `Frei-Bund` — casing is inconsistent in practice, so comparisons are
case-insensitive), `invoice_number`, `doc_type`
(`DocumentType.DEPOSIT_INVOICE` / `PAID_INVOICE` / `REFUND_INVOICE` /
`PAYMENT_CONFIRMATION` / `OTHER`), and `extension`.

This is the join key between a file sitting in Google Drive and a row in
`1 TRANSACTIONS` / `2 FREIGHT` / `3 COMPONENTS` (the "Deposit invoice" /
"Source" columns in those sheets already store exactly these filenames).

### `transactions.InventoryTransaction` (`transactions.py`)

Mirrors `1 TRANSACTIONS` section A, one row per QBO Inventory addition:
`category`, `paid_date`, `payee`, `invoice_number`, `amount`. This is the
control total every other sheet ties back to (`8 CONTROL`, checks 7–10).

### `components.py`

- `ComponentPurchaseLine` — one line of `3 COMPONENTS` section A: order
  date, invoice number, component name, quantity, unit price, plus the
  derived adjustment fields (`weighted_invoice_adjustment`,
  `adjusted_unit_price`) that spread a component invoice's total
  adjustments/exchange fees back across its lines by value share, and a
  `verified` flag (workbook column K).
- `ComponentInvoiceRegister` — one row of `1 TRANSACTIONS` section C /
  `3 COMPONENTS`'s invoice-level rollup: invoice number, invoice date,
  balance-paid date, total order amount (incl. exchange fees), invoice
  adjustments, and the deposit-invoice `SourceDocument` filename.
- `ComponentPriceSummary` — one row of `3 COMPONENTS` section B: the
  weighted-average price per component, split 2025 vs. 2024 qty/spend, with
  `price_used` following the workbook's rule (use this year's weighted
  average if any was bought this year, else fall back to last year's).

### `freight.py`

- `FreightInvoiceRegister` — one row of `1 TRANSACTIONS` section D /
  `2 FREIGHT` section A: invoice number, invoice date, paid date, freight
  amount, bundling/packaging amount, deposit-invoice filename. Note some
  invoice numbers are refund/credit lines (e.g. `JG20250612E-Refurn`) with a
  negative amount — these are real invoices, not errors.
- `ShipmentAllocation` — one row of `2 FREIGHT` section B: the finest-grained
  freight record, one row per SKU per FBA shipment. Carries `fba_shipment_id`,
  `lh_ref` (Linkhub reference), destination, market, SKU, units, CBM, and the
  derived `freight_allocated` (shipment freight × this row's CBM share of the
  shipment's total CBM). `shipment_cbm` and `share` are computed properties,
  not stored — they must always be derived from the sibling rows in the same
  shipment, never hand-entered, or the allocation stops summing to the
  invoice total (`8 CONTROL` check 1/2).

### `bundling.py`

- `BundlingRate` — one row of `4 BUNDLING` section A: SKU → $/unit rate,
  set from the prep sheets (a blue "input" cell in the workbook's own
  convention).
- `BundlingAllocation` — one row of `4 BUNDLING` section B: mirrors a
  `ShipmentAllocation` row (same invoice/shipment/SKU/units) with the rate
  applied. Kept as a distinct model rather than a field on
  `ShipmentAllocation` because bundling and freight are different QBO cost
  categories that happen to share source invoices, per the workbook's own
  design note.

### `overhead.py`

- `OverheadTransaction` — one row of `5 OVERHEAD` section A: date,
  description, invoice/reference, amount. Filtered from `1 TRANSACTIONS` by
  `Category.OVERHEAD`; explicitly excludes component orders routed through
  Weimin Huang (those are components, not overhead, even though he's the
  same payee).
- `OverheadAllocation` — one row of `5 OVERHEAD` section B: SKU, units
  shipped, `components_per_unit` (from `SKU` reference data), the derived
  weighted units, and the resulting $/unit and total — the overhead pool
  divided across SKUs by component-count weight, not evenly.

### `reference.py`

Master/reference data that the cost sheets look up against, from
`9 REFERENCES` and the BOM grid on `6 UNIT COST` section A:

- `ComponentReference` — canonical component names (e.g. `Rack`,
  `26 QT Inner Box`).
- `VendorReference` — vendor name, abbreviation (`FBSL`, `WHSM`, `WH`) used
  in filenames, and which components/categories they supply.
- `SKU` — SKU code, market(s) it ships to, `components_per_unit` (used for
  overhead allocation), `cbm_per_unit` (fallback freight rate basis when a
  SKU has no shipment in a period), and its `bill_of_materials`: a mapping
  of component name → quantity per unit (the BOM grid in `6 UNIT COST`
  section A, e.g. a container SKU using 0.5 of a "26 QT Master Carton"
  because two units share one carton).

### `unit_cost.UnitCostLine` (`unit_cost.py`)

One row of `6 UNIT COST` section B — the actual tax-facing number: SKU,
market, `components_cost` (BOM × `ComponentPriceSummary.price_used`),
`bundling_cost`, `freight_cost` (actual allocated, or market-rate-by-CBM
fallback if this SKU/market had no shipment this period —
`freight_basis` records which), `overhead_cost`, and the derived
`landed_cost_per_unit` (sum of the four).

### `year_end.py`

- `YearEndFinishedGoods` — one row of `7 YEAR-END` section A: SKU, market,
  units on hand by location (FBA/AWD/3PL), and value = units ×
  `UnitCostLine.landed_cost_per_unit`.
- `YearEndComponentInventory` — one row of section B: raw component units on
  hand, valued at `ComponentPriceSummary.price_used` (component cost only —
  finished-goods layers like freight/bundling/overhead don't apply to
  unbuilt inventory).
- `YearEndSummary` — section C total, plus the `previously_given_total` /
  `difference` reconciliation against whatever total was last given to the
  accountant (Steve), so a re-run always shows what changed and why.

### `control.ControlCheck` (`control.py`)

One row of `8 CONTROL`: a name, the two values being compared
(`built_up_value`, `source_value`), the derived `difference`, and `status`
(`OK` / `REVIEW` / `CHECK`) using the same thresholds as the workbook
(< $1 or < $0.01 depending on the check, then < $250, else fail). This is
the model a pipeline run should evaluate *every time* before treating a
build-up as postable — per the workbook's own rule: "if one does not [read
zero], the number below it is wrong — do not send the file."

## What this milestone does *not* do yet

No Google Drive access, no Sheets read/write, no PDF/invoice parsing. Those
are the next slices, in roughly this order:

1. A `documents` ingestion pass over a Drive folder that instantiates
   `SourceDocument` for every file and flags any filename that doesn't
   parse (so the naming convention stays enforced going forward).
2. A Google Sheets client that reads/writes the exact ranges above (kept
   next to each model as a `SHEET_RANGE` constant so the mapping can't
   drift silently).
3. Per-vendor PDF/invoice parsers that produce `ComponentPurchaseLine` /
   `FreightInvoiceRegister` / etc. rows, reviewed against `verified`/manual
   sign-off before they're trusted for tax numbers.
4. A reconciliation runner that recomputes every `ControlCheck` after a
   pipeline run and refuses to write a "final" number sheet if any check is
   not `OK`.

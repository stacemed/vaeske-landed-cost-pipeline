# SOP: Populating 1 TRANSACTIONS / 2 FREIGHT from a QBO report

This is the manual process behind what the README calls "Milestone 2
remainder + Milestone 3" — there's no committed code for this yet (see
the README's "Not built yet" list). Until there is, this is how to get
a year's financial data from QuickBooks + Drive into paste-ready CSVs
for the live Google Sheet, using a fresh Claude session each time.

## When to use this

You have:
- A QuickBooks Online **Account QuickReport** export for the `Inventory`
  distribution account, covering the year you want to populate.
- That year's component/freight/overhead invoices already filed in the
  Drive "Support Docs" folder (`Invoices - Components`,
  `Invoices - Freight-Bundling`, `Invoices - Overhead`) using the
  standard filename convention (see `docs/DATA_MODEL.md`). If they
  aren't filed yet, run the Inbox automation first
  (`docs/DRIVE_INGESTION.md`) — this SOP reads already-filed documents,
  it doesn't file them.

## What this does NOT do

- Doesn't touch `3 COMPONENTS` (the BOM-level purchase-line detail) —
  that sheet is maintained separately and trusted as-is.
- Doesn't allocate freight/bundling/overhead to shipments or SKUs
  (that's Phase 2 — a different task, using the monthly Prep Instructions
  files).
- Doesn't write into the Google Sheet directly — produces CSVs for you
  to paste in yourself.
- Doesn't need anything for `5 OVERHEAD` — that sheet is a live formula
  off `1 TRANSACTIONS` in the real workbook and recomputes on its own
  once Section A is pasted in. Never paste static values over it.

## Before you start

1. **Export the QBO CSV.** QuickBooks Online → Reports → "Account
   QuickReport" → set the report period to the target year → make sure
   it's scoped to the `Inventory` account → Export to CSV.
2. **Get the Drive folder ID** for "Support Docs" (from its URL:
   `drive.google.com/drive/folders/<this part>`).
3. **Confirm the year's invoices are already filed.** If some aren't,
   file them first (a separate step) — this process only reads what's
   already correctly named and filed.

## The prompt

Paste this into a fresh Claude conversation (Claude needs Google Drive
access and the QBO CSV either uploaded or accessible):

```
I need to populate the "1 TRANSACTIONS" and "2 FREIGHT" sheets of my
landed-cost Google Sheet for <YEAR>. I'm attaching/providing:
1. A QBO "Account QuickReport" CSV for the Inventory account, <YEAR>.
2. Access to my Google Drive "Support Docs" folder (ID: <FOLDER_ID>),
   which has this year's invoices already filed under
   "Invoices - Components", "Invoices - Freight-Bundling", and
   "Invoices - Overhead" using a standard filename convention.

Follow this method:

1. Parse the QBO CSV into individual transactions: date, vendor/wire
   description text, amount.
2. Classify each transaction's category by vendor pattern:
   - A wire to/from "Shenzhen Linkhub" -> Freight / bundling / packaging
   - A wire to/from "Shenzhen Minzhi BYJ Trading Company", or a charge
     from "Alibaba.com" -> Components
   - A wire "Sent WEIMIN HUANG" or similar personal payment to him
     -> Overhead
   - Anything else -> leave Category BLANK and flag it for my review;
     do not guess.
3. Read every invoice / payment-confirmation PDF filed in the three
   Invoices folders for <YEAR>. For each, extract: amount, date,
   invoice/reference number, and payment stage (deposit / balance /
   full / refund).
4. Match each documented payment to a QBO transaction by amount.
   Several invoices are sometimes paid in ONE combined wire -- check
   whether a QBO amount equals the SUM of multiple invoice amounts
   before concluding there's no match.
5. When a payment has both an invoice document and a payment
   confirmation, use the payment confirmation's amount/date (actual
   cash movement) over the invoice's stated amount/date.
6. Do not silently guess or resolve:
   - A dollar split (e.g. freight vs. bundling on one combined invoice)
   - A "refund"-labeled document's sign -- check what QBO actually
     posted it as (a credit vs. a normal positive expense) and flag
     any mismatch with the label
   - Any invoice-number or category ambiguity
   Flag all of these clearly instead, with your best-effort default
   still shown, so I can review before pasting anything in.
7. Flag every gap in BOTH directions:
   - A QBO transaction with no matching invoice/confirmation document
   - A documented invoice/payment with no matching QBO transaction
8. Exclude anything genuinely outside <YEAR> (e.g. a misdated document),
   but call it out explicitly rather than quietly dropping it.

Produce one CSV per table below, column headers exactly as shown (so I
can paste the data rows straight under the matching header row in my
Sheet -- don't include the header row itself in the CSV, just the data,
unless I ask for it for reference):

TABLE 1 -- "1 TRANSACTIONS" Section A (QBO INVENTORY ADDITIONS)
Columns: Category, Date, Payee / description, Invoice #, Amount $
One row per REAL transaction in the QBO CSV -- this table IS the QBO
ledger, never built bottom-up from invoices.

TABLE 2 -- "1 TRANSACTIONS" Section C (COMPONENT INVOICE REGISTER)
Columns: Invoice #, Invoice date, Balance paid date, Total Order $
(incl exchng fees), Invoice Adjustments
One row per distinct component order/payment event.

TABLE 3 -- "1 TRANSACTIONS" Section D (FREIGHT INVOICE REGISTER)
Columns: Invoice #, Invoice date, Paid date, Freight $, Bundling /
packaging $
Freight and bundling as separate columns even though the vendor bills
them together on one invoice -- split using each invoice's own line
items.

TABLE 4 -- "1 TRANSACTIONS" Section E (OVERHEAD INVOICE REGISTER)
Columns: Invoice #, Invoice date, Paid date, Overhead $, Invoice Link
"Invoice Link" = the filed document's filename.

TABLE 5 -- "2 FREIGHT" Section A (INVOICE REGISTER)
Columns: Invoice, Prep sheet, Invoice date, Paid date, freight $
"Prep sheet" = a month label like "2024-01 JAN", from the paid date.
Freight-only $ (bundling is tracked in Table 3 and in 4 BUNDLING, not
here).

Also give me a short reconciliation summary listing every flagged gap,
judgment call, and dollar discrepancy over $1, so I can review before
pasting anything into the live sheet.
```

## Why these particular rules

Each rule above came from a real mistake or a real finding while doing
this by hand for 2024, not from guessing upfront:

- **Section A must come from QBO, not be built bottom-up from
  invoices.** The first pass built it from invoice PDFs alone and got
  the categories and totals right in isolation, but it wasn't actually
  what happened in the books -- QBO is the source of truth for "did
  this transaction happen," invoices are the source of truth for "what
  was it for."
- **Combined wires are common, not an edge case.** Several real 2024
  freight and component payments covered 2-3 invoices in one wire.
  Matching strictly 1:1 misses these and wrongly reports them as
  unmatched on both sides.
- **A "refund"-suffixed invoice isn't automatically a credit.** One
  real 2024 file tagged `INV-refund` actually posted as a normal
  positive expense in QBO -- the filename convention's doc-type is a
  human's label, not proof of the accounting treatment.
- **The two-directional gap check is where the real value is.** Doing
  this for 2024 surfaced a fully undocumented $2,303 in Overhead
  invoices with zero overlap against QBO, a $7,852 invoice that had
  never been registered anywhere, and about $40k in QBO Components
  transactions with no supporting document at all -- none of which
  would have surfaced from either direction alone.

## After you get the CSVs

1. Read the reconciliation summary first. Resolve or explicitly accept
   every flagged item before pasting anything in.
2. Paste each table's data rows under the matching section header in
   the live Sheet.
3. Don't touch `5 OVERHEAD` -- it recomputes on its own.
4. `3 COMPONENTS` still needs its own year's rows added separately (out
   of scope for this SOP) if you want `8 CONTROL`'s Components tie-out
   to mean anything for the new year.

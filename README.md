# Väeske landed-cost pipeline

Automates the landed-unit-cost workbook Väeske / Black Oak Essentials uses
with its accountant for tax purposes. The workbook itself (currently a
Google Sheet, exported to xlsx for the accountant) stays the system of
record; this project's job is to keep it fed from the supporting documents
— component invoices, freight/shipping invoices, expense records, inventory
counts — that currently get entered by hand from Google Drive.

## Status

**First milestone: the data model.** This repo currently defines, in code,
the entities the workbook already tracks (transactions, freight/component/
overhead invoices, shipment CBM allocation, the bill of materials, unit
cost, year-end inventory, and the tie-out checks), each validated against
real numbers pulled from the source workbook. See
[`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) for the full design and how each
model maps back to a specific sheet.

Not built yet, in planned order:

1. Google Drive ingestion — read a folder of source documents, parse the
   filename convention already used throughout the workbook
   (`landed_cost.models.SourceDocument`), and flag anything that doesn't
   conform.
2. A Google Sheets client that reads/writes the exact ranges the models
   above are shaped around, so the mapping can't silently drift from the
   real sheet.
3. Per-vendor invoice/packing-list parsers that produce populated model
   rows from PDFs, with a review step before anything feeds a tax number.
4. A reconciliation runner that recomputes every `ControlCheck` after a
   pipeline run and refuses to post a "final" set of numbers unless every
   check reads `OK`, matching the workbook's own rule: "if one does not
   [read zero], the number below it is wrong — do not send the file."

## Layout

```
src/landed_cost/models/   # the data model (this milestone)
docs/DATA_MODEL.md        # design notes + sheet-to-model mapping
tests/                    # model tests, several checked against real
                           # numbers from the source workbook
```

## Development

```
pip install -e ".[dev]"
pytest
```

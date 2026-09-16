# Väeske landed-cost pipeline

Automates the landed-unit-cost workbook Väeske / Black Oak Essentials uses
with its accountant for tax purposes. The workbook itself (currently a
Google Sheet, exported to xlsx for the accountant) stays the system of
record; this project's job is to keep it fed from the supporting documents
— component invoices, freight/shipping invoices, expense records, inventory
counts — that currently get entered by hand from Google Drive.

## Status

**Milestone 1: the data model — done.** The entities the workbook already
tracks (transactions, freight/component/overhead invoices, shipment CBM
allocation, the bill of materials, unit cost, year-end inventory, and the
tie-out checks), each validated against real numbers pulled from the
source workbook. See [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md).

**Milestone 2: Google Drive ingestion — in progress.**
- Category ingestion: given the root "Support Docs" folder, lists each
  category subfolder, parses every filename with `SourceDocument`, and
  flags anything that doesn't conform or looks misfiled.
- Inbox processing: drop a file with any name into an `Inbox` folder;
  reads the PDF's own text (falling back to OCR for scans/photos with no
  text layer), guesses the standardized filename + category, and (only
  with `--apply`) renames and files it, or moves it to `Needs Review` if
  it can't guess confidently — components never auto-file, and neither
  does anything read via OCR, since both carry a real misread risk that
  needs a human check.

See [`docs/DRIVE_INGESTION.md`](docs/DRIVE_INGESTION.md) for the folder
layout, credential setup, and how to run both.

Not built yet, in planned order:

1. A Google Sheets client that reads/writes the exact ranges the models
   above are shaped around, so the mapping can't silently drift from the
   real sheet.
2. Wiring the confidently-extracted fields (freight, overhead) into
   populated `FreightInvoiceRegister` / etc. rows; a review step before
   anything feeds a tax number for the categories that can't auto-extract.
3. A reconciliation runner that recomputes every `ControlCheck` after a
   pipeline run and refuses to post a "final" set of numbers unless every
   check reads `OK`, matching the workbook's own rule: "if one does not
   [read zero], the number below it is wrong — do not send the file."

## Layout

```
src/landed_cost/models/   # the data model (milestone 1)
src/landed_cost/drive/    # Drive ingestion, filename parsing, and PDF-text
                           # field extraction (milestone 2)
scripts/                  # runnable entry points:
                           #   ingest_drive_folder.py  (report on category folders)
                           #   process_inbox.py        (guess + file Inbox contents)
docs/DATA_MODEL.md        # design notes + sheet-to-model mapping
docs/DRIVE_INGESTION.md   # Drive folder layout + credential setup
tests/                    # tests, several checked against real numbers /
                           # filenames / invoice text from the source
                           # workbook and Drive
```

## Development

```
pip install -e ".[dev]"
pytest
```

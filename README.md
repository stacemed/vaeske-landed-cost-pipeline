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

## Adding another user

The one-time Google Cloud project + OAuth client setup (see "Setting up
credentials" in [`docs/DRIVE_INGESTION.md`](docs/DRIVE_INGESTION.md))
only needs to happen once, by whoever creates it. Adding a second person
to actually run these scripts doesn't repeat that — each person just
needs their own authorized token:

1. In Google Cloud Console, under **APIs & Services → OAuth consent
   screen → Test users**, add their Google account email. This is
   required for anyone besides the original developer to sign in at all
   — the app stays in "Testing" publishing status (capped at 100 named
   test users, plenty for a small team) rather than going through
   Google's public-app verification, which isn't needed for a couple of
   people using their own tool.
2. Confirm their Google account already has access to the Drive folder
   itself. Drive sharing is separate from being a Test user — the API
   only sees what their signed-in account can see in Drive.
3. Send them the same `client_secret_<id>.json` file. It identifies the
   app, not a person, so it's fine to share between authorized users —
   but still keep it out of git, as `.gitignore` already does.
4. They run the one-time browser sign-in themselves (see "Setting up
   credentials" in `docs/DRIVE_INGESTION.md`) to produce their **own**
   `token.json`. Never share a `token.json` between people — it's tied
   to whichever Google account signed in to create it.

Since the app stays in Testing status, each person's `token.json`
expires after about 7 days and needs to be regenerated the same way —
a non-issue for occasional use, just re-run the sign-in step before the
next run rather than expecting it to stay valid indefinitely.

## Development

```
pip install -e ".[dev]"
pytest
```

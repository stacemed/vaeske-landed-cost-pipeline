# Drive ingestion

Two things touch Google Drive so far:

1. **Category ingestion** (`landed_cost.drive.ingest`) -- given a root
   "Support Docs" folder, lists each category subfolder, parses every
   filename with `landed_cost.models.SourceDocument`, and reports what
   parsed, what didn't, and anything that looks off. Assumes files are
   already correctly named and correctly filed.
2. **Inbox processing** (`landed_cost.drive.inbox`) -- the answer to "do I
   have to name and sort every file myself?" Drop a file with *any* name
   into an `Inbox` folder; it reads the PDF's own text, guesses the
   standardized filename and which category folder it belongs in, and
   (only with `--apply`) renames and files it -- or, if it can't guess
   confidently, moves it to `Needs Review` untouched so nothing is ever
   silently misfiled.

Neither writes anything back to the workbook or touches Google Sheets yet
-- see the roadmap in the main README for what comes after this.

## Folder layout

Agreed 2026-09-04: one **continuous** folder per category, not
year-partitioned -- new documents just land in the same folder every
year, and the year lives in each file's own filename, not the folder
name. Under a root folder (yours is named "Vaeske Landed Cost Tracking" >
"Support Docs"):

```
Support Docs/
  Inbox/                                           (drop new files here, any name)
  Needs Review/                                    (couldn't be confidently filed)
  Invoices - Components/
  Invoices - Freight-Bundling/
  Invoices - Overhead/
  Year End Inventory Data/                        (not ingested by either module)
  FBABee Prep Sheets associated w Invoices/        (not ingested by either module)
```

The three `Invoices - *` folders are where correctly-named,
correctly-filed documents live (per the `SourceDocument` convention in
`docs/DATA_MODEL.md`). `find_child_folder` matches folder names
case-insensitively, and all the names above are configurable (pass
`category_folder_names` / `--inbox-name` / `needs_review_folder_name`)
in case you rename them again later.

A file's own `category_tag` (the third `_`-delimited segment, e.g.
`comp`, `Frei-Bund`, `Over`) is cross-checked against the folder it's
found in during category ingestion -- a mismatch (e.g. a freight invoice
sitting in the Components folder) is flagged as `category_tag_mismatch`,
not silently accepted or rejected outright, since it's a strong signal
something's misfiled but not proof (the tag is free text, not validated
at upload time).

## How the Inbox guesses a filename

`landed_cost.drive.extract.extract_from_text` reads a PDF's text and
tries to identify the vendor, then extracts the rest from patterns
specific to that vendor. How reliable this is varies a lot by category,
and the code is upfront about it rather than pretending otherwise:

- **Freight (Shenzhen Linkhub)** and **overhead (Weimin Huang inspection
  invoices)** follow tight, regular formats -- a `JG########E` invoice
  number, a dated `INVOICE DATE` or `Invoice Date:` line, a recognizable
  bank wire confirmation header. These extract confidently and get
  auto-filed with `--apply`.
- **Components** never auto-file, on purpose. Vendors use inconsistent,
  one-off invoice-number formats, and the workbook itself has purchase
  lines with no invoice number recorded at all (see `ComponentPurchaseLine`
  in `docs/DATA_MODEL.md`). A components document always lands in Needs
  Review with its best guess attached, for a human to confirm.
- Anything from an unrecognized vendor, or a scanned PDF with no text
  layer at all, also goes to Needs Review with an explanation of what
  failed.

The generator and the parser are tested against each other (a proposed
filename must parse back through `SourceDocument.from_filename` to the
same fields), so they can't silently drift apart.

## Setting up credentials

Neither `landed_cost.drive.ingest` nor `landed_cost.drive.extract`/`inbox`
depend on any Google library -- they're tested entirely against a fake
in-memory client and plain text fixtures. To run against real Drive you
need the optional `drive` dependency group (this also pulls in `pypdf`
for reading PDF text) and an OAuth credential:

```
pip install -e ".[drive]"
```

For a folder that's shared with your own Google account (as this one is),
the simplest path is an OAuth "Desktop app" client, not a service account
(a service account would need the folder re-shared with its own
service-account email, which is more setup for no benefit here):

1. In [Google Cloud Console](https://console.cloud.google.com/), create a
   project (or reuse one), enable the **Google Drive API**, and under
   "APIs & Services > Credentials" create an OAuth client ID of type
   **Desktop app**. Download the resulting `client_secret.json`.
2. Run a one-time local authorization flow to turn that into a cached
   user token (`token.json`) that `GoogleDriveClient.from_authorized_user_file`
   reads:

   ```python
   from google_auth_oauthlib.flow import InstalledAppFlow

   flow = InstalledAppFlow.from_client_secrets_file(
       "client_secret.json",
       scopes=["https://www.googleapis.com/auth/drive"],
   )
   credentials = flow.run_local_server(port=0)
   with open("token.json", "w") as f:
       f.write(credentials.to_json())
   ```

   This opens a browser, asks you to sign in as the account the folder is
   shared with, shows an "unverified app" warning (expected -- click
   **Advanced > Go to \[app name\] (unsafe)**; it just means this personal
   OAuth client hasn't been through Google's public-app review, not that
   anything is actually wrong), and writes `token.json`. Keep both
   `client_secret.json` and `token.json` out of git -- `.gitignore`
   already excludes `client_secret*.json`, `token.json`, and
   `credentials.json`.

   Note the scope is the full `.../auth/drive`, not `drive.readonly` --
   `process_inbox.py` needs to rename and move files, and the narrower
   `drive.file` scope wouldn't give access to files that already existed
   in the folder before the app touched them (it only covers files the
   app itself creates, or ones picked through a Drive Picker UI). If you
   generated a `token.json` before this scope was added, delete it and
   redo this step -- Google won't silently upgrade an existing token's
   scope.
3. Get the root folder's ID from its URL:
   `https://drive.google.com/drive/folders/<this part>`.
4. This one-time browser step needs a real browser, so run it on your own
   laptop, not inside a headless/remote environment. Copy the resulting
   `token.json` to wherever the scripts actually run.

## Running it

Report on the three category folders (read-only, always):

```
python scripts/ingest_drive_folder.py <root_folder_id> --credentials token.json
```

Process the Inbox -- dry run by default, prints what it *would* do:

```
python scripts/process_inbox.py <root_folder_id> --credentials token.json
```

Add `--apply` once you've checked the dry-run output and are ready to let
it actually rename and move files:

```
python scripts/process_inbox.py <root_folder_id> --credentials token.json --apply
```

Both exit non-zero if anything needs a look.

## What's next

Per the main README roadmap: a Sheets client to read/write the live
workbook, then wiring the confidently-extracted fields (freight, overhead)
into populated `FreightInvoiceRegister` / etc. rows, and the
`ControlCheck` gate before anything is called final. Components will keep
needing a human to type the invoice number even after that, per the
"never auto-file" design above -- worth watching whether that's still
true once there's more real component-invoice text to learn from.

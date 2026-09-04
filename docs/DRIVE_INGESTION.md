# Drive ingestion

This is the first thing that actually touches Google Drive: given a root
"Support Docs" folder, it lists each category subfolder, parses every
filename with `landed_cost.models.SourceDocument`, and reports what
parsed, what didn't, and anything that looks off. It does **not** yet read
PDF content, write anything back to the workbook, or touch Google Sheets
-- see the roadmap in the main README for what comes after this.

## Folder layout

Agreed 2026-09-04: one **continuous** folder per category, not
year-partitioned -- new documents just land in the same folder every
year, and the year lives in each file's own filename, not the folder
name. Under a root folder (yours is named "Vaeske Landed Cost Tracking" >
"Support Docs"):

```
Support Docs/
  Invoices - Components/
  Invoices - Freight-Bundling/
  Invoices - Overhead/
  Year End Inventory Data/                        (not ingested by this slice)
  FBABee Prep Sheets associated w Invoices/        (not ingested by this slice)
```

The three `Invoices - *` folders are the ones this module reads --
they're where files named per the `SourceDocument` convention
(`docs/DATA_MODEL.md`) live. `find_child_folder` matches folder names
case-insensitively, and the three names are configurable (pass
`category_folder_names` to `ingest_support_docs`) in case you rename them
again later.

A file's own `category_tag` (the third `_`-delimited segment, e.g.
`comp`, `Frei-Bund`, `Over`) is cross-checked against the folder it's
found in -- a mismatch (e.g. a freight invoice dropped in the Components
folder) is flagged as `category_tag_mismatch`, not silently accepted or
rejected outright, since it's a strong signal something's misfiled but
not proof (the tag is free text, not validated at upload time).

## Setting up credentials

The ingestion logic itself (`landed_cost.drive.ingest`) doesn't depend on
any Google library -- it's tested entirely against a fake in-memory
client. To run it against real Drive you need the optional `drive`
dependency group and an OAuth credential:

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
       scopes=["https://www.googleapis.com/auth/drive.readonly"],
   )
   credentials = flow.run_local_server(port=0)
   with open("token.json", "w") as f:
       f.write(credentials.to_json())
   ```

   This opens a browser, asks you to sign in as the account the folder is
   shared with, and writes `token.json`. Keep both `client_secret.json`
   and `token.json` out of git -- `.gitignore` already excludes
   `client_secret*.json`, `token.json`, and `credentials.json`.
3. Get the root folder's ID from its URL:
   `https://drive.google.com/drive/folders/<this part>`.

## Running it

```
python scripts/ingest_drive_folder.py <root_folder_id> --credentials token.json
```

Prints, per category: how many files parsed, how many failed to parse
(with the reason), any category-tag mismatches, and any filename that
shows up more than once across categories. Exits non-zero if anything
needs a look.

## What's next

Per the main README roadmap: a Sheets client to read/write the live
workbook, per-vendor PDF parsers that turn a `SourceDocument` into
populated `ComponentPurchaseLine` / `FreightInvoiceRegister` / etc. rows,
and the `ControlCheck` gate before anything is called final.

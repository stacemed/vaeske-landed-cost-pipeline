#!/usr/bin/env python3
"""Report what the Drive filename parser makes of a Support Docs folder.

Read-only: lists each category subfolder, parses every filename, and
prints what parsed, what didn't, and any category-tag mismatches or
duplicate filenames. Does not write anything back to Drive or the
spreadsheet -- see docs/DRIVE_INGESTION.md for the full picture of what
this step does and doesn't do yet.

Usage:
    python scripts/ingest_drive_folder.py <root_folder_id> --credentials token.json

See docs/DRIVE_INGESTION.md for how to get a root folder ID and a
credentials file.
"""

from __future__ import annotations

import argparse
import sys

from landed_cost.drive.google_client import GoogleDriveClient
from landed_cost.drive.ingest import duplicate_filenames, ingest_support_docs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root_folder_id", help="Drive folder ID of the 'Support Docs' folder")
    parser.add_argument(
        "--credentials",
        required=True,
        help="Path to an OAuth authorized-user JSON file (see docs/DRIVE_INGESTION.md)",
    )
    args = parser.parse_args()

    client = GoogleDriveClient.from_authorized_user_file(args.credentials)
    result = ingest_support_docs(client, args.root_folder_id)

    exit_code = 0
    for category, category_result in result.results.items():
        print(
            f"\n{category.value}: {len(category_result.documents)} parsed, "
            f"{len(category_result.failures)} failed to parse"
        )
        for doc in category_result.documents:
            if doc.category_tag_mismatch:
                print(f"  ! category tag mismatch: {doc.document.raw_filename}")
        for failure in category_result.failures:
            print(f"  X {failure.file_name}: {failure.error}")
            exit_code = 1

    dupes = duplicate_filenames(result.all_documents)
    if dupes:
        print(f"\nDuplicate filenames across categories: {dupes}")
        exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())

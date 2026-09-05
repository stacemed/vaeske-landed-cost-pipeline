#!/usr/bin/env python3
"""Read every file in the Inbox folder, propose a standardized filename
and destination folder, and -- only with --apply -- actually rename and
file it.

Without --apply this only prints what it *would* do; nothing on Drive
changes. Anything that can't be confidently classified (most notably
every component invoice -- see docs/DATA_MODEL.md on why) moves to Needs
Review with its original filename intact, never guessed onto the file
itself.

Usage:
    python scripts/process_inbox.py <root_folder_id> --credentials token.json
    python scripts/process_inbox.py <root_folder_id> --credentials token.json --apply

See docs/DRIVE_INGESTION.md for folder layout and credential setup.
"""

from __future__ import annotations

import argparse
import sys

from landed_cost.drive.google_client import GoogleDriveClient
from landed_cost.drive.inbox import (
    DEFAULT_INBOX_FOLDER_NAME,
    apply_inbox_actions,
    propose_inbox_actions,
)
from landed_cost.drive.ingest import find_child_folder


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root_folder_id", help="Drive folder ID of the 'Support Docs' folder")
    parser.add_argument(
        "--credentials",
        required=True,
        help="Path to an OAuth authorized-user JSON file (see docs/DRIVE_INGESTION.md)",
    )
    parser.add_argument(
        "--inbox-name",
        default=DEFAULT_INBOX_FOLDER_NAME,
        help=f"Inbox subfolder name (default: {DEFAULT_INBOX_FOLDER_NAME!r})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually rename/move files. Without this, only prints proposals.",
    )
    args = parser.parse_args()

    client = GoogleDriveClient.from_authorized_user_file(args.credentials)

    inbox_folder = find_child_folder(client, args.root_folder_id, args.inbox_name)
    if inbox_folder is None:
        print(
            f"No {args.inbox_name!r} subfolder found under {args.root_folder_id!r}.",
            file=sys.stderr,
        )
        return 1

    proposals = propose_inbox_actions(client, inbox_folder.id)

    if not proposals:
        print("Inbox is empty.")
        return 0

    for proposal in proposals:
        status = "READY" if proposal.ready_to_file else "NEEDS REVIEW"
        print(f"\n[{status}] {proposal.original_name}")
        print(f"  -> {proposal.proposed_name}")
        for issue in proposal.extracted.issues:
            print(f"  ! {issue}")

    ready_count = sum(1 for p in proposals if p.ready_to_file)
    print(f"\n{ready_count} of {len(proposals)} ready to file automatically.")

    if args.apply:
        apply_inbox_actions(
            client, proposals, args.root_folder_id, inbox_folder_id=inbox_folder.id
        )
        print(
            f"Applied: {ready_count} filed into their category folder, "
            f"{len(proposals) - ready_count} moved to Needs Review."
        )
    else:
        print("Dry run only -- pass --apply to actually rename/move these files.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

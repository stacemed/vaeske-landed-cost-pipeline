#!/usr/bin/env python3
"""One-time browser sign-in that turns a downloaded OAuth client secret
into an authorized-user token file the other scripts can use.

Run this once per person who needs to run process_inbox.py /
ingest_drive_folder.py against the real Drive folder. Opens a browser,
asks you to sign in as whichever Google account has access to the
Support Docs folder, and writes the resulting token to --out.

This needs a real browser, so run it on your own machine, not inside a
headless/remote environment.

Needs the optional `drive` dependency group:
    pip install -e ".[drive]"

Usage:
    python scripts/get_token.py client_secret_<id>.json
    python scripts/get_token.py client_secret_<id>.json --out token.json

See docs/DRIVE_INGESTION.md ("Setting up credentials") for how to get a
client secret file, and "Adding another user" in the README for what a
second person needs (their own token, same client secret file).
"""

from __future__ import annotations

import argparse
import sys

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "client_secret",
        help="Path to the OAuth client secret JSON downloaded from Google Cloud Console",
    )
    parser.add_argument(
        "--out",
        default="token.json",
        help="Where to write the resulting token (default: token.json)",
    )
    args = parser.parse_args()

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(args.client_secret, scopes=DRIVE_SCOPES)
    credentials = flow.run_local_server(port=0)

    with open(args.out, "w") as f:
        f.write(credentials.to_json())

    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

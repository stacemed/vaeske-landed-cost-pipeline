"""Real Google Sheets client, backed by the Sheets v4 API.

Requires the optional ``drive`` dependency group (same
``google-api-python-client``/``google-auth`` packages the Drive client
uses) plus a token authorized for the Sheets scope -- see
docs/DRIVE_INGESTION.md. Never imported by ``landed_cost.sheets.qbo``
itself, so the parsing/planning logic and its tests never need these
dependencies installed.

Uses ``https://www.googleapis.com/auth/spreadsheets``, not the Drive
scope -- they're separate APIs. A ``token.json`` generated before this
scope existed won't have it; regenerate via ``scripts/get_token.py``
(same one-time step, now requesting both scopes).
"""

from __future__ import annotations

from typing import Any

_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


class GoogleSheetsClient:
    """Adapts a ``googleapiclient`` Sheets v4 service to ``SheetsClient``."""

    def __init__(self, service: Any) -> None:
        self._service = service

    @classmethod
    def from_authorized_user_file(cls, path: str) -> "GoogleSheetsClient":
        """Build a client from a cached OAuth user-token JSON file, as
        produced by ``scripts/get_token.py``.
        """
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        credentials = Credentials.from_authorized_user_file(path, scopes=[_SCOPE])
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        return cls(build("sheets", "v4", credentials=credentials))

    def get_values(self, spreadsheet_id: str, a1_range: str) -> list[list[object]]:
        # UNFORMATTED_VALUE: dates come back as Sheets' own serial-number
        # date, amounts as plain numbers -- not whatever display format
        # (locale, currency symbol, etc.) the cell happens to be
        # formatted with. landed_cost.sheets.sync's date/amount parsing
        # depends on this.
        response = (
            self._service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=a1_range, valueRenderOption="UNFORMATTED_VALUE")
            .execute()
        )
        return response.get("values", [])

    def update_values(self, spreadsheet_id: str, a1_range: str, values: list[list[object]]) -> None:
        self._service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=a1_range,
            valueInputOption="USER_ENTERED",
            body={"values": values},
        ).execute()

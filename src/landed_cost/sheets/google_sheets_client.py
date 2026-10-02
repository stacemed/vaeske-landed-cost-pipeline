"""Real Google Sheets client, backed by the Sheets v4 API.

Requires the optional ``drive`` dependency group (same
``google-api-python-client``/``google-auth`` packages the Drive client
uses) plus a token authorized for the Sheets scope -- see
docs/DRIVE_INGESTION.md. Never imported by ``landed_cost.sheets.qbo``
itself, so the parsing/planning logic and its tests never need these
dependencies installed.

Uses both the ``spreadsheets`` scope and the ``drive`` scope. Writing a
Drive file smart chip (``write_file_chip_cells``) is a Sheets API call
whose access token must ALSO carry Drive read rights for the chip's
file reference to resolve -- confirmed by a real 403 (2026-10-02):
"The request scopes are not sufficient for reading from Drive." A
``token.json`` generated before chips existed may still have both
scopes in its underlying grant (``scripts/get_token.py`` has requested
both since the Sheets scope was first added), since this is a scoped-
DOWN refresh problem, not a missing-grant one -- constructing
credentials with only the ``spreadsheets`` scope here meant every
refreshed access token for THIS client carried only that scope, no
matter what the original token.json grant included. Regenerate via
``scripts/get_token.py`` only if your token predates the Sheets scope
entirely (see its own module docstring).
"""

from __future__ import annotations

from typing import Any

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


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

        credentials = Credentials.from_authorized_user_file(path, scopes=_SCOPES)
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

    def get_sheet_id(self, spreadsheet_id: str, sheet_name: str) -> int:
        response = (
            self._service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id, fields="sheets.properties(sheetId,title)")
            .execute()
        )
        for sheet in response.get("sheets", []):
            if sheet["properties"]["title"] == sheet_name:
                return sheet["properties"]["sheetId"]
        raise ValueError(f"no sheet tab named {sheet_name!r} found in spreadsheet {spreadsheet_id!r}")

    def insert_rows(self, spreadsheet_id: str, sheet_id: int, start_row: int, num_rows: int) -> None:
        start_index = start_row - 1  # Sheets API GridRange is 0-indexed
        end_index = start_index + num_rows
        body = {
            "requests": [
                {
                    "insertDimension": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "ROWS",
                            "startIndex": start_index,
                            "endIndex": end_index,
                        },
                        # Copies the cell formatting of the row directly above
                        # the insertion point onto the new rows -- same as
                        # "Insert row above" in the Sheets UI. Requires
                        # startIndex > 0, always true here (Section A never
                        # starts at row 1).
                        "inheritFromBefore": start_index > 0,
                    }
                }
            ]
        }
        self._service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()

    def format_row_flags(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        row_flags: list[tuple[int, bool]],
        num_columns: int,
    ) -> None:
        if not row_flags:
            return
        flagged_color = {"red": 0.96, "green": 0.80, "blue": 0.80}  # light red
        clear_color = {"red": 1.0, "green": 1.0, "blue": 1.0}  # white
        requests = [
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row_number - 1,
                        "endRowIndex": row_number,
                        "startColumnIndex": 0,
                        "endColumnIndex": num_columns,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": flagged_color if flagged else clear_color
                        }
                    },
                    "fields": "userEnteredFormat.backgroundColor",
                }
            }
            for row_number, flagged in row_flags
        ]
        self._service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests}
        ).execute()

    def write_file_chip_cells(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        cells: list[tuple[int, int, list[str]]],
    ) -> None:
        if not cells:
            return

        def _cell_data(file_ids: list[str]) -> dict:
            if not file_ids:
                return {"userEnteredValue": {"stringValue": ""}, "chipRuns": []}
            # "@" is a placeholder -- Sheets renders the chip in its
            # place once the request lands; the literal text between
            # placeholders (", ") stays as plain separator text.
            text = ", ".join(["@"] * len(file_ids))
            chip_runs = []
            index = 0
            for i, file_id in enumerate(file_ids):
                chip_runs.append({
                    "startIndex": index,
                    "chip": {
                        "richLinkProperties": {
                            "uri": f"https://drive.google.com/file/d/{file_id}/view"
                        }
                    },
                })
                index += 1  # length of "@"
                if i < len(file_ids) - 1:
                    index += 2  # length of ", "
            return {"userEnteredValue": {"stringValue": text}, "chipRuns": chip_runs}

        requests = [
            {
                "updateCells": {
                    "rows": [{"values": [_cell_data(file_ids)]}],
                    "start": {
                        "sheetId": sheet_id,
                        "rowIndex": row_number - 1,
                        "columnIndex": column_index,
                    },
                    "fields": "userEnteredValue,chipRuns",
                }
            }
            for row_number, column_index, file_ids in cells
        ]
        self._service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests}
        ).execute()

    def sort_range(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        start_row: int,
        end_row: int,
        sort_column_index: int,
        ascending: bool = True,
        num_columns: int = 5,
    ) -> None:
        body = {
            "requests": [
                {
                    "sortRange": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": start_row - 1,  # 0-indexed
                            "endRowIndex": end_row,  # exclusive, so inclusive end_row works as-is
                            "startColumnIndex": 0,
                            "endColumnIndex": num_columns,  # A:E by default (Section A); pass the caller's own column count otherwise
                        },
                        "sortSpecs": [
                            {
                                "dimensionIndex": sort_column_index,
                                "sortOrder": "ASCENDING" if ascending else "DESCENDING",
                            }
                        ],
                    }
                }
            ]
        }
        self._service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()

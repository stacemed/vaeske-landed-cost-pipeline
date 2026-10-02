"""Tests for GoogleSheetsClient's own request-building/chunking logic,
using a fake googleapiclient ``service`` object -- GoogleSheetsClient's
module-level constructor and methods have no import-time dependency on
``googleapiclient``/``google-auth`` themselves (only
``from_authorized_user_file`` does, via a lazy import), so this needs
none of the optional ``drive`` dependency group installed, same
no-I/O-in-tests philosophy as everywhere else in this project.

Real bug this guards against (2026-10-02): write_file_chip_cells's
first version sent every chip cell for a run in ONE batchUpdate call,
which a real 25-invoice run blew past Google's own per-call limit on
how many chip-bearing requests one batchUpdate may contain -- a 400
error that only ever showed up against the live API, since the
Protocol-level FakeSheetsClient used everywhere else just records
calls rather than exercising GoogleSheetsClient's actual request-
building code.
"""

from __future__ import annotations

from landed_cost.sheets.google_sheets_client import GoogleSheetsClient


class _FakeExecutable:
    def __init__(self, calls: list[dict], body: dict):
        self._calls = calls
        self._body = body

    def execute(self) -> dict:
        self._calls.append(self._body)
        return {}


class _FakeSpreadsheets:
    def __init__(self, calls: list[dict]):
        self._calls = calls

    def batchUpdate(self, spreadsheetId: str, body: dict) -> _FakeExecutable:
        return _FakeExecutable(self._calls, body)


class _FakeService:
    def __init__(self):
        self.batch_update_calls: list[dict] = []

    def spreadsheets(self) -> _FakeSpreadsheets:
        return _FakeSpreadsheets(self.batch_update_calls)


def test_write_file_chip_cells_builds_one_chip_run_per_file():
    service = _FakeService()
    client = GoogleSheetsClient(service)

    client.write_file_chip_cells("sheet1", 12345, [(170, 5, ["drive-id-1"])])

    assert len(service.batch_update_calls) == 1
    requests = service.batch_update_calls[0]["requests"]
    assert len(requests) == 1
    update_cells = requests[0]["updateCells"]
    assert update_cells["start"] == {"sheetId": 12345, "rowIndex": 169, "columnIndex": 5}
    assert update_cells["fields"] == "userEnteredValue,chipRuns"
    cell = update_cells["rows"][0]["values"][0]
    assert cell["userEnteredValue"]["stringValue"] == "@"
    assert cell["chipRuns"] == [
        {"startIndex": 0, "chip": {"richLinkProperties": {"uri": "https://drive.google.com/file/d/drive-id-1/view"}}}
    ]


def test_write_file_chip_cells_places_multiple_chips_in_one_cell_correctly():
    service = _FakeService()
    client = GoogleSheetsClient(service)

    client.write_file_chip_cells("sheet1", 12345, [(170, 5, ["id-a", "id-b", "id-c"])])

    cell = service.batch_update_calls[0]["requests"][0]["updateCells"]["rows"][0]["values"][0]
    assert cell["userEnteredValue"]["stringValue"] == "@, @, @"
    # "@, @, @" -- placeholders at 0, 3, 6 (each "@" is 1 char, each
    # ", " separator is 2 chars).
    assert [run["startIndex"] for run in cell["chipRuns"]] == [0, 3, 6]
    assert [run["chip"]["richLinkProperties"]["uri"] for run in cell["chipRuns"]] == [
        "https://drive.google.com/file/d/id-a/view",
        "https://drive.google.com/file/d/id-b/view",
        "https://drive.google.com/file/d/id-c/view",
    ]


def test_write_file_chip_cells_does_nothing_for_an_empty_list():
    service = _FakeService()
    client = GoogleSheetsClient(service)

    client.write_file_chip_cells("sheet1", 12345, [])

    assert service.batch_update_calls == []


def test_write_file_chip_cells_splits_across_calls_past_the_real_api_limit():
    # Real bug (2026-10-02): a 25-invoice run with up to 2 chip cells
    # each -- far more than Google's own per-batchUpdate limit on
    # chip-bearing requests -- was sent as ONE call and rejected
    # outright ("The number of drive chip requests exceeds the limit
    # of 10"). 15 single-chip cells must split into multiple calls of
    # at most 10 chips each.
    service = _FakeService()
    client = GoogleSheetsClient(service)
    cells = [(170 + i, 5, [f"id-{i}"]) for i in range(15)]

    client.write_file_chip_cells("sheet1", 12345, cells)

    assert len(service.batch_update_calls) == 2
    first_requests = service.batch_update_calls[0]["requests"]
    second_requests = service.batch_update_calls[1]["requests"]
    assert len(first_requests) == 10
    assert len(second_requests) == 5
    # Every cell is still written exactly once, across both calls, in
    # order -- splitting must never drop or duplicate a cell.
    all_uris = [
        run["chip"]["richLinkProperties"]["uri"]
        for call in service.batch_update_calls
        for req in call["requests"]
        for run in req["updateCells"]["rows"][0]["values"][0]["chipRuns"]
    ]
    assert all_uris == [f"https://drive.google.com/file/d/id-{i}/view" for i in range(15)]


def test_write_file_chip_cells_counts_multi_chip_cells_toward_the_batch_limit():
    # A cell holding several chips (a combined multi-file link) must
    # count toward the same 10-chip-per-batch cap as single-chip cells
    # -- conservative by total chips, not by request count, since the
    # real API limit's exact counting rule isn't confirmed either way.
    service = _FakeService()
    client = GoogleSheetsClient(service)
    cells = [
        (170, 5, ["a", "b", "c", "d", "e", "f", "g", "h"]),  # 8 chips
        (171, 5, ["i", "j", "k"]),  # 3 more -- would make 11, over the cap
    ]

    client.write_file_chip_cells("sheet1", 12345, cells)

    assert len(service.batch_update_calls) == 2
    assert len(service.batch_update_calls[0]["requests"]) == 1
    assert len(service.batch_update_calls[1]["requests"]) == 1


def test_write_file_chip_cells_clears_a_cell_with_no_file_ids():
    service = _FakeService()
    client = GoogleSheetsClient(service)

    client.write_file_chip_cells("sheet1", 12345, [(170, 5, [])])

    cell = service.batch_update_calls[0]["requests"][0]["updateCells"]["rows"][0]["values"][0]
    assert cell == {"userEnteredValue": {"stringValue": ""}, "chipRuns": []}

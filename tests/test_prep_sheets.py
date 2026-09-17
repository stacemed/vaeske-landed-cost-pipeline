from landed_cost.drive.client import FOLDER_MIME_TYPE, DriveFile
from landed_cost.drive.prep_sheets import find_prep_sheet_link


class FakeDriveClient:
    """In-memory stand-in for a real Drive client, keyed by folder id."""

    def __init__(self, children: dict[str, list[DriveFile]]):
        self._children = children

    def list_children(self, folder_id: str) -> list[DriveFile]:
        return self._children.get(folder_id, [])


def _file(file_id: str, name: str) -> DriveFile:
    return DriveFile(id=file_id, name=name, mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def _folder(file_id: str, name: str) -> DriveFile:
    return DriveFile(id=file_id, name=name, mime_type=FOLDER_MIME_TYPE)


def test_find_prep_sheet_link_matches_real_filename():
    client = FakeDriveClient({
        "prep-folder": [
            _file("1", "Prep Instructions for John Grattan FBABEE 2025-01 JAN.xlsx"),
            _file("2", "Prep Instructions for John Grattan FBABEE 2025-02 FEB.xlsx"),
        ]
    })

    link, status = find_prep_sheet_link(client, "prep-folder", "2025-01 JAN")

    assert link == "Prep Instructions for John Grattan FBABEE 2025-01 JAN.xlsx"
    assert status == "matched"


def test_find_prep_sheet_link_excludes_the_template_file():
    client = FakeDriveClient({
        "prep-folder": [
            _file("1", "Template Prep Instructions for John Grattan FBABEE YYYY-MM MONTH.xlsx"),
        ]
    })

    link, status = find_prep_sheet_link(client, "prep-folder", "2025-01 JAN")

    assert link == ""
    assert "no Prep Instructions file found" in status


def test_find_prep_sheet_link_flags_ambiguous_month_with_multiple_variants():
    # Real pattern seen 2026-09-18: some months have more than one real
    # file (e.g. a "- Standard Speed" variant) -- never guess which.
    client = FakeDriveClient({
        "prep-folder": [
            _file("1", "Prep Instructions for John Grattan FBABEE 2024-01 JAN - Standard Speed.xlsx"),
            _file("2", "Prep Instructions for John Grattan FBABEE 2024-01 JAN - Express.xlsx"),
        ]
    })

    link, status = find_prep_sheet_link(client, "prep-folder", "2024-01 JAN")

    assert link == ""
    assert "ambiguous" in status


def test_find_prep_sheet_link_ignores_folders():
    client = FakeDriveClient({
        "prep-folder": [
            _folder("1", "Prep Instructions for John Grattan FBABEE 2025-01 JAN"),
        ]
    })

    link, status = find_prep_sheet_link(client, "prep-folder", "2025-01 JAN")

    assert link == ""
    assert "no Prep Instructions file found" in status


def test_find_prep_sheet_link_no_match_for_unrelated_month():
    client = FakeDriveClient({
        "prep-folder": [
            _file("1", "Prep Instructions for John Grattan FBABEE 2025-02 FEB.xlsx"),
        ]
    })

    link, status = find_prep_sheet_link(client, "prep-folder", "2025-01 JAN")

    assert link == ""
    assert "no Prep Instructions file found" in status

"""Finds a month's Prep Instructions file for 1 TRANSACTIONS Section D's
"Prep sheet link" column.

Real files (2026-09-18) are named
"Prep Instructions for John Grattan FBABEE <YYYY-MM MON>[ - free text]"
(e.g. "Prep Instructions for John Grattan FBABEE 2025-01 JAN.xlsx"), plus
a "Template Prep Instructions for John Grattan FBABEE YYYY-MM MONTH.xlsx"
that must never be matched. A real 2024 folder (2026-09-22) showed every
file there prefixed "Copy of " from being moved/duplicated -- matched on
the filename CONTAINING the expected name, not starting with it, so a
"Copy of " (or any other) prefix doesn't hide an otherwise-real file. A
month sometimes has more than one real file -- confirmed in that same
folder: two different January 2024 variants ("- Standard Speed" and
"- Fast Line"), and two files both literally named "...2024-06 JUN.xlsx"
(different sizes -- an actual duplicate, not just a differently-named
variant). Ambiguous either way, so per the user's own choice
(2026-09-18) this only fills the link on an unambiguous single match and
flags otherwise, rather than guessing which one is the real one.
"""

from __future__ import annotations

from .client import DriveClient

_FILENAME_PREFIX = "prep instructions for john grattan fbabee"


def find_prep_sheet_link(
    drive_client: DriveClient, prep_sheet_folder_id: str, label: str
) -> tuple[str, str]:
    """Return ``(filename_or_empty, status)`` for the one Prep
    Instructions file matching ``label`` (e.g. "2025-01 JAN"), excluding
    the template file. ``filename_or_empty`` is only ever non-empty when
    exactly one real file matches.
    """
    wanted = f"{_FILENAME_PREFIX} {label.lower()}"
    matches = [
        child
        for child in drive_client.list_children(prep_sheet_folder_id)
        if not child.is_folder
        and "template" not in child.name.lower()
        and wanted in child.name.lower()
    ]
    if not matches:
        return "", f"no Prep Instructions file found for {label!r}"
    if len(matches) > 1:
        names = ", ".join(m.name for m in matches)
        return "", f"{len(matches)} Prep Instructions files found for {label!r} -- ambiguous: {names}"
    return matches[0].name, "matched"

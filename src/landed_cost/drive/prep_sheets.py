"""Finds a month's Prep Instructions file for 1 TRANSACTIONS Section D's
"Prep sheet link" column.

Real files (2026-09-18) live in one Drive folder, named
"Prep Instructions for John Grattan FBABEE <YYYY-MM MON>[ - free text]"
(e.g. "Prep Instructions for John Grattan FBABEE 2025-01 JAN.xlsx"), plus
a "Template Prep Instructions for John Grattan FBABEE YYYY-MM MONTH.xlsx"
that must never be matched. A month sometimes has more than one real file
(e.g. "...2024-01 JAN - Standard Speed.xlsx" alongside another variant for
the same month) -- ambiguous, so per the user's own choice (2026-09-18)
this only fills the link on an unambiguous single match and flags
otherwise, rather than guessing which variant is the real one.
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
    wanted_prefix = f"{_FILENAME_PREFIX} {label.lower()}"
    matches = [
        child
        for child in drive_client.list_children(prep_sheet_folder_id)
        if not child.is_folder
        and "template" not in child.name.lower()
        and child.name.lower().startswith(wanted_prefix)
    ]
    if not matches:
        return "", f"no Prep Instructions file found for {label!r}"
    if len(matches) > 1:
        names = ", ".join(m.name for m in matches)
        return "", f"{len(matches)} Prep Instructions files found for {label!r} -- ambiguous: {names}"
    return matches[0].name, "matched"

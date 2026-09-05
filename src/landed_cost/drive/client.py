"""The minimal Drive surface the ingestion pipeline needs.

Deliberately narrow (list the immediate children of a folder, that's it)
so a real Drive API client and a fake in-memory client used in tests can
both satisfy ``DriveClient`` without either depending on the other, and
without tests needing real credentials or network access.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


class DriveFile(BaseModel):
    """A Drive file or folder, trimmed to the fields ingestion needs."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    mime_type: str
    parent_id: str | None = None

    @property
    def is_folder(self) -> bool:
        return self.mime_type == FOLDER_MIME_TYPE


class DriveClient(Protocol):
    def list_children(self, folder_id: str) -> list[DriveFile]:
        """List the immediate (non-recursive) children of a folder."""
        ...

    def download_file(self, file_id: str) -> bytes:
        """Download a file's raw content."""
        ...

    def rename_file(self, file_id: str, new_name: str) -> None:
        """Rename a file in place."""
        ...

    def move_file(self, file_id: str, new_parent_id: str, old_parent_id: str) -> None:
        """Move a file from one parent folder to another."""
        ...

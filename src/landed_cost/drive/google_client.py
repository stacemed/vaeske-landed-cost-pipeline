"""Real Google Drive client, backed by the Drive v3 API.

Requires the optional ``drive`` dependency group
(``pip install -e ".[drive]"``) plus credentials -- see
docs/DRIVE_INGESTION.md for how to set those up. This module is never
imported by ``landed_cost.drive.ingest`` itself, so the ingestion logic
and its tests never need these dependencies installed; only code that
actually talks to Drive does.
"""

from __future__ import annotations

from typing import Any

from .client import DriveFile

_LIST_FIELDS = "nextPageToken, files(id, name, mimeType, parents)"
_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"


class GoogleDriveClient:
    """Adapts a ``googleapiclient`` Drive v3 service to ``DriveClient``."""

    def __init__(self, service: Any) -> None:
        self._service = service

    @classmethod
    def from_service_account_file(cls, path: str) -> "GoogleDriveClient":
        """Build a client from a service-account JSON key file.

        Only works for folders explicitly shared with that service
        account's email -- for a personal/shared-with-me folder like this
        project's, ``from_authorized_user_file`` is usually simpler.
        """
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        credentials = service_account.Credentials.from_service_account_file(
            path, scopes=[_READONLY_SCOPE]
        )
        return cls(build("drive", "v3", credentials=credentials))

    @classmethod
    def from_authorized_user_file(cls, path: str) -> "GoogleDriveClient":
        """Build a client from a cached OAuth user-token JSON file, as
        produced by the one-time console flow in docs/DRIVE_INGESTION.md.
        """
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        credentials = Credentials.from_authorized_user_file(path, scopes=[_READONLY_SCOPE])
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        return cls(build("drive", "v3", credentials=credentials))

    def list_children(self, folder_id: str) -> list[DriveFile]:
        files: list[DriveFile] = []
        page_token: str | None = None
        query = f"'{folder_id}' in parents and trashed = false"
        while True:
            response = (
                self._service.files()
                .list(
                    q=query,
                    fields=_LIST_FIELDS,
                    pageToken=page_token,
                    pageSize=1000,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            for item in response.get("files", []):
                parents = item.get("parents") or []
                files.append(
                    DriveFile(
                        id=item["id"],
                        name=item["name"],
                        mime_type=item["mimeType"],
                        parent_id=parents[0] if parents else None,
                    )
                )
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return files

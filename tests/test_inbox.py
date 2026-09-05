import pytest

from landed_cost.drive.client import DriveFile
from landed_cost.drive.inbox import (
    DEFAULT_NEEDS_REVIEW_FOLDER_NAME,
    apply_inbox_actions,
    propose_from_text,
    propose_inbox_actions,
)
from landed_cost.models import Category

from test_extract import FREIGHT_INVOICE_TEXT, UNKNOWN_TEXT

FOLDER_MIME = "application/vnd.google-apps.folder"


def _file(file_id: str, name: str, mime_type: str = "application/pdf") -> DriveFile:
    return DriveFile(id=file_id, name=name, mime_type=mime_type)


def _folder(file_id: str, name: str) -> DriveFile:
    return _file(file_id, name, mime_type=FOLDER_MIME)


class FakeDriveClient:
    """In-memory Drive stand-in that also records writes for assertions."""

    def __init__(
        self,
        children: dict[str, list[DriveFile]],
        contents: dict[str, bytes] | None = None,
    ):
        self._children = children
        self._contents = contents or {}
        self.renamed: dict[str, str] = {}
        self.moved: list[tuple[str, str, str]] = []  # (file_id, new_parent, old_parent)

    def list_children(self, folder_id: str) -> list[DriveFile]:
        return self._children.get(folder_id, [])

    def download_file(self, file_id: str) -> bytes:
        return self._contents[file_id]

    def rename_file(self, file_id: str, new_name: str) -> None:
        self.renamed[file_id] = new_name

    def move_file(self, file_id: str, new_parent_id: str, old_parent_id: str) -> None:
        self.moved.append((file_id, new_parent_id, old_parent_id))


def test_propose_from_text_ready_to_file():
    file = _file("f1", "scan001.pdf")
    proposal = propose_from_text(file, FREIGHT_INVOICE_TEXT)

    assert proposal.ready_to_file is True
    assert proposal.proposed_name == "2025-04-21_FBSL_Frei-Bund_JG20250421E_INV-paid.pdf"
    assert proposal.original_name == "scan001.pdf"


def test_propose_from_text_needs_review_for_unrecognized_content():
    file = _file("f1", "scan002.pdf")
    proposal = propose_from_text(file, UNKNOWN_TEXT)

    assert proposal.ready_to_file is False


def test_propose_from_text_handles_empty_extraction():
    file = _file("f1", "scan003.pdf")
    proposal = propose_from_text(file, "")

    assert proposal.ready_to_file is False
    assert any("no text layer" in issue for issue in proposal.extracted.issues)


def test_propose_inbox_actions_skips_subfolders_and_uses_text_extractor():
    client = FakeDriveClient(
        children={
            "inbox": [
                _folder("sub", "Archive"),
                _file("f1", "scan.pdf"),
            ]
        },
        contents={"f1": b"fake-pdf-bytes"},
    )

    proposals = propose_inbox_actions(
        client, "inbox", text_extractor=lambda data: FREIGHT_INVOICE_TEXT
    )

    assert len(proposals) == 1
    assert proposals[0].ready_to_file is True


def test_apply_inbox_actions_files_ready_proposals_into_category_folder():
    client = FakeDriveClient(
        children={
            "root": [
                _folder("comp-folder", "Invoices - Components"),
                _folder("freight-folder", "Invoices - Freight-Bundling"),
                _folder("overhead-folder", "Invoices - Overhead"),
                _folder("review-folder", DEFAULT_NEEDS_REVIEW_FOLDER_NAME),
            ]
        },
        contents={"f1": b"irrelevant"},
    )
    proposal = propose_from_text(_file("f1", "scan.pdf"), FREIGHT_INVOICE_TEXT)
    assert proposal.ready_to_file is True

    apply_inbox_actions(client, [proposal], "root", inbox_folder_id="inbox")

    assert client.renamed["f1"] == "2025-04-21_FBSL_Frei-Bund_JG20250421E_INV-paid.pdf"
    assert client.moved == [("f1", "freight-folder", "inbox")]


def test_apply_inbox_actions_sends_unready_proposals_to_needs_review():
    client = FakeDriveClient(
        children={
            "root": [
                _folder("comp-folder", "Invoices - Components"),
                _folder("freight-folder", "Invoices - Freight-Bundling"),
                _folder("overhead-folder", "Invoices - Overhead"),
                _folder("review-folder", DEFAULT_NEEDS_REVIEW_FOLDER_NAME),
            ]
        },
    )
    proposal = propose_from_text(_file("f1", "scan.pdf"), UNKNOWN_TEXT)
    assert proposal.ready_to_file is False

    apply_inbox_actions(client, [proposal], "root", inbox_folder_id="inbox")

    assert "f1" not in client.renamed
    assert client.moved == [("f1", "review-folder", "inbox")]


def test_apply_inbox_actions_raises_when_needs_review_folder_missing():
    client = FakeDriveClient(children={"root": []})
    proposal = propose_from_text(_file("f1", "scan.pdf"), UNKNOWN_TEXT)

    with pytest.raises(ValueError, match="Needs Review"):
        apply_inbox_actions(client, [proposal], "root", inbox_folder_id="inbox")


def test_apply_inbox_actions_raises_when_target_category_folder_missing():
    client = FakeDriveClient(
        children={"root": [_folder("review-folder", DEFAULT_NEEDS_REVIEW_FOLDER_NAME)]}
    )
    proposal = propose_from_text(_file("f1", "scan.pdf"), FREIGHT_INVOICE_TEXT)
    assert proposal.ready_to_file is True

    with pytest.raises(ValueError, match="Invoices - Freight-Bundling"):
        apply_inbox_actions(client, [proposal], "root", inbox_folder_id="inbox")


def test_apply_inbox_actions_honors_custom_category_folder_names():
    client = FakeDriveClient(
        children={"root": [_folder("review-folder", DEFAULT_NEEDS_REVIEW_FOLDER_NAME)]},
    )
    proposal = propose_from_text(
        _file("f1", "scan.pdf"),
        "WEIMIN HUANG Inspection Invoice #INV-Inspection-1 Invoice Date: 01-Jan-25",
    )
    assert proposal.extracted.category is Category.OVERHEAD
    assert proposal.ready_to_file is True

    custom_names = {
        Category.COMPONENTS: "Comp Invoices",
        Category.FREIGHT_BUNDLING_PACKAGING: "Freight Invoices",
        Category.OVERHEAD: "Overhead Invoices (custom)",
    }

    # The Overhead folder isn't in Drive under either its default or
    # custom name -- the error naming the custom name proves that name
    # (not the default) is what got looked up.
    with pytest.raises(ValueError, match=r"Overhead Invoices \(custom\)"):
        apply_inbox_actions(
            client,
            [proposal],
            "root",
            inbox_folder_id="inbox",
            category_folder_names=custom_names,
        )

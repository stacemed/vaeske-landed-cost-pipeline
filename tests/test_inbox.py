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

# Mimics a real bug (2026-09-15): the PDF's own text layer recognizes the
# vendor and finds an invoice number, but its header -- with the invoice
# date -- isn't in the text layer's output at all, even though the rest of
# the page extracts fine. Distinct from the fully-empty-text-layer case
# full-page OCR already covers.
COMPONENTS_MISSING_DATE_TEXT = """
Shenzhen Minzhi BYJ Trading Company

Invoice # INV-TEST-001 Order details

Some content, but the invoice date isn't in this text layer.
"""

COMPONENTS_DATE_ONLY_SUPPLEMENT_TEXT = "Invoice Date: Mar 3, 2024"


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
        self.downloaded: list[str] = []

    def list_children(self, folder_id: str) -> list[DriveFile]:
        return self._children.get(folder_id, [])

    def download_file(self, file_id: str) -> bytes:
        self.downloaded.append(file_id)
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
    assert any("text layer" in issue for issue in proposal.extracted.issues)


def test_propose_from_text_empty_even_via_ocr_says_so():
    file = _file("f1", "scan004.pdf")
    proposal = propose_from_text(file, "", via_ocr=True)

    assert proposal.ready_to_file is False
    assert any("even via OCR" in issue for issue in proposal.extracted.issues)


def test_propose_from_text_via_ocr_never_ready_even_when_fields_are_clean():
    file = _file("f1", "scan005.pdf")
    proposal = propose_from_text(file, FREIGHT_INVOICE_TEXT, via_ocr=True)

    # Would be ready_to_file if not for via_ocr -- confirmed by the
    # non-OCR test above (test_propose_from_text_ready_to_file).
    assert proposal.ready_to_file is False
    assert proposal.via_ocr is True
    assert any("OCR" in issue for issue in proposal.extracted.issues)
    # The real fields are still there for a human to review -- OCR
    # caution doesn't blank out a good guess, just stops it auto-filing.
    assert proposal.extracted.invoice_number == "JG20250421E"


def test_propose_from_text_via_ocr_false_stays_ready():
    file = _file("f1", "scan006.pdf")
    proposal = propose_from_text(file, FREIGHT_INVOICE_TEXT, via_ocr=False)

    assert proposal.ready_to_file is True
    assert proposal.via_ocr is False


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
        client, "inbox", text_extractor=lambda data: (FREIGHT_INVOICE_TEXT, False)
    )

    assert len(proposals) == 1
    assert proposals[0].ready_to_file is True


def test_propose_inbox_actions_flags_non_pdf_without_downloading():
    # Real bug (2026-09-16): a Google Doc shortcut file (".gdoc", tiny
    # JSON pointer content, not a real PDF) sitting in the Inbox crashed
    # pypdf and took down the whole batch. Now it's flagged and skipped
    # -- download_file is never even called for it.
    client = FakeDriveClient(
        children={
            "inbox": [
                _file("f1", "notes.gdoc", mime_type="application/vnd.google-apps.document"),
                _file("f2", "scan.pdf"),
            ]
        },
        contents={"f2": b"fake-pdf-bytes"},
    )

    proposals = propose_inbox_actions(
        client, "inbox", text_extractor=lambda data: (FREIGHT_INVOICE_TEXT, False)
    )

    assert len(proposals) == 2
    gdoc_proposal = next(p for p in proposals if p.file_id == "f1")
    assert gdoc_proposal.ready_to_file is False
    assert gdoc_proposal.proposed_name == "notes.gdoc"
    assert any("not a PDF" in issue for issue in gdoc_proposal.extracted.issues)
    assert client.downloaded == ["f2"]  # never even tried to download the .gdoc
    pdf_proposal = next(p for p in proposals if p.file_id == "f2")
    assert pdf_proposal.ready_to_file is True


def test_propose_inbox_actions_recovers_from_a_corrupt_pdf_without_losing_the_batch():
    # A single unreadable/corrupt file must not crash the whole run --
    # the other real PDFs in the same Inbox still need to be processed.
    def flaky_extractor(data: bytes) -> tuple[str, bool]:
        if data == b"corrupt":
            raise ValueError("Stream has ended unexpectedly")
        return FREIGHT_INVOICE_TEXT, False

    client = FakeDriveClient(
        children={
            "inbox": [
                _file("f1", "broken.pdf"),
                _file("f2", "scan.pdf"),
            ]
        },
        contents={"f1": b"corrupt", "f2": b"fake-pdf-bytes"},
    )

    proposals = propose_inbox_actions(client, "inbox", text_extractor=flaky_extractor)

    assert len(proposals) == 2
    broken_proposal = next(p for p in proposals if p.file_id == "f1")
    assert broken_proposal.ready_to_file is False
    assert any("could not be read as a PDF" in issue for issue in broken_proposal.extracted.issues)
    good_proposal = next(p for p in proposals if p.file_id == "f2")
    assert good_proposal.ready_to_file is True


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


def test_propose_from_text_merges_supplemental_text_when_primary_incomplete():
    file = _file("f1", "scan.pdf")
    proposal = propose_from_text(
        file, COMPONENTS_MISSING_DATE_TEXT, supplemental_text=COMPONENTS_DATE_ONLY_SUPPLEMENT_TEXT
    )

    assert proposal.extracted.invoice_number == "INV-TEST-001"
    from datetime import date

    assert proposal.extracted.doc_date == date(2024, 3, 3)
    assert proposal.via_ocr is True
    assert any("OCR" in issue for issue in proposal.extracted.issues)
    # Components never auto-file regardless -- but the caution should be
    # there specifically because a field came from the OCR supplement.
    assert proposal.ready_to_file is False


def test_propose_from_text_ignores_supplemental_text_when_already_complete():
    file = _file("f1", "scan.pdf")
    baseline = propose_from_text(file, FREIGHT_INVOICE_TEXT)
    with_supplement = propose_from_text(
        file, FREIGHT_INVOICE_TEXT, supplemental_text="some other unrelated OCR noise"
    )

    assert with_supplement.extracted == baseline.extracted
    assert with_supplement.via_ocr is False


def test_propose_from_text_ignores_supplemental_text_that_adds_nothing():
    file = _file("f1", "scan.pdf")
    proposal = propose_from_text(
        file, COMPONENTS_MISSING_DATE_TEXT, supplemental_text="unrelated noise with no date in it"
    )

    assert proposal.extracted.doc_date is None
    assert proposal.via_ocr is False
    assert not any("OCR" in issue for issue in proposal.extracted.issues)


def test_propose_from_text_full_page_ocr_takes_priority_over_supplemental_text():
    # via_ocr=True already means the whole text came from a full-page OCR
    # pass -- a supplemental_text merge on top of that would be redundant
    # (both readings came from the same rendered page).
    file = _file("f1", "scan.pdf")
    proposal = propose_from_text(
        file, FREIGHT_INVOICE_TEXT, via_ocr=True, supplemental_text=COMPONENTS_DATE_ONLY_SUPPLEMENT_TEXT
    )

    assert proposal.via_ocr is True
    assert any("OCR" in issue for issue in proposal.extracted.issues)


def test_propose_inbox_actions_tries_ocr_supplement_only_when_worth_it():
    client = FakeDriveClient(
        children={
            "inbox": [
                _file("f1", "partial.pdf"),  # recognized vendor, missing date
                _file("f2", "ready.pdf"),  # already complete
            ]
        },
        contents={"f1": b"partial-bytes", "f2": b"ready-bytes"},
    )
    calls: list[bytes] = []

    def ocr_supplement(data: bytes) -> str:
        calls.append(data)
        return COMPONENTS_DATE_ONLY_SUPPLEMENT_TEXT

    def text_extractor(data: bytes) -> tuple[str, bool]:
        return (COMPONENTS_MISSING_DATE_TEXT if data == b"partial-bytes" else FREIGHT_INVOICE_TEXT, False)

    proposals = propose_inbox_actions(
        client, "inbox", text_extractor=text_extractor, ocr_supplement_extractor=ocr_supplement
    )

    assert calls == [b"partial-bytes"]  # never called for the already-ready file
    partial = next(p for p in proposals if p.file_id == "f1")
    from datetime import date

    assert partial.extracted.doc_date == date(2024, 3, 3)
    assert partial.via_ocr is True
    ready = next(p for p in proposals if p.file_id == "f2")
    assert ready.ready_to_file is True
    assert ready.via_ocr is False


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

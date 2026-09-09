"""Turn the Inbox folder's raw files into standardized, filed source
documents.

Two steps, and neither trusts a guess blindly:

1. ``propose_inbox_actions`` reads each Inbox file's PDF text, proposes a
   standardized filename via ``extract_from_text`` + ``propose_filename``,
   and classifies it ``ready_to_file`` (rename + move into its category
   folder) or not (move to the Needs Review folder, original name kept).
2. ``apply_inbox_actions`` actually performs the Drive writes for a set
   of proposals -- kept separate from step 1 so a caller (the CLI script,
   a test) can inspect or dry-run proposals before anything touches
   Drive, per the 2026-09-04 decision that this defaults to a dry run.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

from ..models.enums import Category
from .client import DriveClient, DriveFile
from .extract import ExtractedInvoice, extract_from_text, propose_filename
from .ingest import DEFAULT_CATEGORY_FOLDER_NAMES, find_child_folder
from .pdf_text import extract_text_with_ocr_fallback

DEFAULT_INBOX_FOLDER_NAME = "Inbox"
DEFAULT_NEEDS_REVIEW_FOLDER_NAME = "Needs Review"

_OCR_CAUTION = (
    "text was read via OCR, not a real text layer (this PDF is a scan or "
    "photo) -- OCR misreads characters, so confirm every field by hand "
    "before filing even though it looks complete"
)


class InboxProposal(BaseModel):
    model_config = ConfigDict(frozen=True)

    file_id: str
    original_name: str
    extracted: ExtractedInvoice
    proposed_name: str
    ready_to_file: bool
    via_ocr: bool = False


def _extension_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1] if "." in filename else "pdf"


def propose_from_text(file: DriveFile, text: str, via_ocr: bool = False) -> InboxProposal:
    """Build a proposal from a file's already-extracted text.

    Split out from ``propose_inbox_actions`` so the guessing logic is
    testable without a real PDF or the optional OCR/pypdf dependencies.

    ``via_ocr`` marks text that came from OCR rather than a genuine text
    layer -- OCR misreads characters (confirmed on real files: "Bundle"
    read back as "Bunlde", a stray space inserted inside a reference
    number), so a document read this way never comes back
    ``ready_to_file``, no matter how complete the guess looks; the
    ``_OCR_CAUTION`` issue is added even when every field extracted
    cleanly.
    """
    if not text.strip():
        reason = (
            "could not extract any text from this PDF, even via OCR fallback"
            if via_ocr
            else "could not extract any text from this PDF's text layer"
        )
        extracted = ExtractedInvoice(issues=(reason,))
    else:
        extracted = extract_from_text(text)
        if via_ocr and not extracted.issues:
            extracted = extracted.model_copy(update={"issues": (_OCR_CAUTION,)})

    proposed_name = propose_filename(extracted, _extension_of(file.name))

    return InboxProposal(
        file_id=file.id,
        original_name=file.name,
        extracted=extracted,
        proposed_name=proposed_name,
        ready_to_file=extracted.is_ready_to_file,
        via_ocr=via_ocr,
    )


def propose_inbox_actions(
    client: DriveClient,
    inbox_folder_id: str,
    text_extractor: Callable[[bytes], tuple[str, bool]] = extract_text_with_ocr_fallback,
) -> list[InboxProposal]:
    """Propose an action for every file currently in the Inbox folder.

    Read-only: downloads and reads each file but never renames or moves
    anything -- that's ``apply_inbox_actions``. The default extractor
    tries the PDF's real text layer first and only falls back to OCR
    (slower, needs the optional OCR extras) when that comes back empty.
    """
    proposals: list[InboxProposal] = []
    for child in client.list_children(inbox_folder_id):
        if child.is_folder:
            continue
        text, used_ocr = text_extractor(client.download_file(child.id))
        proposals.append(propose_from_text(child, text, via_ocr=used_ocr))
    return proposals


def apply_inbox_actions(
    client: DriveClient,
    proposals: list[InboxProposal],
    root_folder_id: str,
    inbox_folder_id: str,
    category_folder_names: dict[Category, str] | None = None,
    needs_review_folder_name: str = DEFAULT_NEEDS_REVIEW_FOLDER_NAME,
) -> None:
    """Perform the actual Drive writes for a set of proposals.

    A ``ready_to_file`` proposal is renamed to its proposed filename and
    moved into its category folder. Anything else is moved to the Needs
    Review folder with its original name untouched -- the proposal is a
    record of what was guessed, not something written onto the file, so
    it's still visible via ``propose_inbox_actions`` on a re-run.

    A missing category or Needs Review subfolder is a hard error, same as
    ``ingest_support_docs`` -- surface a typo/rename loudly rather than
    silently misfiling documents.
    """
    names = category_folder_names or DEFAULT_CATEGORY_FOLDER_NAMES
    needs_review_folder = find_child_folder(client, root_folder_id, needs_review_folder_name)
    if needs_review_folder is None:
        raise ValueError(
            f"expected a subfolder named {needs_review_folder_name!r} under "
            f"{root_folder_id!r}, but none was found"
        )

    for proposal in proposals:
        if proposal.ready_to_file and proposal.extracted.category is not None:
            folder_name = names[proposal.extracted.category]
            target_folder = find_child_folder(client, root_folder_id, folder_name)
            if target_folder is None:
                raise ValueError(
                    f"expected a subfolder named {folder_name!r} under "
                    f"{root_folder_id!r} for category "
                    f"{proposal.extracted.category.value!r}, but none was found"
                )
            client.rename_file(proposal.file_id, proposal.proposed_name)
            client.move_file(
                proposal.file_id,
                new_parent_id=target_folder.id,
                old_parent_id=inbox_folder_id,
            )
        else:
            client.move_file(
                proposal.file_id,
                new_parent_id=needs_review_folder.id,
                old_parent_id=inbox_folder_id,
            )

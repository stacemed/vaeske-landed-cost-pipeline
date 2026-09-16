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

2026-09-15: a PDF's real text layer can come back non-empty but still
be missing a field a human can plainly read on the page (confirmed on
a real invoice: the whole invoice-number/date header wasn't in
``extract_text_from_pdf_bytes``'s output, though everything else was).
``propose_inbox_actions`` now tries a second, targeted OCR pass in that
case -- see ``propose_from_text``'s ``supplemental_text`` -- distinct
from the full-page OCR fallback in ``pdf_text.py``, which only ever
triggers when the text layer is entirely empty.

2026-09-16: a real Inbox folder had a ``.gdoc`` shortcut file (a tiny
JSON pointer, not a real PDF -- Google Drive Desktop leaves these behind
for native Docs) sitting alongside real invoices. ``pypdf`` throwing on
it crashed the whole batch, taking the other files' proposals down with
it. ``propose_inbox_actions`` now checks ``mime_type`` before even
downloading a non-PDF file, and catches any parse failure on a real PDF
too (a corrupt file is not hypothetical) -- either way the file gets a
clear issue and lands in Needs Review, and every other file in the same
run still gets processed.
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

_OCR_SUPPLEMENT_CAUTION = (
    "some fields came from OCR of the rendered page, not the PDF's real "
    "text layer, which doesn't include that part of it (seen on invoices "
    "with a header rendered in a way the text layer just skips) -- OCR "
    "misreads characters, so confirm every field by hand before filing "
    "even though it looks complete"
)

_MERGEABLE_FIELDS = ("invoice_number", "doc_date", "doc_type")


def _default_ocr_supplement(data: bytes) -> str:
    from .ocr import extract_text_via_ocr

    return extract_text_via_ocr(data)


def _worth_ocr_supplement(extracted: ExtractedInvoice) -> bool:
    """True when a vendor was recognized but a field is still missing --
    worth the cost of an extra OCR pass to see if it's hiding somewhere
    the real text layer didn't pick up. An unrecognized vendor wouldn't
    be fixed by this (OCR reads the same document, not a different one).
    """
    return extracted.category is not None and not extracted.is_fields_complete


def _filled_in_by(before: ExtractedInvoice, after: ExtractedInvoice) -> bool:
    return any(getattr(before, field) is None and getattr(after, field) is not None for field in _MERGEABLE_FIELDS)


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


def propose_from_text(
    file: DriveFile, text: str, via_ocr: bool = False, supplemental_text: str = ""
) -> InboxProposal:
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

    ``supplemental_text`` is a second pass at the same document (in
    practice, an OCR reading) tried only when ``text`` alone recognized
    a vendor but came up short on a field -- some invoices have a
    header the real text layer just doesn't include, even though the
    rest of the page extracts fine (confirmed on a real file). It's
    appended to ``text`` and re-extracted as one; adopted only if that
    actually fills in something ``text`` alone couldn't, and flagged
    with ``_OCR_SUPPLEMENT_CAUTION`` when it does, same as full-page OCR.
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
        elif (
            not via_ocr
            and supplemental_text.strip()
            and _worth_ocr_supplement(extracted)
        ):
            merged = extract_from_text(f"{text}\n\n{supplemental_text}")
            if _filled_in_by(extracted, merged):
                extracted = merged.model_copy(update={"issues": (*merged.issues, _OCR_SUPPLEMENT_CAUTION)})
                via_ocr = True

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
    ocr_supplement_extractor: Callable[[bytes], str] = _default_ocr_supplement,
) -> list[InboxProposal]:
    """Propose an action for every file currently in the Inbox folder.

    Read-only: downloads and reads each file but never renames or moves
    anything -- that's ``apply_inbox_actions``. The default extractor
    tries the PDF's real text layer first and only falls back to OCR
    (slower, needs the optional OCR extras) when that comes back empty.

    When the text layer wasn't empty but still leaves a recognized
    vendor's document short a field, a second, targeted OCR pass is
    tried and merged in via ``propose_from_text``'s ``supplemental_text``
    -- see there for why a non-empty text layer can still be missing
    part of the page. Only run when actually worth it, so a file that's
    already complete (or whose vendor isn't recognized at all) never
    pays the extra OCR cost.
    """
    proposals: list[InboxProposal] = []
    for child in client.list_children(inbox_folder_id):
        if child.is_folder:
            continue
        if child.mime_type != "application/pdf":
            proposals.append(_unreadable_proposal(
                child,
                f"not a PDF (Drive reports its type as {child.mime_type!r}) -- "
                "this tool only reads PDFs, needs manual filing",
            ))
            continue
        try:
            raw = client.download_file(child.id)
            text, used_ocr = text_extractor(raw)
        except Exception as exc:  # noqa: BLE001 -- a single bad file must not sink the whole batch
            proposals.append(_unreadable_proposal(
                child, f"could not be read as a PDF ({exc}) -- needs manual filing"
            ))
            continue
        proposal = propose_from_text(child, text, via_ocr=used_ocr)
        if not used_ocr and _worth_ocr_supplement(proposal.extracted):
            ocr_text = ocr_supplement_extractor(raw)
            proposal = propose_from_text(child, text, via_ocr=False, supplemental_text=ocr_text)
        proposals.append(proposal)
    return proposals


def _unreadable_proposal(file: DriveFile, reason: str) -> InboxProposal:
    """A proposal for a file that couldn't even be read as a PDF -- still
    reported (not silently dropped), always routed to Needs Review, name
    left untouched since there's nothing to base a rename on.
    """
    extracted = ExtractedInvoice(issues=(reason,))
    return InboxProposal(
        file_id=file.id,
        original_name=file.name,
        extracted=extracted,
        proposed_name=file.name,
        ready_to_file=False,
    )


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

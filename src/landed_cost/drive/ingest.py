"""Ingest source documents from the Drive "Support Docs" folder structure.

Layout expected under a root folder (see docs/DRIVE_INGESTION.md), agreed
2026-09-04 to be continuous rather than year-partitioned so new documents
just land in the same folder every year:

    Support Docs/
      Invoices - Components/
      Invoices - Freight-Bundling/
      Invoices - Overhead/

Each category folder holds files named per the ``SourceDocument`` filename
convention. This module never trusts a folder's category by itself -- it
also checks each file's own ``category_tag`` against the folder it was
found in and flags a mismatch, since a file dropped in the wrong folder is
exactly the kind of mistake this is here to catch.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ..models.documents import SourceDocument
from ..models.enums import Category
from .client import DriveClient, DriveFile

DEFAULT_CATEGORY_FOLDER_NAMES: dict[Category, str] = {
    Category.COMPONENTS: "Invoices - Components",
    Category.FREIGHT_BUNDLING_PACKAGING: "Invoices - Freight-Bundling",
    Category.OVERHEAD: "Invoices - Overhead",
}

_EXPECTED_CATEGORY_TAG_PREFIXES: dict[Category, tuple[str, ...]] = {
    Category.COMPONENTS: ("comp",),
    Category.FREIGHT_BUNDLING_PACKAGING: ("frei-bund", "freight", "bundling"),
    Category.OVERHEAD: ("over",),
}


def category_tag_matches(category: Category, category_tag: str) -> bool:
    """Best-effort check that a filename's free-text category tag (e.g.
    'comp', 'Frei-Bund', 'Over') agrees with the folder category it was
    found in.
    """
    tag = category_tag.lower()
    prefixes = _EXPECTED_CATEGORY_TAG_PREFIXES[category]
    return any(tag.startswith(prefix) or prefix.startswith(tag) for prefix in prefixes)


class IngestFailure(BaseModel):
    """A file whose name didn't parse -- flagged for a human, not guessed."""

    model_config = ConfigDict(frozen=True)

    file_id: str
    file_name: str
    error: str


class IngestedDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    file_id: str
    document: SourceDocument
    category_tag_mismatch: bool = False


class CategoryIngestResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: Category
    folder_id: str
    documents: list[IngestedDocument]
    failures: list[IngestFailure]

    @property
    def has_failures(self) -> bool:
        return bool(self.failures)


class RootIngestResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    results: dict[Category, CategoryIngestResult]

    @property
    def all_documents(self) -> list[IngestedDocument]:
        return [doc for result in self.results.values() for doc in result.documents]

    @property
    def all_failures(self) -> list[IngestFailure]:
        return [failure for result in self.results.values() for failure in result.failures]


def find_child_folder(client: DriveClient, parent_id: str, name: str) -> DriveFile | None:
    """Find a direct child folder by exact name, case-insensitive."""
    target = name.strip().lower()
    for child in client.list_children(parent_id):
        if child.is_folder and child.name.strip().lower() == target:
            return child
    return None


def ingest_category_folder(
    client: DriveClient, folder_id: str, category: Category
) -> CategoryIngestResult:
    """Parse every file's filename in one category folder.

    Never raises on a single bad filename -- collects it as an
    IngestFailure so one mis-named file doesn't block the rest of the run.
    Subfolders (if any get created) are skipped, not descended into.
    """
    documents: list[IngestedDocument] = []
    failures: list[IngestFailure] = []

    for child in client.list_children(folder_id):
        if child.is_folder:
            continue
        try:
            parsed = SourceDocument.from_filename(child.name)
        except ValueError as exc:
            failures.append(
                IngestFailure(file_id=child.id, file_name=child.name, error=str(exc))
            )
            continue
        mismatch = not category_tag_matches(category, parsed.category_tag)
        documents.append(
            IngestedDocument(
                file_id=child.id, document=parsed, category_tag_mismatch=mismatch
            )
        )

    return CategoryIngestResult(
        category=category, folder_id=folder_id, documents=documents, failures=failures
    )


def ingest_support_docs(
    client: DriveClient,
    root_folder_id: str,
    category_folder_names: dict[Category, str] | None = None,
) -> RootIngestResult:
    """Ingest every configured category subfolder under a root Drive folder.

    A missing category subfolder is a hard error, not a skip -- the folder
    structure is small and hand-maintained, so a typo or rename should
    surface loudly rather than silently ingesting zero documents for a
    whole category.
    """
    names = category_folder_names or DEFAULT_CATEGORY_FOLDER_NAMES
    results: dict[Category, CategoryIngestResult] = {}
    for category, folder_name in names.items():
        folder = find_child_folder(client, root_folder_id, folder_name)
        if folder is None:
            raise ValueError(
                f"expected a subfolder named {folder_name!r} under "
                f"{root_folder_id!r} for category {category.value!r}, "
                f"but none was found"
            )
        results[category] = ingest_category_folder(client, folder.id, category)
    return RootIngestResult(results=results)


def duplicate_filenames(documents: list[IngestedDocument]) -> list[str]:
    """Flag the same filename appearing more than once across a run --
    e.g. a file accidentally copied into two category folders.
    """
    seen: dict[str, int] = {}
    for doc in documents:
        seen[doc.document.raw_filename] = seen.get(doc.document.raw_filename, 0) + 1
    return [name for name, count in seen.items() if count > 1]

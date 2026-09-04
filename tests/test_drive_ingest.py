import pytest

from landed_cost.drive.client import DriveFile
from landed_cost.drive.ingest import (
    DEFAULT_CATEGORY_FOLDER_NAMES,
    IngestedDocument,
    category_tag_matches,
    duplicate_filenames,
    find_child_folder,
    ingest_category_folder,
    ingest_support_docs,
)
from landed_cost.models import Category, SourceDocument

FOLDER_MIME = "application/vnd.google-apps.folder"


class FakeDriveClient:
    """In-memory stand-in for a real Drive client, keyed by folder id."""

    def __init__(self, children: dict[str, list[DriveFile]]):
        self._children = children

    def list_children(self, folder_id: str) -> list[DriveFile]:
        return self._children.get(folder_id, [])


def _file(file_id: str, name: str, mime_type: str = "application/pdf") -> DriveFile:
    return DriveFile(id=file_id, name=name, mime_type=mime_type)


def _folder(file_id: str, name: str) -> DriveFile:
    return _file(file_id, name, mime_type=FOLDER_MIME)


def test_ingest_category_folder_parses_valid_and_flags_invalid():
    client = FakeDriveClient(
        {
            "folder-1": [
                _file("f1", "2025-01-15_WHSM_comp_INV-1_INV-dep.pdf"),
                _file("f2", "not-a-real-filename.pdf"),
            ]
        }
    )

    result = ingest_category_folder(client, "folder-1", Category.COMPONENTS)

    assert len(result.documents) == 1
    assert result.documents[0].document.invoice_number == "INV-1"
    assert len(result.failures) == 1
    assert result.failures[0].file_name == "not-a-real-filename.pdf"
    assert result.has_failures is True


def test_ingest_category_folder_skips_subfolders():
    client = FakeDriveClient(
        {
            "folder-1": [
                _folder("sub", "Archive"),
                _file("f1", "2025-01-15_WHSM_comp_INV-1_INV-dep.pdf"),
            ]
        }
    )

    result = ingest_category_folder(client, "folder-1", Category.COMPONENTS)

    assert len(result.documents) == 1


def test_category_tag_mismatch_is_flagged_not_rejected():
    # A freight file accidentally dropped in the Components folder.
    client = FakeDriveClient(
        {"folder-1": [_file("f1", "2025-01-15_FBSL_Frei-Bund_JG1_INV-dep.pdf")]}
    )

    result = ingest_category_folder(client, "folder-1", Category.COMPONENTS)

    assert len(result.documents) == 1
    assert result.documents[0].category_tag_mismatch is True
    assert len(result.failures) == 0


@pytest.mark.parametrize(
    "category,tag,expected",
    [
        (Category.COMPONENTS, "comp", True),
        (Category.COMPONENTS, "Comp", True),
        (Category.OVERHEAD, "Over", True),
        (Category.FREIGHT_BUNDLING_PACKAGING, "Frei-Bund", True),
        (Category.OVERHEAD, "comp", False),
        (Category.COMPONENTS, "Over", False),
    ],
)
def test_category_tag_matches(category, tag, expected):
    assert category_tag_matches(category, tag) is expected


def test_find_child_folder_matches_case_insensitively():
    client = FakeDriveClient(
        {"root": [_folder("cf", "invoices - components")]}
    )
    found = find_child_folder(client, "root", "Invoices - Components")
    assert found is not None
    assert found.id == "cf"


def test_find_child_folder_returns_none_when_missing():
    client = FakeDriveClient({"root": []})
    assert find_child_folder(client, "root", "Invoices - Components") is None


def test_ingest_support_docs_raises_on_missing_category_folder():
    client = FakeDriveClient({"root": []})
    with pytest.raises(ValueError):
        ingest_support_docs(client, "root")


def test_ingest_support_docs_covers_all_default_categories():
    children: dict[str, list[DriveFile]] = {
        "root": [
            _folder(f"cf-{category.name}", name)
            for category, name in DEFAULT_CATEGORY_FOLDER_NAMES.items()
        ]
    }
    for category in DEFAULT_CATEGORY_FOLDER_NAMES:
        children[f"cf-{category.name}"] = []
    client = FakeDriveClient(children)

    result = ingest_support_docs(client, "root")

    assert set(result.results.keys()) == set(DEFAULT_CATEGORY_FOLDER_NAMES.keys())
    assert result.all_documents == []
    assert result.all_failures == []


def test_ingest_support_docs_honors_custom_folder_names():
    client = FakeDriveClient(
        {
            "root": [_folder("cf", "Comp Invoices")],
            "cf": [_file("f1", "2025-01-15_WHSM_comp_INV-1_INV-dep.pdf")],
        }
    )

    result = ingest_support_docs(
        client, "root", category_folder_names={Category.COMPONENTS: "Comp Invoices"}
    )

    assert len(result.results[Category.COMPONENTS].documents) == 1


def test_duplicate_filenames_detects_repeats():
    doc = SourceDocument.from_filename("2025-01-15_WHSM_comp_INV-1_INV-dep.pdf")
    docs = [
        IngestedDocument(file_id="a", document=doc),
        IngestedDocument(file_id="b", document=doc),
    ]
    assert duplicate_filenames(docs) == ["2025-01-15_WHSM_comp_INV-1_INV-dep.pdf"]


def test_duplicate_filenames_empty_when_all_unique():
    docs = [
        IngestedDocument(
            file_id="a",
            document=SourceDocument.from_filename("2025-01-15_WHSM_comp_INV-1_INV-dep.pdf"),
        ),
        IngestedDocument(
            file_id="b",
            document=SourceDocument.from_filename("2025-01-16_WHSM_comp_INV-2_INV-dep.pdf"),
        ),
    ]
    assert duplicate_filenames(docs) == []

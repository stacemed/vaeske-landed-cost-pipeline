"""Google Sheets I/O and the QBO -> 1 TRANSACTIONS Section A sync.

Deliberately narrow, matching ``landed_cost.drive``'s split: pure parsing
and planning logic here needs no network access and is fully testable;
``google_sheets_client.py`` is the only module that talks to the real
Sheets API, and only code that actually writes to a live sheet needs it
installed.
"""

from .overhead_register import (
    OverheadRegisterRow,
    build_overhead_register_rows,
    extract_overhead_amount,
)
from .overhead_sync import (
    SectionATransaction,
    match_section_a_row,
    read_existing_e_register,
    read_section_a_rows,
    sync_overhead_register,
)
from .qbo import (
    QboTransaction,
    SectionARow,
    classify_category,
    clean_payee,
    merge_qbo_csv_texts,
    parse_qbo_quickreport_csv,
    plan_section_a_sync,
)
from .section_headers import (
    SECTION_E_TITLE_PATTERN,
    find_section_data_start_row,
    verify_column_header,
)
from .sync import read_existing_section_a, sync_section_a

__all__ = [
    "SECTION_E_TITLE_PATTERN",
    "OverheadRegisterRow",
    "QboTransaction",
    "SectionARow",
    "SectionATransaction",
    "build_overhead_register_rows",
    "classify_category",
    "clean_payee",
    "extract_overhead_amount",
    "find_section_data_start_row",
    "match_section_a_row",
    "merge_qbo_csv_texts",
    "parse_qbo_quickreport_csv",
    "plan_section_a_sync",
    "read_existing_e_register",
    "read_existing_section_a",
    "read_section_a_rows",
    "sync_overhead_register",
    "sync_section_a",
    "verify_column_header",
]

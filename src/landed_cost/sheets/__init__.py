"""Google Sheets I/O and the QBO -> 1 TRANSACTIONS Section A sync.

Deliberately narrow, matching ``landed_cost.drive``'s split: pure parsing
and planning logic here needs no network access and is fully testable;
``google_sheets_client.py`` is the only module that talks to the real
Sheets API, and only code that actually writes to a live sheet needs it
installed.
"""

from .freight_register import (
    FreightRegisterRow,
    base_invoice_number,
    build_freight_register_rows,
    extract_freight_and_bundling,
    extract_payment_amount,
)
from .freight_sync import read_existing_d_register, sync_freight_register
from .overhead_register import (
    OverheadRegisterRow,
    build_overhead_register_rows,
    extract_overhead_amount,
)
from .overhead_sync import read_existing_e_register, sync_overhead_register
from .qbo import (
    QboTransaction,
    SectionARow,
    classify_category,
    clean_payee,
    merge_qbo_csv_texts,
    parse_qbo_quickreport_csv,
    plan_section_a_sync,
)
from .section_a_backfill import SectionATransaction, match_section_a_row, read_section_a_rows
from .section_headers import (
    SECTION_D_TITLE_PATTERN,
    SECTION_E_TITLE_PATTERN,
    find_section_data_start_row,
    verify_column_header,
)
from .sync import read_existing_section_a, sync_section_a

__all__ = [
    "SECTION_D_TITLE_PATTERN",
    "SECTION_E_TITLE_PATTERN",
    "FreightRegisterRow",
    "OverheadRegisterRow",
    "QboTransaction",
    "SectionARow",
    "SectionATransaction",
    "base_invoice_number",
    "build_freight_register_rows",
    "build_overhead_register_rows",
    "classify_category",
    "clean_payee",
    "extract_freight_and_bundling",
    "extract_overhead_amount",
    "extract_payment_amount",
    "find_section_data_start_row",
    "match_section_a_row",
    "merge_qbo_csv_texts",
    "parse_qbo_quickreport_csv",
    "plan_section_a_sync",
    "read_existing_d_register",
    "read_existing_e_register",
    "read_existing_section_a",
    "read_section_a_rows",
    "sync_freight_register",
    "sync_overhead_register",
    "sync_section_a",
    "verify_column_header",
]

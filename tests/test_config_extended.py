"""Extended edge-case tests for scripts/config.py — find_column, read_csv_safe, STANDARD_COLUMNS."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import (
    STANDARD_COLUMNS,
    find_column,
    get_normalized_filename,
    read_csv_safe,
)


# ---------------------------------------------------------------------------
# find_column — additional families and edge cases
# ---------------------------------------------------------------------------

class TestFindColumnExtended:
    def test_date_family_action_date(self):
        result = find_column(["Action Date", "Vendor Name"], "date")
        assert result == "Action Date"

    def test_date_family_date_signed(self):
        result = find_column(["Date Signed", "Amount"], "date")
        assert result == "Date Signed"

    def test_vendor_family_vendor_name(self):
        result = find_column(["vendor_name", "agency"], "vendor")
        assert result == "vendor_name"

    def test_vendor_family_recipient_name(self):
        result = find_column(["recipient_name"], "vendor")
        assert result == "recipient_name"

    def test_vendor_family_company_name(self):
        result = find_column(["company_name"], "vendor")
        assert result == "company_name"

    def test_returns_none_when_no_match(self):
        result = find_column(["irrelevant_col", "another_col"], "vendor")
        assert result is None

    def test_returns_none_for_empty_columns(self):
        result = find_column([], "vendor")
        assert result is None

    def test_case_insensitive_vendor(self):
        result = find_column(["VENDOR_NAME"], "vendor")
        assert result == "VENDOR_NAME"

    def test_case_insensitive_date(self):
        result = find_column(["DATE SIGNED"], "date")
        assert result == "DATE SIGNED"

    def test_prefers_earlier_candidate_over_later(self):
        # "vendor_name" appears before "recipient_name" in the vendor family list
        # If both present, should return "vendor_name"
        result = find_column(["recipient_name", "vendor_name"], "vendor")
        assert result == "vendor_name"

    def test_amount_family_federal_action_obligation(self):
        result = find_column(["Federal Action Obligation"], "amount")
        assert result == "Federal Action Obligation"

    def test_pop_state_family(self):
        result = find_column(["Place of Performance State Code"], "pop_state")
        assert result == "Place of Performance State Code"

    def test_unknown_family_returns_none(self):
        result = find_column(["foo", "bar"], "nonexistent_family")
        assert result is None

    def test_contract_id_piid(self):
        result = find_column(["PIID", "Award Date"], "contract_id")
        assert result == "PIID"


# ---------------------------------------------------------------------------
# read_csv_safe — edge cases
# ---------------------------------------------------------------------------

class TestReadCsvSafeExtended:
    def test_header_only_returns_empty_dataframe(self, tmp_path):
        p = tmp_path / "header_only.csv"
        p.write_text("col_a,col_b\n", encoding="utf-8")
        df = read_csv_safe(p)
        assert len(df) == 0
        assert list(df.columns) == ["col_a", "col_b"]

    def test_single_row_returns_one_row(self, tmp_path):
        p = tmp_path / "one_row.csv"
        p.write_text("name,amount\nAcme,1000\n", encoding="utf-8")
        df = read_csv_safe(p)
        assert len(df) == 1

    def test_trailing_whitespace_in_header_cleaned(self, tmp_path):
        p = tmp_path / "trailing.csv"
        p.write_text("col_a  ,col_b  \nfoo,bar\n", encoding="utf-8")
        df = read_csv_safe(p)
        assert "col_a" in df.columns
        assert "col_b" in df.columns

    def test_cp1252_fallback(self, tmp_path):
        p = tmp_path / "cp1252.csv"
        # cp1252-specific character: € (0x80)
        p.write_bytes(b"vendor,amount\nTest\x80Corp,100\n")
        df = read_csv_safe(p)
        assert len(df) == 1
        assert "vendor" in df.columns


# ---------------------------------------------------------------------------
# get_normalized_filename
# ---------------------------------------------------------------------------

class TestGetNormalizedFilename:
    def test_prepends_normalized(self):
        result = get_normalized_filename("myfile.csv")
        assert result.startswith("normalized_")

    def test_preserves_original_name(self):
        result = get_normalized_filename("expansion_fpds_direct.csv")
        assert "expansion_fpds_direct.csv" in result

    def test_deterministic(self):
        name = "my_file.csv"
        assert get_normalized_filename(name) == get_normalized_filename(name)

    def test_returns_string(self):
        assert isinstance(get_normalized_filename("test.csv"), str)


# ---------------------------------------------------------------------------
# STANDARD_COLUMNS constant
# ---------------------------------------------------------------------------

class TestStandardColumns:
    REQUIRED = ["contract_id", "award_date", "vendor_name", "agency_name",
                "obligated_amount", "pop_state", "source_file", "fiscal_year"]

    def test_all_required_keys_present(self):
        for col in self.REQUIRED:
            assert col in STANDARD_COLUMNS, f"Missing: {col}"

    def test_no_duplicates(self):
        assert len(STANDARD_COLUMNS) == len(set(STANDARD_COLUMNS))

    def test_is_list(self):
        assert isinstance(STANDARD_COLUMNS, list)

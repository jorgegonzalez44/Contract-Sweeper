"""Tests for scripts/ingest_report_builder.py — FPDS Report Builder ingestion."""

import csv
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ingest_report_builder import (
    MASTER_COLUMNS,
    _derive_fy_from_filename,
    _map_col,
    _normalize_name,
    _run,
    run,
)


# ---------------------------------------------------------------------------
# _normalize_name
# ---------------------------------------------------------------------------

class TestNormalizeName:
    def test_removes_trailing_inc(self):
        # "CONSTRUCTION" is not a suffix, so it's preserved; "INC" is stripped
        assert _normalize_name("Island Construction Inc") == "ISLAND CONSTRUCTION"

    def test_removes_trailing_llc(self):
        assert _normalize_name("Island Builders LLC") == "ISLAND BUILDERS"

    def test_removes_multiple_trailing_suffixes(self):
        # "CORP" and "INC" are both suffixes; both stripped
        assert _normalize_name("Acme Corp Inc") == "ACME"

    def test_uppercases_result(self):
        result = _normalize_name("acme builders")
        assert result == result.upper()

    def test_strips_punctuation(self):
        # "Alpha," → "ALPHA"; "Inc." → "INC" (stripped as suffix)
        assert _normalize_name("Alpha, Inc.") == "ALPHA"

    def test_empty_string_returns_empty(self):
        assert _normalize_name("") == ""

    def test_nan_returns_empty(self):
        assert _normalize_name(float("nan")) == ""

    def test_none_returns_empty(self):
        assert _normalize_name(None) == ""

    def test_preserves_non_suffix_tokens(self):
        result = _normalize_name("Puerto Rico Construction Group LLC")
        assert "PUERTO" in result
        assert "RICO" in result
        assert "CONSTRUCTION" in result
        assert "GROUP" in result


# ---------------------------------------------------------------------------
# _map_col
# ---------------------------------------------------------------------------

class TestMapCol:
    def test_returns_exact_match(self):
        cols = ["Vendor Name", "Award ID", "Action Obligation"]
        assert _map_col(cols, ["Vendor Name"]) == "Vendor Name"

    def test_returns_case_insensitive_match(self):
        cols = ["vendor name", "award id"]
        assert _map_col(cols, ["Vendor Name"]) == "vendor name"

    def test_returns_none_when_no_match(self):
        cols = ["Unrelated Column", "Another Column"]
        assert _map_col(cols, ["Vendor Name", "Recipient Name"]) is None

    def test_returns_first_matching_candidate(self):
        cols = ["Recipient Name", "Vendor Name"]
        result = _map_col(cols, ["Vendor Name", "Recipient Name"])
        assert result == "Vendor Name"

    def test_empty_column_list_returns_none(self):
        assert _map_col([], ["Vendor Name"]) is None

    def test_empty_candidates_returns_none(self):
        assert _map_col(["Vendor Name", "Award ID"], []) is None


# ---------------------------------------------------------------------------
# _derive_fy_from_filename
# ---------------------------------------------------------------------------

class TestDeriveFyFromFilename:
    def test_two_digit_fy_prefix(self):
        p = Path("Report Builder FY20 Revised.xlsx")
        assert _derive_fy_from_filename(p) == "2020"

    def test_four_digit_fy_prefix(self):
        p = Path("FY_2018_Federal_Procurement.xlsx")
        assert _derive_fy_from_filename(p) == "2018"

    def test_fy23_format(self):
        p = Path("Report Builder FY23 Final rev2.xlsx")
        assert _derive_fy_from_filename(p) == "2023"

    def test_case_insensitive(self):
        p = Path("fy24_data.xlsx")
        assert _derive_fy_from_filename(p) == "2024"

    def test_no_fy_in_filename_returns_empty(self):
        p = Path("contracts_master.xlsx")
        assert _derive_fy_from_filename(p) == ""


# ---------------------------------------------------------------------------
# run() / _run() — integration with tmp_path
# ---------------------------------------------------------------------------

class TestRunIntegration:
    def _make_raw_dir(self, tmp_path: Path) -> Path:
        raw = tmp_path / "data" / "raw"
        raw.mkdir(parents=True)
        return raw

    def _make_processed_dir(self, tmp_path: Path) -> Path:
        p = tmp_path / "data" / "staging" / "processed"
        p.mkdir(parents=True)
        return p

    def test_no_files_returns_zero_rows(self, tmp_path):
        self._make_raw_dir(tmp_path)
        result = run(root=tmp_path)
        assert result["rows"] == 0

    def test_no_files_creates_empty_csv_with_master_columns(self, tmp_path):
        self._make_raw_dir(tmp_path)
        run(root=tmp_path)
        out = tmp_path / "data" / "staging" / "processed" / "pr_report_builder_master.csv"
        assert out.exists()
        df = pd.read_csv(out, dtype=str)
        assert len(df) == 0
        for col in MASTER_COLUMNS:
            assert col in df.columns, f"Missing column: {col}"

    def test_no_files_includes_error_message(self, tmp_path):
        self._make_raw_dir(tmp_path)
        result = run(root=tmp_path)
        assert len(result["errors"]) > 0

    def _write_xlsx(self, path: Path, rows: list[dict]) -> None:
        pd.DataFrame(rows).to_excel(path, index=False)

    def test_with_xlsx_fixture_extracts_pr_rows(self, tmp_path):
        raw = self._make_raw_dir(tmp_path)
        self._write_xlsx(raw / "Report Builder FY22 Revised.xlsx", [
            {
                "Vendor Name": "Island Corp PR", "Award ID": "FA001",
                "Action Obligation": "500000", "Award Date": "2022-01-15",
                "Awarding Agency Name": "DoD", "Place of Performance State Code": "PR",
                "Fiscal Year": "2022",
            },
            {
                "Vendor Name": "Florida Corp", "Award ID": "FA002",
                "Action Obligation": "200000", "Award Date": "2022-02-01",
                "Awarding Agency Name": "DoD", "Place of Performance State Code": "FL",
                "Fiscal Year": "2022",
            },
        ])
        result = _run(root=tmp_path, force=True)
        assert result["rows"] == 1  # only PR row

    def test_force_false_skips_existing_output(self, tmp_path):
        self._make_raw_dir(tmp_path)
        processed = self._make_processed_dir(tmp_path)
        out_path = processed / "pr_report_builder_master.csv"
        existing_df = pd.DataFrame([{"award_id": "X001", "recipient_name": "Pre-existing"}])
        existing_df.to_csv(out_path, index=False, encoding="utf-8")

        result = run(root=tmp_path)
        assert result["rows"] == 1  # reads existing count, does not reprocess

    def test_result_dict_has_required_keys(self, tmp_path):
        self._make_raw_dir(tmp_path)
        result = run(root=tmp_path)
        assert "rows" in result
        assert "path" in result
        assert "errors" in result

    def test_with_xlsx_fixture_output_has_master_columns(self, tmp_path):
        raw = self._make_raw_dir(tmp_path)
        self._write_xlsx(raw / "Report Builder FY23 Revised.xlsx", [{
            "Vendor Name": "PR Tech Corp", "Award ID": "C001",
            "Action Obligation": "1000000", "Award Date": "2023-03-01",
            "Awarding Agency Name": "DHS", "Place of Performance State Code": "PR",
            "Fiscal Year": "2023",
        }])
        _run(root=tmp_path, force=True)
        out = tmp_path / "data" / "staging" / "processed" / "pr_report_builder_master.csv"
        df = pd.read_csv(out, dtype=str)
        for col in MASTER_COLUMNS:
            assert col in df.columns, f"Missing output column: {col}"

    def test_recipient_name_normalized_populated(self, tmp_path):
        raw = self._make_raw_dir(tmp_path)
        self._write_xlsx(raw / "Report Builder FY23 Revised.xlsx", [{
            "Vendor Name": "PR Solutions LLC", "Award ID": "C002",
            "Action Obligation": "500000", "Award Date": "2023-04-01",
            "Awarding Agency Name": "DoD", "Place of Performance State Code": "PR",
            "Fiscal Year": "2023",
        }])
        _run(root=tmp_path, force=True)
        out = tmp_path / "data" / "staging" / "processed" / "pr_report_builder_master.csv"
        df = pd.read_csv(out, dtype=str)
        assert df.loc[0, "recipient_name_normalized"] == "PR SOLUTIONS"

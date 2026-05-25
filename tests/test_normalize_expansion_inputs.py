"""Tests for scripts/normalize_expansion_inputs.py — expansion CSV normalization."""

import logging
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import STANDARD_COLUMNS
from scripts.normalize_expansion_inputs import (
    build_column_map,
    derive_fiscal_year,
    normalize_file,
)


def _logger():
    log = logging.getLogger("test_normalize_expansion")
    log.addHandler(logging.NullHandler())
    return log


# ---------------------------------------------------------------------------
# build_column_map
# ---------------------------------------------------------------------------

class TestBuildColumnMap:
    def test_detects_award_date_column(self):
        cols = ["Award Date", "Vendor Name", "Agency"]
        result = build_column_map(cols)
        assert result["award_date"] == "Award Date"

    def test_detects_vendor_name_column(self):
        cols = ["Vendor Name", "Award ID", "Dollars Obligated"]
        result = build_column_map(cols)
        assert result["vendor_name"] == "Vendor Name"

    def test_detects_obligated_amount_column(self):
        cols = ["Dollars Obligated", "Vendor Name", "Date"]
        result = build_column_map(cols)
        assert result["obligated_amount"] == "Dollars Obligated"

    def test_detects_pop_state_column(self):
        cols = ["Place of Performance State Code", "Amount", "Vendor"]
        result = build_column_map(cols)
        assert result["pop_state"] == "Place of Performance State Code"

    def test_returns_none_for_undetected_family(self):
        cols = ["Unrelated Column A", "Unrelated Column B"]
        result = build_column_map(cols)
        assert result["award_date"] is None
        assert result["vendor_name"] is None

    def test_returns_all_six_standard_keys(self):
        cols = ["contract_id", "award_date", "vendor_name", "agency_name", "obligated_amount", "pop_state"]
        result = build_column_map(cols)
        assert set(result.keys()) == {"contract_id", "award_date", "vendor_name",
                                       "agency_name", "obligated_amount", "pop_state"}

    def test_empty_column_list_returns_all_none(self):
        result = build_column_map([])
        assert all(v is None for v in result.values())


# ---------------------------------------------------------------------------
# derive_fiscal_year
# ---------------------------------------------------------------------------

class TestDeriveFiscalYear:
    def _dates(self, strings: list[str]) -> pd.Series:
        return pd.to_datetime(pd.Series(strings), errors="coerce")

    def test_january_is_same_year(self):
        dates = self._dates(["2022-01-15"])
        result = derive_fiscal_year(dates)
        assert result.iloc[0] == 2022

    def test_september_30_is_same_fiscal_year(self):
        dates = self._dates(["2022-09-30"])
        result = derive_fiscal_year(dates)
        assert result.iloc[0] == 2022

    def test_october_1_is_next_fiscal_year(self):
        dates = self._dates(["2021-10-01"])
        result = derive_fiscal_year(dates)
        assert result.iloc[0] == 2022

    def test_december_31_is_next_fiscal_year(self):
        dates = self._dates(["2021-12-31"])
        result = derive_fiscal_year(dates)
        assert result.iloc[0] == 2022

    def test_nat_produces_na(self):
        dates = self._dates(["not-a-date"])
        result = derive_fiscal_year(dates)
        assert pd.isna(result.iloc[0])

    def test_mixed_valid_and_nat(self):
        dates = self._dates(["2022-01-01", "not-a-date", "2022-10-01"])
        result = derive_fiscal_year(dates)
        assert result.iloc[0] == 2022
        assert pd.isna(result.iloc[1])
        assert result.iloc[2] == 2023

    def test_empty_series_returns_empty(self):
        dates = self._dates([])
        result = derive_fiscal_year(dates)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# normalize_file
# ---------------------------------------------------------------------------

class TestNormalizeFile:
    def _write_csv(self, path: Path, rows: list[dict]) -> None:
        df = pd.DataFrame(rows)
        df.to_csv(path, index=False)

    def test_output_has_all_standard_columns(self, tmp_path):
        csv_path = tmp_path / "input.csv"
        self._write_csv(csv_path, [
            {"Award Date": "2022-01-15", "Vendor Name": "Acme Corp", "Dollars Obligated": "500000"},
        ])
        out_dir = tmp_path / "processed"
        result = normalize_file(csv_path, out_dir, _logger())
        assert result["output_path"] is not None
        df = pd.read_csv(result["output_path"], dtype=str)
        for col in STANDARD_COLUMNS:
            assert col in df.columns, f"Missing column: {col}"

    def test_fiscal_year_derived_from_date(self, tmp_path):
        csv_path = tmp_path / "fy_test.csv"
        self._write_csv(csv_path, [
            {"Award Date": "2021-10-01", "Vendor Name": "Corp A", "Dollars Obligated": "100000"},
        ])
        out_dir = tmp_path / "processed"
        result = normalize_file(csv_path, out_dir, _logger())
        assert 2022 in result["fiscal_years"]

    def test_empty_file_status_warn(self, tmp_path):
        # Write CSV with headers but no data rows so read_csv_safe succeeds
        csv_path = tmp_path / "empty.csv"
        pd.DataFrame(columns=["Award Date", "Vendor Name"]).to_csv(csv_path, index=False)
        out_dir = tmp_path / "processed"
        result = normalize_file(csv_path, out_dir, _logger())
        assert result["status"] == "WARN"
        assert result["input_rows"] == 0

    def test_result_contains_required_keys(self, tmp_path):
        csv_path = tmp_path / "req_keys.csv"
        self._write_csv(csv_path, [{"Award Date": "2022-03-01", "Vendor Name": "X Corp"}])
        out_dir = tmp_path / "processed"
        result = normalize_file(csv_path, out_dir, _logger())
        for key in ("filename", "input_rows", "output_rows", "status", "output_path", "errors"):
            assert key in result

    def test_source_file_column_added(self, tmp_path):
        csv_path = tmp_path / "mysource.csv"
        self._write_csv(csv_path, [{"Award Date": "2023-01-01", "Vendor Name": "PR Corp"}])
        out_dir = tmp_path / "processed"
        result = normalize_file(csv_path, out_dir, _logger())
        df = pd.read_csv(result["output_path"], dtype=str)
        assert df.loc[0, "source_file"] == "mysource"

    def test_output_written_to_output_dir(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        self._write_csv(csv_path, [{"Award Date": "2022-01-01", "Vendor Name": "Test"}])
        out_dir = tmp_path / "processed"
        result = normalize_file(csv_path, out_dir, _logger())
        assert Path(result["output_path"]).parent == out_dir

    def test_row_count_preserved(self, tmp_path):
        csv_path = tmp_path / "multi.csv"
        self._write_csv(csv_path, [
            {"Award Date": "2022-01-01", "Vendor Name": "A"},
            {"Award Date": "2022-02-01", "Vendor Name": "B"},
            {"Award Date": "2022-03-01", "Vendor Name": "C"},
        ])
        out_dir = tmp_path / "processed"
        result = normalize_file(csv_path, out_dir, _logger())
        assert result["output_rows"] == 3

    def test_obligated_amount_coerced_to_numeric(self, tmp_path):
        csv_path = tmp_path / "amounts.csv"
        self._write_csv(csv_path, [
            {"Award Date": "2022-01-01", "Vendor Name": "Corp", "Dollars Obligated": "$1,234,567"},
        ])
        out_dir = tmp_path / "processed"
        result = normalize_file(csv_path, out_dir, _logger())
        df = pd.read_csv(result["output_path"])
        assert pd.to_numeric(df["obligated_amount"], errors="coerce").notna().all()

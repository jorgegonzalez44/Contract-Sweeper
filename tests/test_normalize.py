"""Tests for scripts/normalize_expansion_inputs.py — normalization logic."""

import csv
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.normalize_expansion_inputs import (
    build_column_map,
    derive_fiscal_year,
    normalize_file,
)


# ---------------------------------------------------------------------------
# derive_fiscal_year
# ---------------------------------------------------------------------------

class TestDeriveFiscalYear:
    def test_january_same_year(self):
        dates = pd.to_datetime(pd.Series(["2020-01-15"]))
        fy = derive_fiscal_year(dates)
        assert fy.iloc[0] == 2020

    def test_september_same_year(self):
        dates = pd.to_datetime(pd.Series(["2020-09-30"]))
        fy = derive_fiscal_year(dates)
        assert fy.iloc[0] == 2020

    def test_october_next_year(self):
        dates = pd.to_datetime(pd.Series(["2020-10-01"]))
        fy = derive_fiscal_year(dates)
        assert fy.iloc[0] == 2021

    def test_november_next_year(self):
        dates = pd.to_datetime(pd.Series(["2020-11-15"]))
        fy = derive_fiscal_year(dates)
        assert fy.iloc[0] == 2021

    def test_december_next_year(self):
        dates = pd.to_datetime(pd.Series(["2019-12-31"]))
        fy = derive_fiscal_year(dates)
        assert fy.iloc[0] == 2020

    def test_nat_produces_na(self):
        dates = pd.Series([pd.NaT])
        fy = derive_fiscal_year(dates)
        assert pd.isna(fy.iloc[0])

    def test_mixed_series(self):
        dates = pd.to_datetime(pd.Series(["2020-03-01", pd.NaT, "2020-10-15"]))
        fy = derive_fiscal_year(dates)
        assert fy.iloc[0] == 2020
        assert pd.isna(fy.iloc[1])
        assert fy.iloc[2] == 2021

    def test_boundary_sept30_vs_oct1(self):
        dates = pd.to_datetime(pd.Series(["2020-09-30", "2020-10-01"]))
        fy = derive_fiscal_year(dates)
        assert fy.iloc[0] == 2020
        assert fy.iloc[1] == 2021


# ---------------------------------------------------------------------------
# build_column_map
# ---------------------------------------------------------------------------

class TestBuildColumnMap:
    def test_fpds_columns(self):
        cols = ["PIID", "Date Signed", "Vendor Name", "Contracting Agency Name",
                "Dollars Obligated", "Place of Performance State"]
        cmap = build_column_map(cols)
        assert cmap["contract_id"] == "PIID"
        assert cmap["award_date"] == "Date Signed"
        assert cmap["vendor_name"] == "Vendor Name"
        assert cmap["agency_name"] == "Contracting Agency Name"
        assert cmap["obligated_amount"] == "Dollars Obligated"

    def test_usaspending_columns(self):
        cols = ["Award ID", "Start Date", "Recipient Name", "Awarding Agency",
                "Award Amount", "Place of Performance State Code"]
        cmap = build_column_map(cols)
        assert cmap["contract_id"] == "Award ID"
        assert cmap["award_date"] == "Start Date"
        assert cmap["vendor_name"] == "Recipient Name"
        assert cmap["agency_name"] == "Awarding Agency"
        assert cmap["obligated_amount"] == "Award Amount"
        assert cmap["pop_state"] == "Place of Performance State Code"

    def test_missing_columns_return_none(self):
        cols = ["random_col_a", "random_col_b"]
        cmap = build_column_map(cols)
        assert cmap["contract_id"] is None
        assert cmap["award_date"] is None
        assert cmap["vendor_name"] is None


# ---------------------------------------------------------------------------
# normalize_file (end-to-end)
# ---------------------------------------------------------------------------

class TestNormalizeFile:
    def test_normalizes_fpds_csv(self, sample_fpds_csv, tmp_project):
        import logging
        logger = logging.getLogger("test_normalize")
        output_dir = tmp_project / "data" / "staging" / "processed"

        result = normalize_file(sample_fpds_csv, output_dir, logger)

        assert result["status"] == "OK"
        assert result["input_rows"] == 3
        # 1 duplicate row should be removed
        assert result["output_rows"] == 2
        assert result["date_parsed_pct"] == 100.0
        assert 2020 in result["fiscal_years"]
        assert 2022 in result["fiscal_years"]  # Oct 2021 → FY2022
        assert result["output_path"].exists()

        # Read output and verify columns
        df = pd.read_csv(result["output_path"])
        assert "contract_id" in df.columns or "award_date" in df.columns
        assert "fiscal_year" in df.columns
        assert "source_file" in df.columns

    def test_normalizes_usaspending_csv(self, sample_usaspending_csv, tmp_project):
        import logging
        logger = logging.getLogger("test_normalize")
        output_dir = tmp_project / "data" / "staging" / "processed"

        result = normalize_file(sample_usaspending_csv, output_dir, logger)

        assert result["status"] == "OK"
        assert result["input_rows"] == 2
        assert result["output_rows"] == 2

    def test_handles_empty_csv(self, tmp_project):
        import logging
        logger = logging.getLogger("test_normalize")
        empty_csv = tmp_project / "data" / "staging" / "expansion" / "empty.csv"
        empty_csv.write_text("col_a,col_b\n", encoding="utf-8")
        output_dir = tmp_project / "data" / "staging" / "processed"

        result = normalize_file(empty_csv, output_dir, logger)

        assert result["status"] == "WARN"
        assert result["input_rows"] == 0

    def test_amount_cleaning(self, tmp_project):
        """Dollar signs and commas should be stripped from amounts."""
        import logging
        logger = logging.getLogger("test_normalize")
        csv_path = tmp_project / "data" / "staging" / "expansion" / "amount_test.csv"
        csv_path.write_text(
            "Award ID,Date Signed,Vendor Name,Awarding Agency,Dollars Obligated,pop_state_code\n"
            "C001,2020-05-01,VENDOR A,Agency A,\"$1,234,567.89\",PR\n"
            "C002,2020-06-01,VENDOR B,Agency B,987654.32,PR\n",
            encoding="utf-8",
        )
        output_dir = tmp_project / "data" / "staging" / "processed"
        result = normalize_file(csv_path, output_dir, logger)

        df = pd.read_csv(result["output_path"])
        amounts = df["obligated_amount"].tolist()
        assert abs(amounts[0] - 1234567.89) < 0.01
        assert abs(amounts[1] - 987654.32) < 0.01

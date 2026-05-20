"""Tests for scripts/download_nfip.py."""
import logging
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_nfip").setLevel(logging.CRITICAL)

from scripts.download_nfip import NFIP_COLUMNS, OUTPUT_COLUMNS, _records_to_df, run


class TestRecordsToDf:
    def test_empty_list_returns_output_columns(self):
        df = _records_to_df([])
        assert list(df.columns) == OUTPUT_COLUMNS
        assert len(df) == 0

    def test_renames_known_columns(self):
        records = [{"reportedCity": "San Juan", "amountPaidOnBuildingClaim": "50000"}]
        out = _records_to_df(records)
        assert "reported_city" in out.columns
        assert "paid_building" in out.columns

    def test_output_columns_present(self):
        records = [{"reportedCity": "Ponce"}]
        out = _records_to_df(records)
        assert set(OUTPUT_COLUMNS).issubset(set(out.columns))


class TestColumns:
    def test_output_has_date_of_loss(self):
        assert "date_of_loss" in OUTPUT_COLUMNS

    def test_output_has_paid_building(self):
        assert "paid_building" in OUTPUT_COLUMNS

    def test_nfip_and_output_same_length(self):
        assert len(NFIP_COLUMNS) == len(OUTPUT_COLUMNS)


class TestRunCaching:
    def test_existing_file_skips(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_nfip_claims.csv"
        out.write_text("col\nrow\n")
        result = run(root=tmp_path)
        assert "rows" in result

    def test_result_has_rows_key(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_nfip_claims.csv"
        out.write_text("col\nrow\n")
        result = run(root=tmp_path)
        assert result["rows"] >= 1

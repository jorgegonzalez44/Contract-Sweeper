"""Tests for scripts/download_sbir.py."""
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_sbir").setLevel(logging.CRITICAL)

from scripts.download_sbir import MASTER_COLUMNS, _derive_fiscal_year, _file_has_data, _records_to_df


class TestMasterColumns:
    def test_has_award_id(self):
        assert "award_id" in MASTER_COLUMNS

    def test_has_source_dataset(self):
        assert "source_dataset" in MASTER_COLUMNS

    def test_has_fiscal_year(self):
        assert "fiscal_year" in MASTER_COLUMNS


class TestDeriveFiscalYear:
    def test_int_returns_string(self):
        assert _derive_fiscal_year(2021) == "2021"

    def test_none_returns_empty(self):
        assert _derive_fiscal_year(None) == ""

    def test_float_str_coerced(self):
        assert _derive_fiscal_year("2020.0") == "2020"


class TestFileHasData:
    def test_missing_false(self, tmp_path):
        assert _file_has_data(tmp_path / "x.csv") is False

    def test_header_only_false(self, tmp_path):
        p = tmp_path / "h.csv"
        p.write_text("col\n")
        assert _file_has_data(p) is False

    def test_with_data_true(self, tmp_path):
        p = tmp_path / "d.csv"
        p.write_text("col\nrow\n")
        assert _file_has_data(p) is True


class TestRecordsToDf:
    def test_empty_returns_empty_df(self):
        df = _records_to_df([], "sbir_pr.csv")
        assert list(df.columns) == MASTER_COLUMNS

    def test_record_maps_to_columns(self):
        records = [{"award_number": "A1", "firm": "Acme PR", "amount": "50000",
                    "state_code": "PR", "award_date": "01/01/2022"}]
        df = _records_to_df(records, "sbir_pr.csv")
        assert "source_dataset" in df.columns
        assert df.iloc[0]["source_dataset"] == "sbir"


class TestRunCaching:
    def test_existing_output_skips(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_sbir_master.csv"
        out.write_text("col\nrow\n")
        (tmp_path / "data" / "staging" / "raw" / "sbir").mkdir(parents=True)
        with patch("scripts.download_sbir._paginate", return_value=[]):
            from scripts.download_sbir import run
            result = run(root=tmp_path)
        assert "rows" in result

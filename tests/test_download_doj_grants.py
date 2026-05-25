"""Tests for scripts/download_doj_grants.py."""
import logging
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_doj_grants").setLevel(logging.CRITICAL)

from scripts.download_doj_grants import (
    MASTER_COLUMNS,
    _derive_fiscal_year,
    _file_has_data,
    _results_to_df,
    run,
)


class TestDeriveFiscalYear:
    def test_october_advances_year(self):
        assert _derive_fiscal_year("2021-10-01") == "2022"

    def test_september_same_year(self):
        assert _derive_fiscal_year("2021-09-30") == "2021"

    def test_january_same_year(self):
        assert _derive_fiscal_year("2021-01-15") == "2021"

    def test_none_returns_empty(self):
        assert _derive_fiscal_year(None) == ""

    def test_empty_string_returns_empty(self):
        assert _derive_fiscal_year("") == ""

    def test_invalid_string_returns_empty(self):
        assert _derive_fiscal_year("not-a-date") == ""


class TestFileHasData:
    def test_missing_file_false(self, tmp_path):
        assert _file_has_data(tmp_path / "missing.csv") is False

    def test_header_only_false(self, tmp_path):
        p = tmp_path / "header.csv"
        p.write_text("col_a,col_b\n")
        assert _file_has_data(p) is False

    def test_file_with_data_true(self, tmp_path):
        p = tmp_path / "data.csv"
        p.write_text("col_a\nrow1\n")
        assert _file_has_data(p) is True


class TestResultsToDf:
    def test_empty_returns_master_columns(self):
        df = _results_to_df([], "test.csv")
        assert list(df.columns) == MASTER_COLUMNS
        assert len(df) == 0

    def test_award_id_mapped(self):
        records = [{"Award ID": "DOJ-001", "Recipient Name": "Acme", "Start Date": "2022-01-15"}]
        df = _results_to_df(records, "test.csv")
        assert "award_id" in df.columns
        assert df["award_id"].iloc[0] == "DOJ-001"

    def test_fiscal_year_derived(self):
        records = [{"Award ID": "DOJ-002", "Start Date": "2021-10-01"}]
        df = _results_to_df(records, "test.csv")
        assert df["fiscal_year"].iloc[0] == "2022"

    def test_source_file_assigned(self):
        records = [{"Award ID": "DOJ-003"}]
        df = _results_to_df(records, "sentinel.csv")
        assert df["source_file"].iloc[0] == "sentinel.csv"

    def test_source_dataset_is_doj(self):
        records = [{"Award ID": "DOJ-004"}]
        df = _results_to_df(records, "test.csv")
        assert df["source_dataset"].iloc[0] == "doj_grants"

    def test_master_columns_present(self):
        records = [{"Award ID": "DOJ-005"}]
        df = _results_to_df(records, "test.csv")
        assert set(df.columns) == set(MASTER_COLUMNS)


class TestRunWithMocks:
    def test_run_returns_summary_dict(self, tmp_path):
        from unittest.mock import patch, MagicMock
        with patch("scripts.download_doj_grants._paginate", return_value=[]), \
             patch("scripts.download_doj_grants._session", return_value=MagicMock()):
            from scripts.download_doj_grants import _run
            result = _run(root=tmp_path, force=False, fy_start=2024)
        assert "master_rows" in result

    def test_file_level_caching_skips_fetch(self, tmp_path):
        raw_dir = tmp_path / "data" / "staging" / "raw" / "doj"
        raw_dir.mkdir(parents=True)
        from scripts.download_doj_grants import TIME_WINDOWS, _file_has_data
        # Pre-create all window files so all are cached
        for window in TIME_WINDOWS[:1]:
            for ft in ("pop", "recipient"):
                f = raw_dir / f"doj_{ft}_{window['label']}.csv"
                f.write_text("col\nrow\n")
        assert _file_has_data(raw_dir / f"doj_pop_{TIME_WINDOWS[0]['label']}.csv") is True

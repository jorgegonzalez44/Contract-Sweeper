"""Tests for scripts/download_exim.py."""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_exim").setLevel(logging.CRITICAL)

from scripts.download_exim import (
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

    def test_none_returns_empty(self):
        assert _derive_fiscal_year(None) == ""

    def test_invalid_returns_empty(self):
        assert _derive_fiscal_year("bad") == ""


class TestFileHasData:
    def test_missing_false(self, tmp_path):
        assert _file_has_data(tmp_path / "missing.csv") is False

    def test_header_only_false(self, tmp_path):
        p = tmp_path / "h.csv"
        p.write_text("col\n")
        assert _file_has_data(p) is False

    def test_with_data_true(self, tmp_path):
        p = tmp_path / "d.csv"
        p.write_text("col\nrow\n")
        assert _file_has_data(p) is True


class TestResultsToDf:
    def test_empty_returns_master_columns(self):
        df = _results_to_df([], "test.csv")
        assert list(df.columns) == MASTER_COLUMNS

    def test_source_dataset_is_exim(self):
        records = [{"Award ID": "EX-001"}]
        df = _results_to_df(records, "test.csv")
        assert df["source_dataset"].iloc[0] == "exim"

    def test_master_columns_in_output(self):
        records = [{"Award ID": "EX-002"}]
        df = _results_to_df(records, "test.csv")
        assert set(MASTER_COLUMNS).issubset(set(df.columns))


class TestRunCaching:
    def test_run_with_mocked_paginate(self, tmp_path):
        from unittest.mock import patch, MagicMock
        (tmp_path / "data" / "staging" / "raw" / "exim").mkdir(parents=True)
        (tmp_path / "data" / "staging" / "processed").mkdir(parents=True)
        with patch("scripts.download_exim._paginate", return_value=[]), \
             patch("scripts.download_exim._session", return_value=MagicMock()):
            from scripts.download_exim import _run
            result = _run(root=tmp_path, force=False, fy_start=2025)
        assert "master_rows" in result

    def test_file_has_data_used_for_caching(self, tmp_path):
        raw_dir = tmp_path / "data" / "staging" / "raw" / "exim"
        raw_dir.mkdir(parents=True)
        p = raw_dir / "sentinel.csv"
        p.write_text("col\nrow\n")
        assert _file_has_data(p) is True

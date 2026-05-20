"""Tests for scripts/download_earmarks.py."""
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_earmarks").setLevel(logging.CRITICAL)

from scripts.download_earmarks import (
    EARMARK_COLUMNS,
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

    def test_invalid_string_returns_empty(self):
        assert _derive_fiscal_year("not-a-date") == ""


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
        assert list(df.columns) == EARMARK_COLUMNS
        assert len(df) == 0

    def test_source_dataset_is_earmarks(self):
        records = [{"Award ID": "E-001"}]
        df = _results_to_df(records, "test.csv")
        assert df["source_dataset"].iloc[0] == "earmarks"

    def test_master_columns_complete(self):
        records = [{"Award ID": "E-002", "Recipient Name": "PR Agency", "Start Date": "2022-01-01"}]
        df = _results_to_df(records, "test.csv")
        assert set(EARMARK_COLUMNS).issubset(set(df.columns))


class TestRunCaching:
    def test_existing_file_skips(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_earmarks.csv"
        out.write_text("col\nrow1\n")
        result = run(root=tmp_path)
        assert "rows" in result
        assert result["rows"] >= 1

    def test_run_returns_dict_with_required_keys(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_earmarks.csv"
        out.write_text("col\nrow\n")
        result = run(root=tmp_path)
        assert "rows" in result
        assert "errors" in result
